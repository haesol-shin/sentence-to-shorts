"""Real dev-provider acceptance, never selected by ordinary test runs.

Requires the aligner selected in core/config/app.yaml, prepared model/media runtimes and private
synthetic reference inputs. Missing adapters fail explicitly; no fixture fallback.
See README.md for invocation and the private evidence layout.
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.bootstrap import AppRuntime, build_runtime
from app.main import create_app
from app.schemas.video import Video
from app.settings import CONFIG_DIR, Settings
from tests.conftest import browser_client, pair
from tests.e2e.real_support import CaseSkipped, Evidence, LiveApi
from tests.e2e.support import CORE, Studio

pytestmark = [pytest.mark.realllm, pytest.mark.usefixtures("selected_aligner")]


REAL_ADAPTER_KINDS = ("llm", "aligner", "transcriber", "media", "downloader")
LLM_ADAPTERS = ("openai_compat", "claude_cli")


def _llm_adapter() -> str:
    """The dev LLM provider under test: the endpoint by default, the official CLI on request."""
    selected = os.environ.get("APP_LLM_ADAPTER") or "openai_compat"
    assert selected in LLM_ADAPTERS, f"APP_LLM_ADAPTER must be one of {LLM_ADAPTERS}"
    return selected


@dataclass
class LiveRun:
    runtime: AppRuntime
    api: LiveApi
    studio: Studio
    evidence: Evidence


@pytest.fixture(scope="module")
def live_settings(request: pytest.FixtureRequest) -> Settings:
    if request.config.getoption("markexpr").strip() != "realllm":
        pytest.skip("live calls require explicit -m realllm selection")
    assert os.environ.get("APP_PROFILE") == "dev", "real acceptance requires APP_PROFILE=dev"
    llm = _llm_adapter()
    if llm == "openai_compat":
        assert os.environ.get("APP_LLM_BASE_URL"), (
            "configure APP_LLM_BASE_URL before live acceptance"
        )
    root = CORE.parent / ".local" / "real-e2e" / uuid.uuid4().hex
    settings = Settings(data_dir=root / "data", cache_dir=root / "cache")
    assert settings.profile == "dev", "APP_PROFILE=dev must select the dev profile"
    assert settings.deployment == "local", "reference link acceptance requires local deployment"
    with (CONFIG_DIR / "app.yaml").open(encoding="utf-8") as handle:
        expected = yaml.safe_load(handle)["providers"]["adapters"]
    if llm != expected["llm"]:
        app = settings.app.model_copy(deep=True)
        app.providers.adapters["llm"] = llm
        settings = Settings(data_dir=root / "data", cache_dir=root / "cache", app=app)
    adapters = settings.providers.adapters
    assert adapters["llm"] == llm, "the selected LLM provider did not reach the settings"
    for kind in REAL_ADAPTER_KINDS[1:]:
        assert adapters[kind] == expected[kind], f"real acceptance needs the {kind} adapter"
    if llm == "openai_compat":
        for alias in ("haiku", "sonnet"):
            assert settings.models.models[alias]["openai_compat"], (
                f"configure APP_LLM_MODEL_{alias.upper()}"
            )
    return settings


@pytest.fixture(scope="module")
def live_evidence(live_settings: Settings) -> Evidence:
    named = os.environ.get("E2E_EVIDENCE_DIR")
    assert named, "set E2E_EVIDENCE_DIR to a new private evidence/I2a directory"
    root = Path(named).expanduser().resolve()
    assert not root.is_relative_to(CORE.parent), "evidence must stay outside the checkout"
    evidence = Evidence(root)
    evidence.record({"kind": "providers", "adapters": dict(live_settings.providers.adapters)})
    return evidence


def _align_python() -> Path | None:
    name = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    candidate = CORE / "align_runtime" / ".venv" / name
    return candidate if candidate.is_file() else None


@pytest.fixture(scope="module")
def selected_aligner(live_settings: Settings, live_evidence: Evidence) -> Iterator[AppRuntime]:
    patch = pytest.MonkeyPatch()
    python = _align_python()
    if not os.environ.get("APP_ALIGN_PYTHON") and python is not None:
        patch.setenv("APP_ALIGN_PYTHON", str(python))
    try:
        try:
            runtime = build_runtime(live_settings)
        except RuntimeError as error:
            if "aligner" not in str(error):
                raise
            live_evidence.record({
                "kind": "setup", "state": "blocked", "reason": "selected_aligner_unavailable"
            })
            pytest.fail(
                "Real main-path acceptance requires the aligner selected in app.yaml; "
                "prepare it before running. No fixture or synthetic timing fallback is used.",
                pytrace=False,
            )
        try:
            yield runtime
        finally:
            runtime.close()
    finally:
        patch.undo()


@pytest.fixture(scope="module")
def live_run(selected_aligner: AppRuntime, live_evidence: Evidence) -> Iterator[LiveRun]:
    runtime = selected_aligner
    urls: list[str] = []
    app = create_app(runtime, pairing_display=urls.append)
    with browser_client(app, runtime.settings.port) as client:
        pair(client, urls[0].split("#pair=", 1)[1])
        deadlines = {
            kind: seconds for kind, seconds in runtime.settings.app.jobs.deadlines_s.items()
            if seconds is not None
        }
        api = LiveApi(client, live_evidence, deadlines)
        yield LiveRun(runtime, api, Studio(api), live_evidence)
    live_evidence.record({"kind": "run", "state": "finished"})


def _new(run: LiveRun, language: str = "en") -> dict[str, Any]:
    project = run.api.post("/projects", {"title": "Synthetic greenhouse", "language": language},
                           expect=201)
    return run.api.post(f"/projects/{project['id']}/videos",
                        {"from_video_id": None, "preset_id": None}, expect=201)


def _set(run: LiveRun, video: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    return run.studio.apply_change(video, [{"op": "set", "path": path,
                                           "value": value, "origin": "user"}])


def _real_usage(job: dict[str, Any]) -> None:
    assert job["usage"], "a real LLM job must report provider/model usage"
    for usage in job["usage"]:
        assert usage["provider"] == _llm_adapter()
        assert usage["model"].strip() and usage["model"] not in {"fixture", "recorded"}
        assert usage["wall_ms"] >= 0
    assert job["stages"], "stage timings must be recorded"
    for stage in job["stages"]:
        assert stage["ended_ms"] is not None and stage["ended_ms"] >= stage["started_ms"]


def _draft(run: LiveRun, video: dict[str, Any], message: str, card: str | None) -> dict[str, Any]:
    job = run.api.wait_job(run.api.post(f"/videos/{video['id']}/draft", {
        "base_revision": video["revision"], "message": message, "card_id": card,
    }, expect=202))
    _real_usage(job)
    drafted = run.studio.head(video["id"])
    assert drafted["topic"] and drafted["script"] is not None and drafted["scene_order"]
    assert drafted["stage"] == "draft"
    return drafted


def _revision_digests(run: LiveRun, video: dict[str, Any]) -> dict[str, str]:
    root = run.runtime.settings.data_dir / "p" / video["project_id"] / "v" / video["id"] / "r"
    found = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.glob("*.json")
    }
    assert found
    return found


def _render(
    run: LiveRun, video: dict[str, Any], name: str, art_style_id: str = "pixel",
) -> tuple[dict[str, Any], str]:
    assert video["settings"]["visual"]["art_style"]["id"] == art_style_id
    blocked = run.api.post(f"/videos/{video['id']}/previews",
                           {"base_revision": video["revision"]}, expect=409)
    assert blocked["code"] == "script_not_confirmed"
    jobs = run.api.get("/jobs", video_id=video["id"])["items"]
    assert all(job["kind"] != "preview" for job in jobs)
    early = run.api.post(f"/videos/{video['id']}/generate",
                         {"base_revision": video["revision"]}, expect=409)
    assert early["code"] == "scenes_not_confirmed"
    video = run.studio.confirm(video, "concept/confirm")
    video = run.studio.confirm(video, "script/confirm")
    assert video["stage"] == "script_confirmed"
    video = run.studio.preview(video)
    build = run.api.get(f"/videos/{video['id']}")["build"]
    assert all(scene["still"]["state"] == "fresh" for scene in build["scenes"].values())
    assert build["actual_ms"] is None and build["estimated_ms"] is not None
    video = run.studio.confirm(video, "scenes/confirm")
    assert video["stage"] == "scenes_confirmed"
    job = run.studio.generate(video)
    assert job["stages"] and all(stage["ended_ms"] is not None for stage in job["stages"])
    view = run.api.get(f"/videos/{video['id']}")
    artifact = view["build"]["final"]["artifact"]
    assert view["build"]["final"]["state"] == "fresh"
    content = run.api.download(f"/videos/{video['id']}/download/mp4")
    path, digest = run.evidence.artifact(name, content)
    assert digest == artifact["digest"]
    info = run.runtime.media.probe(path)
    assert (info.width, info.height, info.fps) == (1080, 1920, 30)
    assert info.sample_rate and info.sample_rate > 0
    actual = view["build"]["actual_ms"]
    assert actual and info.duration_ms and abs(info.duration_ms - actual) <= 300
    assert run.runtime.services.project.validate(Video.model_validate(view["video"])) == []
    return view["video"], digest


@pytest.mark.parametrize("language", ["ko", "en"])
def test_1_real_main_path_records_mp4_digest_and_usage(live_run: LiveRun, language: str) -> None:
    with live_run.evidence.case(f"main-{language}"):
        video = _new(live_run, language)
        message = ("문리프 온실을 소개해 줘." if language == "ko"
                   else "Introduce the Moonleaf greenhouse.")
        material = ("문리프 온실은 보라색 씨앗만 사용한다." if language == "ko"
                    else "The Moonleaf greenhouse uses only violet seeds.")
        video = _set(live_run, video, "/material", [{
            "id": live_run.runtime.project_store.new_id("m"), "text": material,
        }])
        video = _set(live_run, video, "/settings/format/register", "neutral")
        video = _draft(live_run, video, message, None)
        assert video["settings"]["format"]["register"] == "neutral"
        assert video["settings"]["origins"]["/format/register"] == "user"
        assert any(origin in {"llm", "card"}
                   for origin in video["settings"]["origins"].values())
        spoken = " ".join(line["speech_text"] for scene in video["scenes"].values()
                          for line in scene["lines"])
        assert ("보라" if language == "ko" else "violet") in spoken.lower()
        _render(live_run, video, f"{language}.mp4")


def test_3_format_cards_produce_distinct_story_flows(live_run: LiveRun) -> None:
    with live_run.evidence.case("card-flows"):
        texts = []
        for card, structure in (("just_three", "numbered_three"),
                                ("its_like", "single_analogy"), ("what_if", "hypothetical")):
            video = _draft(live_run, _new(live_run), "Explain how a greenhouse works.", card)
            assert video["settings"]["format"]["story_structure"] == structure
            expected = live_run.api.get(f"/catalog/story_structure/{structure}")["beats"]
            actual = [video["scenes"][scene_id]["beat_id"] for scene_id in video["scene_order"]]
            assert list(dict.fromkeys(actual)) == [beat["beat_id"] for beat in expected]
            texts.append(video["script"]["raw_text"])
        assert len(set(texts)) == 3


def _background_variation(
    original: dict[str, Any], following: dict[str, Any], style: dict[str, Any],
) -> int:
    theme = next(item for item in style["themes"]
                 if item["id"] == following["settings"]["visual"]["theme_id"])
    candidates = set(theme["backgrounds"])
    previous: dict[str, list[str]] = {}
    for scene_id in original["scene_order"]:
        scene = original["scenes"][scene_id]
        previous.setdefault(scene["beat_id"], []).append(scene["visual"]["background_id"])
    occurrences: dict[str, int] = {}
    compared = 0
    for scene_id in following["scene_order"]:
        scene = following["scenes"][scene_id]
        background = scene["visual"]["background_id"]
        assert background in candidates
        beat = scene["beat_id"]
        index = occurrences.get(beat, 0)
        occurrences[beat] = index + 1
        old = previous.get(beat, [])
        if len(candidates) > 1 and index < len(old):
            assert background != old[index], (
                "varied background repeated for the same beat despite alternative candidates"
            )
            compared += 1
    if len(candidates) > 1:
        assert compared, "background variation needs corresponding story beats"
    return compared


def test_8_next_video_clears_content_varies_settings_and_preserves_previous(
    live_run: LiveRun,
) -> None:
    with live_run.evidence.case("next-video"):
        original = _draft(live_run, _new(live_run), "Explain how a greenhouse works.", "just_three")
        original, digest = _render(live_run, original, "previous.mp4")
        before = _revision_digests(live_run, original)
        following = live_run.api.post(f"/projects/{original['project_id']}/videos", {
            "from_video_id": original["id"], "preset_id": None,
        }, expect=201)
        assert following["topic"] == "" and following["script"] is None
        assert following["material"] == [] and following["reference"] is None
        assert following["scene_order"] == [] and following["scenes"] == {}
        assert following["derived_from"] == {"video_id": original["id"],
                                             "revision": original["revision"]}
        for key in ("art_style", "character"):
            assert following["settings"]["visual"][key] == original["settings"]["visual"][key]
        assert following["settings"]["audio"]["voice"] == original["settings"]["audio"]["voice"]
        assert following["settings"]["format"] == original["settings"]["format"]
        style_id = original["settings"]["visual"]["art_style"]["id"]
        style = live_run.api.get(f"/catalog/art_style/{style_id}")
        if len(style["themes"]) > 1:
            assert (following["settings"]["visual"]["theme_id"]
                    != original["settings"]["visual"]["theme_id"])
        if len(live_run.runtime.catalog.list("bgm")) > 1:
            assert (following["settings"]["audio"]["bgm"]["entry"]
                    != original["settings"]["audio"]["bgm"]["entry"])
        assert live_run.api.get("/jobs", video_id=following["id"])["items"] == []
        following = _draft(live_run, following, "Explain greenhouse ventilation.", None)
        assert following["settings"]["format"] == original["settings"]["format"]
        following, _ = _render(live_run, following, "next.mp4")
        for key in ("art_style", "character"):
            assert following["settings"]["visual"][key] == original["settings"]["visual"][key]
        assert following["settings"]["audio"]["voice"] == original["settings"]["audio"]["voice"]
        compared = _background_variation(original, following, style)
        assert _revision_digests(live_run, original) == before
        assert live_run.studio.head(original["id"]) == original
        previous = live_run.api.download(f"/videos/{original['id']}/download/mp4")
        assert hashlib.sha256(previous).hexdigest() == digest
        jobs = live_run.api.get("/jobs", video_id=following["id"])["items"]
        assert not {job["kind"] for job in jobs} & {"style", "template", "bgm_code"}
        live_run.evidence.record({"kind": "reuse", "state": "passed",
                                  "content_cleared": True, "previous_unchanged": True,
                                  "background_comparisons": compared})


def _value(settings: dict[str, Any], pointer: str) -> Any:
    value: Any = settings
    for part in pointer.strip("/").split("/"):
        value = value[part]
    return value


def _override_reference_value(run: LiveRun, video: dict[str, Any]) -> None:
    alternatives: dict[str, list[Any]] = {
        "/format/humor": ["none", "light"],
        "/format/scene_count": [3, 4, 5],
        "/format/progress_mode": ["none", "numbered", "phases"],
        "/caption/mode": ["sentence", "phrase"],
        "/audio/bgm/mood": ["curious", "calm", "playful", "tense"],
        "/format/story_structure": ["numbered_three", "single_analogy", "hypothetical"],
        "/format/character_role": ["presenter", "subject", "none"],
        "/format/layout": [
            run.runtime.catalog.pin("template", item.id).model_dump(mode="json")
            for item in run.runtime.catalog.list("template")
        ],
    }
    for pointer, options in alternatives.items():
        if video["settings"]["origins"].get(pointer) != "reference":
            continue
        for value in options:
            if value == _value(video["settings"], pointer):
                continue
            candidate = deepcopy(video)
            parts = pointer.strip("/").split("/")
            node = candidate["settings"]
            for part in parts[:-1]:
                node = node[part]
            node[parts[-1]] = value
            try:
                issues = run.runtime.services.project.validate(Video.model_validate(candidate))
            except ValidationError:
                continue
            if issues:
                continue
            changed = _set(run, video, "/settings" + pointer, value)
            assert _value(changed["settings"], pointer) == value
            assert changed["settings"]["origins"][pointer] == "user"
            return
    raise AssertionError("the analyzed reference must expose an editable recommendation")


def _reference_result(run: LiveRun, video: dict[str, Any], job: dict[str, Any], kind: str) -> None:
    _real_usage(job)
    report = job["result"]["reference"]
    assert report["summary"]["kind"] == kind
    assert report["summary"]["status"] == "analyzed" and report["summary"]["source_deleted"]
    video = run.studio.head(video["id"])
    assert video["reference"] == report["summary"]
    if job["result"]["status"] == "proposed":
        plan = run.api.get(f"/changes/{job['result']['change_id']}")
        assert plan["base_revision"] == video["revision"]
        run.api.post(f"/changes/{job['result']['change_id']}/apply",
                     {"base_revision": video["revision"]})
        video = run.studio.head(video["id"])
    assert video["reference"] == report["summary"]
    origins = video["settings"]["origins"]
    assert "reference" in origins.values(), "analysis must visibly fill settings from the reference"
    assert video["settings"]["format"]["register"] == "neutral"
    assert origins["/format/register"] == "user"
    _override_reference_value(run, video)
    run.evidence.record({"kind": "reference", "source": kind, "state": "analyzed",
                         "source_deleted": True, "user_override": True})


def test_20_synthetic_file_analysis_preserves_user_origins(live_run: LiveRun) -> None:
    with live_run.evidence.case("reference-file"):
        named = os.environ.get("E2E_REFERENCE_MP4")
        assert named, "supply the team-created synthetic reference via E2E_REFERENCE_MP4"
        video = _set(live_run, _new(live_run), "/settings/format/register", "neutral")
        with Path(named).open("rb") as source:
            response = live_run.api.http.post(f"/api/v1/videos/{video['id']}/references",
                data={"base_revision": str(video["revision"])},
                files={"file": ("synthetic.mp4", source, "video/mp4")},
                headers={"Idempotency-Key": uuid.uuid4().hex})
        assert response.status_code == 202
        _reference_result(live_run, video, live_run.api.wait_job(response.json()), "file")


def test_20_allowed_public_link_analysis_succeeds(live_run: LiveRun) -> None:
    try:
        with live_run.evidence.case("reference-allowed-link"):
            url = os.environ.get("E2E_ALLOWED_REFERENCE_URL")
            assert url, "supply one authorized public reference link via E2E_ALLOWED_REFERENCE_URL"
            video = _set(live_run, _new(live_run), "/settings/format/register", "neutral")
            submitted = live_run.api.post(f"/videos/{video['id']}/references/link", {
                "base_revision": video["revision"], "url": url,
            }, expect=202)
            job = live_run.api.wait_terminal(submitted)
            code = (job["error"] or {}).get("code")
            if job["state"] == "failed" and code == "download_blocked" and (
                os.environ.get("E2E_SKIP_BLOCKED_ALLOWED_LINK") == "1"
            ):
                live_run.evidence.record({"kind": "reference", "source": "link",
                                          "state": "skipped", "reason": "download_blocked"})
                raise CaseSkipped("the link host refused this runner (download_blocked)")
            assert job["state"] == "succeeded", (job["kind"], job["state"], code)
            _reference_result(live_run, video, job, "link")
    except CaseSkipped as skipped:
        pytest.skip(str(skipped))


def test_20_login_required_link_returns_download_blocked(live_run: LiveRun) -> None:
    with live_run.evidence.case("reference-blocked-link"):
        url = os.environ.get("E2E_BLOCKED_REFERENCE_URL")
        assert url, "supply a login-required link via E2E_BLOCKED_REFERENCE_URL"
        video = _new(live_run)
        before = live_run.studio.head(video["id"])
        submitted = live_run.api.post(f"/videos/{video['id']}/references/link", {
            "base_revision": video["revision"], "url": url,
        }, expect=202)
        job = live_run.api.wait_terminal(submitted)
        assert job["state"] == "failed" and job["error"]["code"] == "download_blocked"
        assert live_run.studio.head(video["id"]) == before
        live_run.evidence.record({"kind": "reference", "source": "login-required-link",
                                  "state": "download_blocked"})
