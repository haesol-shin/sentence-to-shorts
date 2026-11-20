"""Draft route: one sentence fills stages, evidence sets the user origin."""

from __future__ import annotations

from typing import Any

import pytest
from test_patch import FakeContext, RecordingLlm, StubCatalog, make_video

from app.ports import AppError
from app.schemas.change import SetScriptOp
from app.schemas.common import Origin
from app.services.story.draft import draft

MESSAGE = "캐시를 책상 서랍에 비유해서 1분짜리로, 반말로, 차분하게 만들어 줘"
PLAIN_MESSAGE = "캐시를 책상 서랍에 비유해서 만들어 줘"

DRAFT: dict[str, Any] = {
    "card_id": "its_like",
    "topic": "캐시를 책상 서랍에 비유하기",
    "values": {
        "target_duration_s": 60,
        "register": "casual",
        "bgm_mood": "calm",
        "caption_mode": "phrase",
        "art_style": "pixel",
        "theme_id": "day",
    },
    "evidence": [
        {"field": "target_duration_s", "quote": "1분짜리"},
        {"field": "register", "quote": "반말로"},
        {"field": "bgm_mood", "quote": "차분하게"},
    ],
}
PLAIN_DRAFT: dict[str, Any] = {
    "card_id": "its_like",
    "topic": "캐시를 책상 서랍에 비유하기",
    "values": {"register": "neutral", "caption_position": "top"},
    "evidence": [{"field": "caption_position", "quote": "위로"}],
}

ANALOGY_SCRIPT: dict[str, Any] = {
    "title": "캐시는 책상 서랍",
    "beats": [
        {
            "beat_id": "familiar",
            "lines": [
                {
                    "display_text": "캐시를 책상 서랍이라고 생각해 보세요.",
                    "speech_text": "캐시를 책상 서랍이라고 생각해 보세요.",
                    "highlight": ["서랍"],
                }
            ],
        },
        {
            "beat_id": "mapping",
            "lines": [
                {
                    "display_text": "자주 쓰는 것을 서랍에 두죠.",
                    "speech_text": "자주 쓰는 것을 서랍에 두죠.",
                    "highlight": ["자주"],
                }
            ],
        },
        {
            "beat_id": "concept",
            "lines": [
                {
                    "display_text": "캐시도 자주 쓰는 데이터를 가까이 둬요.",
                    "speech_text": "캐시도 자주 쓰는 데이터를 가까이 둬요.",
                    "highlight": ["데이터"],
                }
            ],
        },
        {
            "beat_id": "reality",
            "lines": [
                {
                    "display_text": "서랍이 가득 차면 비워야 하듯 캐시도 지워요.",
                    "speech_text": "서랍이 가득 차면 비워야 하듯 캐시도 지워요.",
                    "highlight": ["비워야"],
                }
            ],
        },
    ],
}
ANALOGY_SPLIT: dict[str, Any] = {
    "scenes": [
        {"beat_id": "familiar", "beat_label": "서랍", "line_indices": [0]},
        {"beat_id": "mapping", "beat_label": "자주 쓰는 것", "line_indices": [1]},
        {"beat_id": "concept", "beat_label": "데이터", "line_indices": [2]},
        {"beat_id": "reality", "beat_label": "비우기", "line_indices": [3]},
    ]
}


def _draft(
    video: Any, message: str, card_id: str | None, *responses: dict[str, Any] | Exception
) -> tuple[list[Any], RecordingLlm]:
    llm = RecordingLlm(*responses)
    ops = draft(
        video, message, card_id, llm=llm, catalog=StubCatalog(), ctx=FakeContext()
    )
    return ops, llm


def _set_values(ops: list[Any]) -> dict[str, Any]:
    return {op.path: op.value for op in ops if op.op == "set"}


def _origins(ops: list[Any]) -> dict[str, Origin]:
    return {op.path: op.origin for op in ops if op.op == "set"}


def test_criterion_1_one_message_fills_every_stage() -> None:
    video = make_video(script=None, origins={})
    ops, _ = _draft(video, MESSAGE, None, DRAFT, ANALOGY_SCRIPT, ANALOGY_SPLIT)
    values = _set_values(ops)
    assert values["/topic"] == "캐시를 책상 서랍에 비유하기"
    assert values["/settings/format/card_id"] == "its_like"
    assert values["/settings/format/story_structure"] == "single_analogy"
    assert values["/settings/format/layout"]["id"] == "full_stage"
    assert values["/settings/format/character_role"] == "subject"
    assert values["/settings/format/humor"] == "light"
    assert values["/settings/format/progress_mode"] == "phases"
    assert values["/settings/format/scene_count"] == 8
    assert values["/settings/format/register"] == "casual"
    assert values["/settings/audio/bgm/mood"] == "calm"
    assert values["/settings/caption/mode"] == "phrase"
    assert values["/settings/visual/art_style"]["id"] == "pixel"
    assert values["/settings/visual/theme_id"] == "day"
    assert values["/settings/target_duration_s"] == 60
    script_op = next(op for op in ops if isinstance(op, SetScriptOp))
    assert [scene.beat_id for scene in script_op.scenes] == [
        "familiar",
        "mapping",
        "concept",
        "reality",
    ]


def test_criterion_1_evidence_list_sets_the_user_origin() -> None:
    video = make_video(script=_existing_script(), origins={})
    ops, _ = _draft(video, MESSAGE, None, DRAFT)
    origins = _origins(ops)
    values = _set_values(ops)
    assert origins["/settings/format/register"] is Origin.user
    assert origins["/settings/audio/bgm/mood"] is Origin.user
    assert origins["/settings/target_duration_s"] is Origin.user
    assert values["/settings/format/register"] == "casual"
    assert values["/settings/audio/bgm/mood"] == "calm"
    assert values["/settings/target_duration_s"] == 60


def test_criterion_1_card_value_beats_an_unquoted_model_value() -> None:
    video = make_video(script=_existing_script(), origins={})
    ops, _ = _draft(video, PLAIN_MESSAGE, None, PLAIN_DRAFT)
    values = _set_values(ops)
    origins = _origins(ops)
    assert values["/settings/format/register"] == "friendly"
    assert origins["/settings/format/register"] is Origin.card
    assert values["/settings/caption/position"] == "top"
    assert origins["/settings/caption/position"] is Origin.llm


def test_recommended_card_is_chosen_when_the_request_names_none() -> None:
    video = make_video(script=_existing_script(), origins={})
    ops, _ = _draft(video, PLAIN_MESSAGE, None, PLAIN_DRAFT)
    values = _set_values(ops)
    origins = _origins(ops)
    assert values["/settings/format/card_id"] == "its_like"
    assert origins["/settings/format/card_id"] is Origin.llm


def test_requested_card_keeps_the_user_origin() -> None:
    video = make_video(script=_existing_script(), origins={})
    ops, _ = _draft(video, PLAIN_MESSAGE, "its_like", PLAIN_DRAFT)
    origins = _origins(ops)
    assert origins["/settings/format/card_id"] is Origin.user


def test_criterion_19_chat_value_survives_a_card_change() -> None:
    video = make_video(script=_existing_script(), origins={"/format/register": "user"})
    ops, _ = _draft(video, PLAIN_MESSAGE, None, PLAIN_DRAFT)
    assert "/settings/format/register" not in _set_values(ops)


def test_locked_card_value_is_not_patched() -> None:
    video = make_video(script=_existing_script(), origins={}, locks={"story_structure": "locked"})
    ops, _ = _draft(video, MESSAGE, None, DRAFT)
    assert "/settings/format/story_structure" not in _set_values(ops)


def test_existing_script_is_not_rewritten() -> None:
    video = make_video(script=_existing_script(), origins={})
    ops, llm = _draft(video, MESSAGE, None, DRAFT)
    assert len(llm.requests) == 1
    assert not any(isinstance(op, SetScriptOp) for op in ops)


def test_user_script_is_not_rewritten_by_the_draft() -> None:
    script = {"source": "user", "raw_text": "첫 문장이다. 둘째 문장이다.", "title": "합성"}
    video = make_video(script=script, origins={})
    ops, llm = _draft(video, MESSAGE, None, DRAFT)
    assert len(llm.requests) == 1
    assert not any(isinstance(op, SetScriptOp) for op in ops)


def test_unknown_recommended_card_fails_after_one_repair() -> None:
    bad = {**DRAFT, "card_id": "not_a_card"}
    video = make_video(script=_existing_script(), origins={})
    with pytest.raises(AppError) as caught:
        _draft(video, MESSAGE, None, bad, bad)
    assert caught.value.code == "llm_invalid_output"


def test_unregistered_story_structure_fails_after_one_repair() -> None:
    bad = {**PLAIN_DRAFT, "values": {"story_structure": "not_a_structure"}}
    video = make_video(script=_existing_script(), origins={})
    with pytest.raises(AppError) as caught:
        _draft(video, PLAIN_MESSAGE, None, bad, bad)
    assert caught.value.code == "llm_invalid_output"


def _existing_script() -> dict[str, Any]:
    return {"source": "llm", "raw_text": "기존 대본", "title": "기존"}
