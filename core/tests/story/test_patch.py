"""Patch validation: locks, origins, targets, prompts and the one repair."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.ports import AppError, LlmRequest, LlmResult, LlmTask, UnknownCatalogId
from app.schemas.change import Target
from app.schemas.common import PERSONAL_OWNER_ID, ContractModel, Origin, PinnedRef
from app.schemas.format_card import FormatCard, StoryStructure
from app.schemas.job import Stage, Usage
from app.schemas.style_manifest import StyleManifest
from app.schemas.template_manifest import TemplateManifest
from app.schemas.video import Video
from app.schemas.voice_manifest import VoiceManifest
from app.services.story.patch import (
    PROMPT_ROOT,
    SkipReason,
    ValuePatch,
    build_ops,
    complete_json,
    load_prompt,
)

CORE = Path(__file__).resolve().parents[2]
REPO = CORE.parent
VIDEO_FIXTURE = REPO / "fixtures" / "contracts" / "valid" / "video_ko_just_three.json"
MATERIAL_ID = "m_0hzb7bexv28termtt2ypc6trzt"
STAGES = {
    LlmTask.draft: Stage.llm_draft,
    LlmTask.script: Stage.llm_script,
    LlmTask.split: Stage.llm_split,
    LlmTask.chat: Stage.llm_chat,
}
OWNED_ROUTES = ("chat", "draft", "script.default", "script.numbered_three", "split")


class NotCancelled:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


class FakeContext:
    """Job context double: records usage and keeps the job deadline fixed."""

    def __init__(self) -> None:
        self.usages: list[Usage] = []
        self.progress_calls: list[tuple[int, int]] = []

    @property
    def owner_id(self) -> str:
        return PERSONAL_OWNER_ID

    @property
    def cancel(self) -> NotCancelled:
        return NotCancelled()

    @property
    def deadline(self) -> float:
        return 1.0

    @property
    def job_dir(self) -> Path:
        return Path(".")

    @property
    def input(self) -> dict[str, Any]:
        return {}

    def progress(self, *, done: int, total: int, waiting_on: Any = None) -> None:
        self.progress_calls.append((done, total))

    def stage(self, stage: Stage) -> Any:
        return contextlib.nullcontext()

    def checkpoint(self, record: Any) -> None:
        return None

    def record_usage(self, usage: Usage) -> None:
        self.usages.append(usage)

    def record_request(self, request: Any) -> None:
        return None


class RecordingLlm:
    """LLM double that replays queued parsed payloads and records requests."""

    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[LlmRequest] = []

    def complete(
        self, req: LlmRequest, *, owner_id: str, cancel: Any, deadline: float,
        on_request: Any = None,
    ) -> LlmResult:
        self.requests.append(req)
        if not self.responses:
            raise AssertionError(f"no recorded response for {req.route}")
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return LlmResult(
            text=json.dumps(payload, ensure_ascii=False),
            parsed=payload,
            usage=Usage(
                stage=STAGES[req.task],
                provider="fake",
                model="fake",
                effort=None,
                input_tokens=None,
                output_tokens=None,
                cache_read_tokens=None,
                cache_write_tokens=None,
                wall_ms=0,
                retries=0,
            ),
        )

    def auth_state(self, owner_id: str) -> str:
        return "ok"


FILE_MODELS: dict[str, tuple[type[ContractModel], tuple[str, ...]]] = {
    "format_card": (FormatCard, ("app", "catalog", "format_cards")),
    "story_structure": (StoryStructure, ("app", "catalog", "story_structures")),
}
PACKAGE_MODELS: dict[str, tuple[type[ContractModel], str]] = {
    "template": (TemplateManifest, "templates"),
    "art_style": (StyleManifest, "art_styles"),
    "voice": (VoiceManifest, "voices"),
}


class StubCatalog:
    """Catalog double that reads the real builtin manifests without file checks."""

    def get(self, kind: str, item_id: str, revision: str | None = None) -> Any:
        if kind in FILE_MODELS:
            model, parts = FILE_MODELS[kind]
            path = CORE.joinpath(*parts) / f"{item_id}.json"
        elif kind in PACKAGE_MODELS:
            model, folder = PACKAGE_MODELS[kind]
            path = CORE / "app" / "plugins" / folder / item_id / "manifest.json"
        else:
            raise UnknownCatalogId(item_id)
        if not path.is_file():
            raise UnknownCatalogId(item_id)
        return model.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def pin(self, kind: str, item_id: str) -> PinnedRef:
        self.get(kind, item_id)
        revision = hashlib.sha256(f"{kind}:{item_id}".encode()).hexdigest()
        return PinnedRef(id=item_id, revision=revision)

    def list(self, kind: str, *, video: Video | None = None) -> list[Any]:
        return []


def _base() -> dict[str, Any]:
    return json.loads(VIDEO_FIXTURE.read_text(encoding="utf-8"))


def make_video(
    *,
    script: dict[str, Any] | None | str = "llm",
    locks: dict[str, str] | None = None,
    origins: dict[str, str] | None = None,
    story_structure: str | None = None,
    language: str | None = None,
    topic: str | None = None,
    material: list[str] | None = None,
    register: str | None = None,
    extra_instructions: list[str] | None = None,
) -> Video:
    """Load the Korean fixture video and adjust the parts a test needs."""
    data = copy.deepcopy(_base())
    if script is None:
        data["script"] = None
    elif isinstance(script, dict):
        data["script"] = script
    if locks is not None:
        data["settings"]["locks"] = dict(locks)
    if origins is not None:
        data["settings"]["origins"] = dict(origins)
    if story_structure is not None:
        data["settings"]["format"]["story_structure"] = story_structure
    if register is not None:
        data["settings"]["format"]["register"] = register
    if language is not None:
        data["settings"]["language"] = language
    if topic is not None:
        data["topic"] = topic
    if material is not None:
        data["material"] = [{"id": MATERIAL_ID, "text": text} for text in material]
    if extra_instructions is not None:
        data["settings"]["extra_instructions"] = list(extra_instructions)
    return Video.model_validate(data)


def patch(path: str, value: Any, origin: Origin = Origin.llm) -> ValuePatch:
    return ValuePatch(path=path, value=value, origin=origin)


class Tiny(ContractModel):
    value: int


def _tiny_check(value: Tiny) -> None:
    if value.value < 1:
        raise ValueError("value must be at least 1")


def test_locked_value_is_not_patched() -> None:
    video = make_video(locks={"register": "locked"})
    outcome = build_ops(video, [patch("/settings/format/register", "casual")])
    assert outcome.ops == []
    assert outcome.skipped == [("/settings/format/register", SkipReason.locked)]


def test_user_value_is_not_overwritten_by_a_model_value() -> None:
    video = make_video(origins={"/format/register": "user"})
    outcome = build_ops(video, [patch("/settings/format/register", "casual")])
    assert outcome.ops == []
    assert outcome.skipped == [("/settings/format/register", SkipReason.lower_origin)]


def test_chat_value_replaces_a_user_value() -> None:
    video = make_video(origins={"/format/register": "user"})
    outcome = build_ops(
        video, [patch("/settings/format/register", "casual", Origin.user)]
    )
    assert [op.value for op in outcome.ops] == ["casual"]
    assert outcome.ops[0].origin is Origin.user


def test_value_outside_the_target_is_skipped() -> None:
    video = make_video()
    scene_id = video.scene_order[0]
    target = Target(scene_id=scene_id, pointer=None)
    outcome = build_ops(
        video, [patch("/settings/format/register", "casual")], target=target
    )
    assert outcome.ops == []
    assert outcome.skipped == [
        ("/settings/format/register", SkipReason.outside_target)
    ]


def test_higher_origin_wins_over_a_later_model_value() -> None:
    video = make_video()
    outcome = build_ops(
        video,
        [
            patch("/settings/format/register", "friendly", Origin.card),
            patch("/settings/format/register", "casual"),
        ],
    )
    assert [op.value for op in outcome.ops] == ["friendly"]
    assert outcome.ops[0].origin is Origin.card


def test_equal_origin_keeps_the_later_value() -> None:
    video = make_video()
    outcome = build_ops(
        video,
        [
            patch("/settings/format/humor", "none", Origin.user),
            patch("/settings/format/humor", "light", Origin.user),
        ],
    )
    assert [op.value for op in outcome.ops] == ["light"]


def _draft_data() -> dict[str, Any]:
    return {
        "message": "합성 요청",
        "language": "ko",
        "target_duration_s": 30,
        "card_id": None,
        "topic": "",
    }


def test_invalid_output_fails_after_one_repair() -> None:
    llm = RecordingLlm({"value": "no"}, {"value": "still no"})
    with pytest.raises(AppError) as caught:
        complete_json(
            llm,
            task=LlmTask.draft,
            route="draft",
            model=Tiny,
            data=_draft_data(),
            max_output_tokens=100,
            ctx=FakeContext(),
        )
    assert caught.value.code == "llm_invalid_output"
    assert len(llm.requests) == 2
    assert len(llm.requests[1].parts) == 2


def test_repair_accepts_a_valid_second_output() -> None:
    llm = RecordingLlm({"value": "no"}, {"value": 3})
    value = complete_json(
        llm,
        task=LlmTask.draft,
        route="draft",
        model=Tiny,
        data=_draft_data(),
        max_output_tokens=100,
        ctx=FakeContext(),
    )
    assert value.value == 3
    assert len(llm.requests) == 2


def test_business_check_runs_inside_the_repair() -> None:
    custom = RecordingLlm({"value": 0}, {"value": 2})
    value = complete_json(
        custom,
        task=LlmTask.draft,
        route="draft",
        model=Tiny,
        data=_draft_data(),
        max_output_tokens=100,
        ctx=FakeContext(),
        check=_tiny_check,
    )
    assert value.value == 2


def test_prompt_loader_rejects_undeclared_and_missing_variables() -> None:
    with pytest.raises(AppError):
        load_prompt("draft", {"message": "합성 요청"})
    data = _draft_data()
    data["extra"] = "not declared"
    with pytest.raises(AppError):
        load_prompt("draft", data)


def _fixtures(route: str) -> list[dict[str, Any]]:
    path = PROMPT_ROOT / route / "style-fixtures.jsonl"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_owned_routes_have_style_notes_and_review_inputs() -> None:
    for route in OWNED_ROUTES:
        fixtures = _fixtures(route)
        assert 2 <= len(fixtures) <= 5, route
        for fixture in fixtures:
            assert fixture["id"]
            system = load_prompt(route, fixture["data"])
            assert "# Style notes" in system
            assert "말투 예시" in system or "Tone example" in system
