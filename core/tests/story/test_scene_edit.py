"""A scene rewrite touches one scene and warns about stale neighbor wording."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.jobs import CancelFlag, LocalJobContext
from app.plugins.registry import Registry
from app.ports import AppError, LlmRequest, LlmResult
from app.schemas.change import WarningCode
from app.schemas.job import Stage, Usage
from app.schemas.scene import Element, Scene, SceneVisual, SfxCue
from app.schemas.script import Line, Span
from app.schemas.video import Video
from app.services.story.scene_edit import plan_scene_rewrite, stale_wording_warnings

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "contracts" / "valid" / "video_ko_draft_no_visual.json"
SECOND_LINE_ID = "l_079jmk94bf8vj82ct90jqj44km"
ELEMENT_ID = "e_0gv16xq3n089nbs6wykgccs0zf"
_CROCKFORD32 = "0123456789abcdefghjkmnpqrstvwxyz"


class ScriptedLlm:
    """Replays recorded responses in order and keeps every request."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.requests: list[LlmRequest] = []

    def complete(
        self, req: LlmRequest, *, owner_id: str, cancel: Any, deadline: float
    ) -> LlmResult:
        self.requests.append(req)
        payload = self.responses.pop(0)
        return LlmResult(
            text=json.dumps(payload, ensure_ascii=False),
            parsed=payload,
            usage=Usage(
                stage=Stage.llm_chat,
                provider="scripted",
                model="scripted",
                effort=None,
                input_tokens=None,
                output_tokens=None,
                cache_read_tokens=None,
                cost_usd=None,
                wall_ms=0,
                retries=0,
            ),
        )

    def auth_state(self, owner_id: str) -> str:
        return "ok"


@pytest.fixture
def ctx(tmp_path: Path) -> LocalJobContext:
    return LocalJobContext(
        cancel_token=CancelFlag(), deadline=time.monotonic() + 60, job_dir=tmp_path
    )


def _video() -> Video:
    video = Video.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    order = list(video.scene_order)
    scenes = dict(video.scenes)
    scenes[order[0]] = _scene_with_lines(
        scenes[order[0]], [(scenes[order[0]].lines[0].id, "요리는 재료가 중요해요.")]
    )
    scenes[order[1]] = _scene_with_lines(
        scenes[order[1]], [(scenes[order[1]].lines[0].id, "비유를 요리에서 게임으로 바꿔요.")]
    )
    scenes[order[2]] = _scene_with_lines(
        scenes[order[2]], [(scenes[order[2]].lines[0].id, "게임은 규칙을 먼저 봐요.")]
    )
    return video.model_copy(update={"scenes": scenes})


def _scene_with_lines(scene: Scene, entries: list[tuple[str, str]]) -> Scene:
    lines = [
        scene.lines[0].model_copy(
            update={"id": line_id, "display_text": text, "speech_text": text}
        )
        for line_id, text in entries
    ]
    return scene.model_copy(update={"lines": lines})


def _video_with_visual() -> Video:
    """Target scene has two lines plus an element and a cue on the second line."""
    video = _video()
    target = video.scene_order[1]
    scene = video.scenes[target]
    first_id = scene.lines[0].id
    scene = _scene_with_lines(
        scene,
        [(first_id, "게임은 규칙을 먼저 봐요."), (SECOND_LINE_ID, "게임은 순서를 지켜요.")],
    )
    scene = scene.model_copy(
        update={
            "visual": SceneVisual(
                background_id="bg_village",
                characters=[],
                elements=[
                    Element(
                        id=ELEMENT_ID,
                        kind="label",
                        value="순서",
                        anchor="top",
                        reveal_line_id=SECOND_LINE_ID,
                    )
                ],
                sfx=[
                    SfxCue(
                        sfx_id=Registry().pin("sfx", "pop"),
                        line_id=SECOND_LINE_ID,
                        at="start",
                        offset_ms=0,
                    )
                ],
                transition_in="cut",
            )
        }
    )
    return video.model_copy(update={"scenes": {**video.scenes, target: scene}})


def _response(scene_id: str, *texts: str) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "lines": [
            {"display_text": text, "speech_text": text, "speaker": "narrator"}
            for text in texts
        ],
    }


def _uuid_of(value: str) -> uuid.UUID:
    _prefix, _, body = value.partition("_")
    number = 0
    for char in body:
        number = (number << 5) | _CROCKFORD32.index(char)
    return uuid.UUID(int=number)


def test_19_scene_rewrite_returns_only_the_target_scene_lines(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    target = video.scene_order[1]
    llm = ScriptedLlm(_response(target, "게임으로 바꿔요."))

    result = plan_scene_rewrite(video, target, "더 짧게", llm=llm, ctx=ctx)

    assert result.scene_id == target
    assert len(result.ops) == 1
    op = result.ops[0]
    assert op.op == "set"
    assert op.path == f"/scenes/{target}/lines"
    assert [line["display_text"] for line in op.value] == ["게임으로 바꿔요."]


def test_19_scene_rewrite_keeps_scene_id_and_order(ctx: LocalJobContext) -> None:
    video = _video()
    order = list(video.scene_order)
    target = order[1]
    llm = ScriptedLlm(_response(target, "게임으로 바꿔요."))

    result = plan_scene_rewrite(video, target, "", llm=llm, ctx=ctx)

    assert list(video.scene_order) == order
    assert {op.op for op in result.ops} == {"set"}
    dumped = json.dumps([op.model_dump(mode="json") for op in result.ops])
    for other in set(order) - {target}:
        assert other not in dumped
    assert result.ops[0].path == f"/scenes/{target}/lines"


def test_19_scene_rewrite_keeps_unchanged_line_ids_and_drops_stale_references(
    ctx: LocalJobContext,
) -> None:
    video = _video_with_visual()
    target = video.scene_order[1]
    kept_id = video.scenes[target].lines[0].id
    llm = ScriptedLlm(_response(target, video.scenes[target].lines[0].display_text))

    result = plan_scene_rewrite(video, target, "짧게", llm=llm, ctx=ctx)

    lines_op, visual_op = result.ops
    assert [line["id"] for line in lines_op.value] == [kept_id]
    visual = SceneVisual.model_validate(visual_op.value)
    assert visual.elements[0].reveal_line_id is None
    assert visual.sfx == []


def test_19_scene_rewrite_keeps_references_when_an_earlier_line_is_removed(
    ctx: LocalJobContext,
) -> None:
    video = _video_with_visual()
    target = video.scene_order[1]
    scene = video.scenes[target]
    llm = ScriptedLlm(_response(target, scene.lines[1].display_text))

    result = plan_scene_rewrite(video, target, "앞 대사만 빼 줘", llm=llm, ctx=ctx)

    assert len(result.ops) == 1
    new_lines = [Line.model_validate(item) for item in result.ops[0].value]
    assert [line.id for line in new_lines] == [SECOND_LINE_ID]
    kept_ids = {line.id for line in new_lines}
    assert scene.visual is not None
    assert all(
        element.reveal_line_id in kept_ids for element in scene.visual.elements
    )
    assert all(cue.line_id in kept_ids for cue in scene.visual.sfx)


def test_19_scene_rewrite_keeps_highlight_spans_of_unchanged_lines(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    target = video.scene_order[1]
    scene = video.scenes[target]
    line = scene.lines[0].model_copy(update={"highlight": [Span(start=0, end=2)]})
    scene = scene.model_copy(update={"lines": [line]})
    video = video.model_copy(update={"scenes": {**video.scenes, target: scene}})
    llm = ScriptedLlm(_response(target, line.display_text))

    result = plan_scene_rewrite(video, target, "그대로", llm=llm, ctx=ctx)

    assert result.ops[0].value[0]["highlight"] == [{"start": 0, "end": 2}]


def test_19_scene_rewrite_keeps_highlights_when_only_the_speech_text_changes(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    target = video.scene_order[1]
    scene = video.scenes[target]
    line = scene.lines[0].model_copy(
        update={
            "highlight": [Span(start=0, end=2)],
            "speech_text": "비유를 게임으로 바꿔요.",
        }
    )
    scene = scene.model_copy(update={"lines": [line]})
    video = video.model_copy(update={"scenes": {**video.scenes, target: scene}})
    llm = ScriptedLlm(
        {
            "scene_id": target,
            "lines": [
                {
                    "display_text": line.display_text,
                    "speech_text": "게임으로 바꿔요.",
                    "speaker": "narrator",
                }
            ],
        }
    )

    result = plan_scene_rewrite(video, target, "읽는 글만 다듬어 줘", llm=llm, ctx=ctx)

    rewritten = result.ops[0].value[0]
    assert rewritten["id"] != line.id
    assert rewritten["highlight"] == [{"start": 0, "end": 2}]


def test_19_scene_rewrite_repoints_references_to_the_new_line_at_the_same_position(
    ctx: LocalJobContext,
) -> None:
    video = _video_with_visual()
    target = video.scene_order[1]
    llm = ScriptedLlm(_response(target, "게임은 규칙부터 봐요.", "게임은 순서대로 해요."))

    result = plan_scene_rewrite(video, target, "다시 써 줘", llm=llm, ctx=ctx)

    lines_op, visual_op = result.ops
    new_ids = [line["id"] for line in lines_op.value]
    assert new_ids[0] != video.scenes[target].lines[0].id
    visual = SceneVisual.model_validate(visual_op.value)
    assert visual.elements[0].reveal_line_id == new_ids[1]
    assert [cue.line_id for cue in visual.sfx] == [new_ids[1]]
    for line_id in [visual.elements[0].reveal_line_id, *new_ids]:
        assert _uuid_of(line_id).version == 7
        assert _uuid_of(line_id).variant == uuid.RFC_4122


def test_19_scene_rewrite_repairs_once_when_the_response_targets_another_scene(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    target = video.scene_order[1]
    llm = ScriptedLlm(
        _response(video.scene_order[0], "게임으로 바꿔요."),
        _response(target, "게임으로 바꿔요."),
    )

    result = plan_scene_rewrite(video, target, "", llm=llm, ctx=ctx)

    assert len(llm.requests) == 2
    assert json.loads(llm.requests[1].parts[-1].text)["repair"]["problems"]
    assert result.ops[0].path == f"/scenes/{target}/lines"


def test_19_scene_rewrite_fails_with_llm_invalid_output_after_one_repair(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    target = video.scene_order[1]
    other = video.scene_order[0]
    llm = ScriptedLlm(
        _response(other, "게임으로 바꿔요."), _response(other, "게임으로 바꿔요.")
    )

    with pytest.raises(AppError) as raised:
        plan_scene_rewrite(video, target, "", llm=llm, ctx=ctx)

    assert raised.value.code == "llm_invalid_output"
    assert len(llm.requests) == 2


def test_26_scene_rewrite_warns_about_stale_wording_in_neighbors(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    target = video.scene_order[1]
    llm = ScriptedLlm(_response(target, "게임으로 바꿔요."))

    result = plan_scene_rewrite(video, target, "비유를 게임으로", llm=llm, ctx=ctx)

    assert [warning.code for warning in result.warnings] == [
        WarningCode.stale_wording_in_neighbor
    ]
    assert [warning.scene_id for warning in result.warnings] == [video.scene_order[0]]
    assert len(result.ops) == 1


def test_26_scene_rewrite_keeps_rewritten_wording_out_of_neighbors(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    target = video.scene_order[1]
    llm = ScriptedLlm(_response(target, "비유를 요리에서 게임으로 바꿔요."))

    result = plan_scene_rewrite(video, target, "그대로", llm=llm, ctx=ctx)

    assert result.warnings == []
    assert stale_wording_warnings(video, result.ops) == []
