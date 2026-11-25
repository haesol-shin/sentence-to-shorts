"""Real dev-provider acceptance for generated styles, templates and code BGM.

Reuses the live run, evidence folder and helpers of test_real_main_path.py; see README.md for the
invocation. Without a configured dev provider every test here skips with its reason. The
visual result (shape numbers, regions) and the execution safety (job states, sandbox stages,
call counts) are recorded as separate evidence events; no generated code or prompt is kept.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.jobs import CancelFlag
from app.schemas.bgm_entry import CodeBgm
from app.schemas.common import PinnedRef
from app.schemas.sandbox_io import SandboxKind, SandboxLimits, SandboxRequest
from app.schemas.scene import Scene
from app.schemas.style_manifest import StyleManifest
from app.schemas.template_manifest import TemplateManifest
from tests.e2e import test_real_main_path as main_path
from tests.e2e.real_support import Evidence, numeric_detail
from tests.e2e.support import CORE
from tests.e2e.test_real_main_path import LiveRun, _draft, _new, _real_usage, _render

# The live run and its evidence folder are the main path's fixtures; no second harness.
live_settings = main_path.live_settings
selected_aligner = main_path.selected_aligner
live_run = main_path.live_run



@pytest.fixture(scope="module")
def live_evidence(live_settings: Any) -> Evidence:
    """A sibling of the configured folder, so the main-path suite keeps its own new folder."""
    named = os.environ.get("E2E_EVIDENCE_DIR")
    assert named, "set E2E_EVIDENCE_DIR to a new private evidence directory"
    base = Path(named).expanduser().resolve()
    root = base.with_name(f"{base.name}-generated-code")
    assert not root.is_relative_to(CORE.parent), "evidence must stay outside the checkout"
    evidence = Evidence(root)
    evidence.record({"kind": "providers", "adapters": dict(live_settings.providers.adapters)})
    return evidence


pytestmark = [pytest.mark.realllm, pytest.mark.usefixtures("dev_provider_configured")]

STYLE_ATTEMPTS = 2
SHAPE_REASONS = frozenset({"color_only", "face_unchanged"})
GENERATED_KINDS = frozenset({"style", "template", "bgm_code"})
SANDBOX_LOGGER = "app.tools.sandbox.adapter"
FRAME = (1080, 1920)
BGM_MOOD = "calm"
BGM_SEED = 7


@pytest.fixture(scope="module")
def dev_provider_configured() -> None:
    if os.environ.get("APP_PROFILE") != "dev" or not os.environ.get("APP_LLM_BASE_URL"):
        pytest.skip("the dev provider is not configured (APP_PROFILE=dev and APP_LLM_BASE_URL)")


@dataclass
class Calls:
    llm: list[str] = field(default_factory=list)
    sandbox: list[str] = field(default_factory=list)


@contextmanager
def watched(run: LiveRun) -> Iterator[Calls]:
    """Count LLM tasks and sandbox kinds that reach the shared ports while the block runs."""
    calls = Calls()
    patch = pytest.MonkeyPatch()
    complete, execute = run.runtime.llm.complete, run.runtime.sandbox.run

    def counted_complete(request: Any, **kwargs: Any) -> Any:
        calls.llm.append(request.task.value)
        return complete(request, **kwargs)

    def counted_run(request: Any, **kwargs: Any) -> Any:
        calls.sandbox.append(request.kind.value)
        return execute(request, **kwargs)

    patch.setattr(run.runtime.llm, "complete", counted_complete)
    patch.setattr(run.runtime.sandbox, "run", counted_run)
    try:
        yield calls
    finally:
        patch.undo()


class SandboxHits(logging.Handler):
    """The sandbox adapter's own per-run record: cache_hit is true when the result was reused."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.hits: list[bool] = []

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "event", None) == "sandbox_run":
            self.hits.append(bool(getattr(record, "cache_hit", False)))


@contextmanager
def sandbox_hits() -> Iterator[SandboxHits]:
    logger = logging.getLogger(SANDBOX_LOGGER)
    handler, level = SandboxHits(), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


def _record_safety(run: LiveRun, name: str, job: dict[str, Any]) -> None:
    sandbox = [stage for stage in job["stages"] if stage["stage"] == "sandbox"]
    run.evidence.record({
        "kind": "execution_safety", "name": name, "job_state": job["state"],
        "sandbox_stages": [stage["state"] for stage in sandbox],
        "llm_calls": len(job["usage"]),
        "repairs": max(0, len(sandbox) - 1),
    })


def _record_visual(run: LiveRun, name: str, shape: dict[str, Any]) -> None:
    run.evidence.record({
        "kind": "visual_difference", "name": name, "mode": shape["mode"],
        "passed": shape["passed"], "threshold_iou_x1000": shape["threshold_iou_x1000"],
        "groups": {group: values.get("iou_x1000") for group, values in shape["groups"].items()},
        "face_changed_pixels": shape["face_changed_pixels"],
    })


def _checks(run: LiveRun, ref: dict[str, Any]) -> dict[str, Any]:
    folder = run.runtime.catalog.package_dir("art_style", PinnedRef.model_validate(ref))
    return json.loads((folder / "checks.json").read_text(encoding="utf-8"))["shape"]


def _apply(run: LiveRun, video: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """The style or template is on the video once its plan is applied (confirm when asked)."""
    result = job["result"]
    if result["status"] == "proposed":
        run.api.post(f"/changes/{result['change_id']}/apply", {"base_revision": video["revision"]})
    return run.studio.head(video["id"])


@dataclass
class StyleCase:
    video: dict[str, Any]
    ref: dict[str, Any]
    shape: dict[str, Any]


def _style(
    run: LiveRun, video: dict[str, Any], instruction: str, name: str,
    *, base: dict[str, Any] | None = None, use_reference: bool = False,
) -> StyleCase:
    """Ask for a style; a shape rejection gets one more try, never a lower bar."""
    for attempt in range(1, STYLE_ATTEMPTS + 1):
        job = run.api.wait_terminal(run.api.post("/styles", {
            "video_id": video["id"], "base_revision": video["revision"],
            "instruction": instruction, "base_style": base, "use_reference": use_reference,
        }, expect=202))
        if job["state"] == "succeeded":
            break
        error = job["error"] or {}
        detail = error.get("detail") or {}
        run.evidence.record({
            "kind": "visual_difference", "name": name, "attempt": attempt, "state": "rejected",
            "error_code": error.get("code"), "reason": detail.get("reason"),
            "numbers": numeric_detail(detail),
        })
        reason = detail.get("reason")
        if error.get("code") != "sandbox_output_invalid" or reason not in SHAPE_REASONS:
            pytest.fail(f"{name}: style job failed with {error.get('code')}", pytrace=False)
    else:
        pytest.fail(
            f"{name}: the shape criterion was missed {STYLE_ATTEMPTS} times; "
            "the criterion is not lowered, report to the owner",
            pytrace=False,
        )
    _real_usage(job)
    _record_safety(run, name, job)
    ref = job["result"]["package"]
    shape = _checks(run, ref)
    _record_visual(run, name, shape)
    applied = _apply(run, video, job)
    assert applied["settings"]["visual"]["art_style"] == ref
    return StyleCase(applied, ref, shape)


@pytest.fixture(scope="module")
def request_style(live_run: LiveRun) -> StyleCase:
    with live_run.evidence.case("style-new-from-request"):
        return _style(
            live_run, _new(live_run),
            "Make a chunky cartoon look: tall square heads, wide round bodies and big props.",
            "style-request",
        )


@pytest.fixture(scope="module")
def modified_style(live_run: LiveRun, request_style: StyleCase) -> StyleCase:
    with live_run.evidence.case("style-narrow-eyes"):
        return _style(
            live_run, request_style.video, "눈을 가늘게", "style-narrow-eyes",
            base=request_style.ref,
        )


def test_6_style_dev_providers_connect_sandbox_and_templates(live_run: LiveRun) -> None:
    with live_run.evidence.case("providers-connected"):
        adapters = live_run.runtime.settings.providers.adapters
        assert adapters["llm"] == "openai_compat" and adapters["sandbox"] == "default", (
            "dev provider table changed; report it, do not substitute"
        )
        assert type(live_run.runtime.sandbox).__name__ != "SkeletonSandbox"
        templates = live_run.runtime.services.templates
        assert templates.builtin_parts and templates.builtin_layers, (
            "builtin renderers are not connected to the templates service"
        )
        assert templates.llm is live_run.runtime.llm
        assert templates.sandbox is live_run.runtime.sandbox


def test_6_style_request_text_shapes_differ_from_base(
    live_run: LiveRun, request_style: StyleCase,
) -> None:
    shape = request_style.shape
    compared = {name: group["iou_x1000"] for name, group in shape["groups"].items()
                if group["compared"]}
    assert shape["mode"] == "new" and shape["passed"]
    assert {"head", "body"} <= set(compared), "head and body masks must be compared"
    assert all(value < shape["threshold_iou_x1000"] for value in compared.values()), compared
    manifest = live_run.runtime.catalog.get(
        "art_style", request_style.ref["id"], request_style.ref["revision"])
    assert isinstance(manifest, StyleManifest)
    assert manifest.origin.value == "generated" and manifest.extends is None
    assert manifest.provenance is not None and manifest.provenance.provider == "openai_compat"
    assert manifest.provenance.reference_digest is None


def test_6_style_reference_file_shapes_differ_from_base(live_run: LiveRun) -> None:
    with live_run.evidence.case("style-new-from-reference"):
        named = os.environ.get("E2E_REFERENCE_MP4")
        assert named, "supply the team-created synthetic reference via E2E_REFERENCE_MP4"
        video = _new(live_run)
        with Path(named).open("rb") as source:
            response = live_run.api.http.post(f"/api/v1/videos/{video['id']}/references",
                data={"base_revision": str(video["revision"])},
                files={"file": ("synthetic.mp4", source, "video/mp4")},
                headers={"Idempotency-Key": uuid.uuid4().hex})
        assert response.status_code == 202
        live_run.api.wait_job(response.json())
        analyzed = live_run.studio.head(video["id"])
        summary = analyzed["reference"]
        assert summary is not None, "the analysis kept no reference summary"
        look = summary["style"]
        assert look is not None, "the analysis kept no palette for the style request"
        assert 1 <= len(look["frames"]) <= 4, "the analysis kept no frames to send"
        case = _style(
            live_run, analyzed, "Follow the look of the reference.", "style-reference",
            use_reference=True,
        )
        manifest = live_run.runtime.catalog.get("art_style", case.ref["id"], case.ref["revision"])
        assert isinstance(manifest, StyleManifest) and manifest.provenance is not None
        assert manifest.provenance.reference_digest is not None
        assert case.shape["mode"] == "new" and case.shape["passed"]


def test_7_style_narrow_eyes_changes_the_face(
    live_run: LiveRun, request_style: StyleCase, modified_style: StyleCase,
) -> None:
    shape = modified_style.shape
    assert shape["mode"] == "modify" and shape["passed"]
    assert shape["face_changed_pixels"] > 0
    manifest = live_run.runtime.catalog.get(
        "art_style", modified_style.ref["id"], modified_style.ref["revision"])
    assert isinstance(manifest, StyleManifest)
    assert manifest.extends == PinnedRef.model_validate(request_style.ref)


def test_17_style_saved_reuse_makes_no_style_job_or_style_code_call(
    live_run: LiveRun, modified_style: StyleCase,
) -> None:
    run, source, ref = live_run, modified_style.video, modified_style.ref
    with run.evidence.case("style-saved-reuse"):
        preset = run.api.post(f"/projects/{source['project_id']}/presets", {
            "video_id": source["id"], "name": "Synthetic saved style",
        }, expect=201)
        following = run.api.post(f"/projects/{source['project_id']}/videos",
                                 {"from_video_id": None, "preset_id": preset["id"]}, expect=201)
        assert following["settings"]["visual"]["art_style"] == ref
        assert run.api.get("/jobs", video_id=following["id"])["items"] == []
        with watched(run) as calls:
            following = _draft(run, following, "Explain greenhouse ventilation.", None)
            following, _ = _render(run, following, "saved-style.mp4", art_style_id=ref["id"])
        assert following["settings"]["visual"]["art_style"] == ref
        assert "draft" in calls.llm, "the call counter must see the real draft call"
        jobs = run.api.get("/jobs", video_id=following["id"])["items"]
        assert not {job["kind"] for job in jobs} & GENERATED_KINDS
        assert all(usage["stage"] != "code_llm" for job in jobs for usage in job["usage"])
        assert calls.llm.count("style_code") == 0
        assert calls.sandbox.count("style_parts") == 0
        run.evidence.record({
            "kind": "style_reuse", "style_jobs": 0, "style_code_calls": 0,
            "style_parts_sandbox_runs": 0, "llm_calls": len(calls.llm),
            "sandbox_runs": len(calls.sandbox),
        })


def _layer_clear_x1000(layer: bytes, visual: Any) -> int:
    with Image.open(io.BytesIO(layer)) as opened:
        alpha = opened.convert("RGBA").getchannel("A").crop(
            (visual.x, visual.y, visual.x + visual.w, visual.y + visual.h))
    return alpha.histogram()[0] * 1000 // (visual.w * visual.h)


def test_17_template_new_format_renders_test_scene_and_applies_to_video(
    live_run: LiveRun,
) -> None:
    run = live_run
    with run.evidence.case("template-new-format"):
        video = _draft(run, _new(run), "Explain how a greenhouse works.", None)
        job = run.api.wait_terminal(run.api.post("/templates", {
            "video_id": video["id"], "base_revision": video["revision"],
            "instruction": "A tall title band on top, the picture in the middle and "
                           "captions in a framed box at the bottom, for a quick tips format.",
        }, expect=202))
        assert job["state"] == "succeeded", (job["state"], (job["error"] or {}).get("code"))
        _real_usage(job)
        _record_safety(run, "template", job)
        ref = job["result"]["package"]
        manifest = run.runtime.catalog.get("template", ref["id"], ref["revision"])
        assert isinstance(manifest, TemplateManifest) and manifest.origin.value == "generated"
        assert manifest.provenance is not None and manifest.provenance.provider == "openai_compat"
        others = [run.runtime.catalog.get("template", item.id)
                  for item in run.runtime.catalog.list("template") if item.id != ref["id"]]
        assert others and all(
            manifest.regions != other.regions for other in others  # type: ignore[attr-defined]
        ), "the new template must differ from every existing layout"
        pinned = PinnedRef.model_validate(ref)
        folder = run.runtime.catalog.package_dir("template", pinned)
        scene = Scene.model_validate_json((folder / manifest.test.scene).read_bytes())
        layer, _ = run.runtime.services.templates.layer_drawer(pinned).draw_layer(
            pinned, scene, FRAME, {}, 0, cancel=CancelFlag())
        assert layer is not None
        assert hashlib.sha256(layer).hexdigest() == manifest.test.layer_digest
        clear = _layer_clear_x1000(layer, manifest.regions.visual)
        assert clear >= 500
        run.evidence.record({
            "kind": "template_checks", "test_scene_digest_matches": True,
            "visual_clear_x1000": clear, "caption_modes": [m.value for m in manifest.caption_modes],
        })
        video = _apply(run, video, job)
        assert video["settings"]["format"]["layout"] == ref
        with watched(run) as calls:
            video, _ = _render(run, video, "template.mp4")
        assert video["settings"]["format"]["layout"] == ref
        assert "template_layer" in calls.sandbox, "the generated template must draw the video"
        run.evidence.record({"kind": "template_applied", "state": "rendered",
                             "template_layer_runs": calls.sandbox.count("template_layer")})


@dataclass
class CodeBgmCase:
    project_id: str
    ref: dict[str, Any]
    entry: CodeBgm
    program: str


@pytest.fixture(scope="module")
def code_bgm(live_run: LiveRun) -> CodeBgmCase:
    run = live_run
    with run.evidence.case("bgm-code-loop"):
        project_id = _new(run)["project_id"]
        job = run.api.wait_terminal(run.api.post("/bgm/code", {
            "project_id": project_id, "mood": BGM_MOOD, "seed": BGM_SEED,
            "instruction": "A soft looping tune for a cozy plant-care video.",
        }, expect=202))
        assert job["state"] == "succeeded", (job["state"], (job["error"] or {}).get("code"))
        _real_usage(job)
        _record_safety(run, "bgm-code", job)
        ref = job["result"]["ref"]
        entry = run.runtime.catalog.get("bgm", ref["id"], ref["revision"])
        assert isinstance(entry, CodeBgm)
        folder = run.runtime.catalog.package_dir("bgm", PinnedRef.model_validate(ref))
        program = (folder / entry.program).read_text(encoding="utf-8")
        assert hashlib.sha256(program.encode("utf-8")).hexdigest() == entry.program_digest
        return CodeBgmCase(project_id, ref, entry, program)


def test_14_bgm_code_loop_preview_and_cache_hit(live_run: LiveRun, code_bgm: CodeBgmCase) -> None:
    run, entry = live_run, code_bgm.entry
    assert entry.provenance.provider == "openai_compat" and entry.seed == BGM_SEED
    assert 500 <= entry.duration_ms <= 16000 and entry.loudness_lufs_x10 is not None
    audio = run.api.download(f"/bgm/{entry.id}/audio")
    assert audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
    assert hashlib.sha256(audio).hexdigest() == entry.sha256
    run.evidence.artifact("bgm-loop.wav", audio)
    request = SandboxRequest(
        protocol=1, request_id=uuid.uuid4().hex[:16], kind=SandboxKind.bgm_loop,
        code=code_bgm.program, assets=[], seed=entry.seed,
        input={"params": {"bpm": entry.params.bpm, "bars": entry.params.bars,
                          "mood": entry.params.mood.value}},
        limits=SandboxLimits(max_files=64, max_png_side=1920, max_wav_ms=16000),
    )
    with sandbox_hits() as seen:
        output = run.runtime.sandbox.run(request, cancel=CancelFlag())
    assert seen.hits == [True], "the same code, seed and params must reuse the cached loop"
    assert hashlib.sha256(output.files["loop"]).hexdigest() == entry.sha256
    run.evidence.record({"kind": "bgm_cache", "state": "hit", "loop_ms": entry.duration_ms,
                         "preview_bytes": len(audio)})


def test_14_bgm_swap_rebuilds_no_clip(live_run: LiveRun, code_bgm: CodeBgmCase) -> None:
    run = live_run
    with run.evidence.case("bgm-swap"):
        video = _draft(run, _new(run), "Explain how a greenhouse works.", None)
        for step in ("concept/confirm", "script/confirm"):
            video = run.studio.confirm(video, step)
        video = run.studio.preview(video)
        video = run.studio.confirm(video, "scenes/confirm")
        first = run.studio.generate(video)
        ops: list[dict[str, Any]] = []
        if video["settings"]["audio"]["bgm"]["mood"] != BGM_MOOD:
            ops.append({"op": "set", "path": "/settings/audio/bgm/mood",
                        "value": BGM_MOOD, "origin": "user"})
        ops.append({"op": "set", "path": "/settings/audio/bgm/entry",
                    "value": code_bgm.ref, "origin": "user"})
        video = run.studio.apply_change(video, ops)
        assert video["settings"]["audio"]["bgm"]["entry"] == code_bgm.ref
        with watched(run) as calls:
            second = run.studio.generate(video)
        clip = next(item for item in second["result"]["stages"] if item["stage"] == "clip")
        mix = next(item for item in second["result"]["stages"] if item["stage"] == "mix")
        assert clip["rebuilt_scene_ids"] == []
        assert second["result"]["artifacts"]["clip"] == first["result"]["artifacts"]["clip"]
        assert mix["state"] == "done"
        assert second["result"]["artifacts"]["mix"] != first["result"]["artifacts"]["mix"]
        assert calls.sandbox == [], "a BGM swap must not call the renderer"
        run.evidence.record({"kind": "bgm_swap", "clip_rebuilt_scenes": 0,
                             "sandbox_runs": 0, "mix": mix["state"]})
