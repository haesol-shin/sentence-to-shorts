"""Chat interpretation: values as user input, notes, refusals and the target."""

from __future__ import annotations

from typing import Any

import pytest
from test_patch import FakeContext, RecordingLlm, StubCatalog, make_video

from app.ports import AppError, Proposal
from app.schemas.change import Target
from app.schemas.common import Origin
from app.services.story.interpret import EMPTY_MESSAGE, interpret

MESSAGE = "반말로, 자막은 구절형으로, BGM은 차분하게 바꿔 줘"
CHAT_MULTI: dict[str, Any] = {
    "values": {
        "register": "casual",
        "caption_mode": "phrase",
        "bgm_mood": "calm",
        "art_style": "pixel",
    },
    "extra_instructions": ["비유는 게임으로"],
    "notes": ["말투와 자막을 바꿨어요."],
}
WHOLE = Target(scene_id=None, pointer=None)


def _interpret(
    video: Any,
    text: str,
    target: Target,
    *responses: dict[str, Any] | Exception,
) -> tuple[Proposal, RecordingLlm]:
    llm = RecordingLlm(*responses)
    proposal = interpret(
        video, text, target, llm=llm, catalog=StubCatalog(), ctx=FakeContext()
    )
    return proposal, llm


def test_criterion_1_chat_changes_values_in_several_stages() -> None:
    video = make_video()
    proposal, _ = _interpret(video, MESSAGE, WHOLE, CHAT_MULTI)
    values = {op.path: op.value for op in proposal.ops}
    assert values["/settings/format/register"] == "casual"
    assert values["/settings/caption/mode"] == "phrase"
    assert values["/settings/audio/bgm/mood"] == "calm"
    assert values["/settings/visual/art_style"]["id"] == "pixel"
    assert values["/settings/extra_instructions"] == ["비유는 게임으로"]
    assert all(op.origin is Origin.user for op in proposal.ops)
    assert proposal.notes == ["말투와 자막을 바꿨어요."]


def test_short_reply_becomes_a_note_without_ops() -> None:
    video = make_video()
    proposal, _ = _interpret(
        video, "그대로 둬", WHOLE, {"values": {}, "notes": ["지금 값으로 둘게요."]}
    )
    assert proposal.ops == []
    assert proposal.notes == ["지금 값으로 둘게요."]


def test_ambiguous_request_returns_one_question_note() -> None:
    video = make_video()
    proposal, _ = _interpret(
        video,
        "좀 더 차분하게",
        WHOLE,
        {"values": {"bgm_mood": "calm"}, "question": "어느 쪽을 바꿀까요?"},
    )
    assert proposal.ops == []
    assert proposal.notes == ["어느 쪽을 바꿀까요?"]


def test_unsupported_request_is_reported() -> None:
    video = make_video()
    proposal, _ = _interpret(
        video,
        "3번 장면을 다시 써 줘",
        WHOLE,
        {"values": {}, "unsupported": ["장면 다시 쓰기에서 처리해요."]},
    )
    assert proposal.unsupported == ["장면 다시 쓰기에서 처리해요."]


def test_locked_value_is_not_changed_by_chat() -> None:
    video = make_video(locks={"register": "locked"})
    proposal, _ = _interpret(
        video, "반말로 바꿔 줘", WHOLE, {"values": {"register": "casual"}}
    )
    assert proposal.ops == []
    assert "/settings/format/register: locked" in proposal.unsupported


def test_target_pointer_limits_changes() -> None:
    video = make_video()
    target = Target(scene_id=None, pointer="/settings/format")
    proposal, _ = _interpret(
        video,
        "반말로, BGM은 차분하게",
        target,
        {"values": {"register": "casual", "bgm_mood": "calm"}},
    )
    assert [op.path for op in proposal.ops] == ["/settings/format/register"]
    assert any("outside_target" in item for item in proposal.unsupported)


def test_scene_target_keeps_settings_unchanged() -> None:
    video = make_video()
    target = Target(scene_id=video.scene_order[0], pointer=None)
    proposal, _ = _interpret(
        video, "반말로 바꿔 줘", target, {"values": {"register": "casual"}}
    )
    assert proposal.ops == []
    assert any("outside_target" in item for item in proposal.unsupported)


def test_extra_instructions_append_up_to_the_cap() -> None:
    existing = [f"메모 {index}" for index in range(19)]
    video = make_video(extra_instructions=existing)
    proposal, _ = _interpret(
        video,
        "비유는 게임으로, 농담은 한 번만",
        WHOLE,
        {"extra_instructions": ["새 메모 하나", "새 메모 둘"]},
    )
    values = {op.path: op.value for op in proposal.ops}
    merged = values["/settings/extra_instructions"]
    assert len(merged) == 20
    assert merged[19] == "새 메모 하나"
    assert any(
        "새 메모 둘" in item and "not saved" in item for item in proposal.unsupported
    )
    assert proposal.ops[0].origin is Origin.user


def test_empty_text_asks_for_an_instruction_without_a_call() -> None:
    video = make_video()
    proposal, llm = _interpret(video, "   ", WHOLE)
    assert proposal.ops == []
    assert proposal.notes == [EMPTY_MESSAGE[video.settings.language]]
    assert llm.requests == []


def test_unknown_style_id_fails_after_one_repair() -> None:
    video = make_video()
    bad = {"values": {"art_style": "not_a_style"}}
    with pytest.raises(AppError) as caught:
        _interpret(video, "화면 스타일 바꿔 줘", WHOLE, bad, bad)
    assert caught.value.code == "llm_invalid_output"


def test_theme_outside_the_style_fails_after_one_repair() -> None:
    video = make_video()
    bad = {"values": {"theme_id": "night"}}
    with pytest.raises(AppError) as caught:
        _interpret(video, "밤 테마로 바꿔 줘", WHOLE, bad, bad)
    assert caught.value.code == "llm_invalid_output"


def test_registered_story_structure_stays_a_string() -> None:
    video = make_video()
    proposal, _ = _interpret(
        video, "비유 흐름으로 바꿔 줘", WHOLE, {"values": {"story_structure": "single_analogy"}}
    )
    values = {op.path: op.value for op in proposal.ops}
    assert values["/settings/format/story_structure"] == "single_analogy"


def test_unregistered_story_structure_fails_after_one_repair() -> None:
    video = make_video()
    bad = {"values": {"story_structure": "not_a_structure"}}
    with pytest.raises(AppError) as caught:
        _interpret(video, "다른 흐름으로 바꿔 줘", WHOLE, bad, bad)
    assert caught.value.code == "llm_invalid_output"
