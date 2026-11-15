"""Script routes: structure flows, material, verbatim user scripts, split order."""

from __future__ import annotations

import re
from typing import Any

import pytest
from test_patch import FakeContext, RecordingLlm, StubCatalog, make_video

from app.ports import AppError, LlmTask
from app.schemas.change import SetScriptOp
from app.schemas.common import TYPEID_PATTERN
from app.schemas.script import ScriptSource
from app.services.story.script import write_script

NUMBERED_SCRIPT: dict[str, Any] = {
    "title": "커피 세 가지 기준",
    "beats": [
        {
            "beat_id": "hook",
            "lines": [
                {
                    "display_text": "커피는 세 가지만 보면 돼요.",
                    "speech_text": "커피는 세 가지만 보면 돼요.",
                    "highlight": ["세 가지"],
                }
            ],
        },
        {
            "beat_id": "first",
            "lines": [
                {
                    "display_text": "첫째, 원두의 신선도를 봐요.",
                    "speech_text": "첫째, 원두의 신선도를 봐요.",
                    "highlight": ["원두"],
                }
            ],
        },
        {
            "beat_id": "second",
            "lines": [
                {
                    "display_text": "둘째, 물의 온도를 지켜요.",
                    "speech_text": "둘째, 물의 온도를 지켜요.",
                    "highlight": ["온도"],
                }
            ],
        },
        {
            "beat_id": "third",
            "lines": [
                {
                    "display_text": "셋째, 비율을 맞춰요.",
                    "speech_text": "셋째, 비율을 맞춰요.",
                    "highlight": ["비율"],
                }
            ],
        },
        {
            "beat_id": "recap",
            "lines": [
                {
                    "display_text": "이 세 가지만 지키면 충분해요.",
                    "speech_text": "이 세 가지만 지키면 충분해요.",
                    "highlight": ["충분해요"],
                }
            ],
        },
    ],
}
NUMBERED_SPLIT: dict[str, Any] = {
    "scenes": [
        {"beat_id": "hook", "beat_label": "훅", "line_indices": [0]},
        {"beat_id": "first", "beat_label": "첫 번째", "line_indices": [1]},
        {"beat_id": "second", "beat_label": "두 번째", "line_indices": [2]},
        {"beat_id": "third", "beat_label": "세 번째", "line_indices": [3]},
        {"beat_id": "recap", "beat_label": "한 줄 요약", "line_indices": [4]},
    ]
}
ANALOGY_SCRIPT: dict[str, Any] = {
    "title": "캐시는 서랍",
    "beats": [
        {
            "beat_id": "familiar",
            "lines": [
                {
                    "display_text": "캐시를 서랍이라고 해요.",
                    "speech_text": "캐시를 서랍이라고 해요.",
                    "highlight": ["서랍"],
                }
            ],
        },
        {
            "beat_id": "mapping",
            "lines": [
                {
                    "display_text": "자주 쓰는 것을 서랍에 둬요.",
                    "speech_text": "자주 쓰는 것을 서랍에 둬요.",
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
                    "display_text": "서랍과 캐시는 같지 않아요.",
                    "speech_text": "서랍과 캐시는 같지 않아요.",
                    "highlight": ["같지"],
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
        {"beat_id": "reality", "beat_label": "현실", "line_indices": [3]},
    ]
}
HYPOTHETICAL_SCRIPT: dict[str, Any] = {
    "title": "만약 메뉴 이름이 없다면",
    "beats": [
        {
            "beat_id": "question",
            "lines": [
                {
                    "display_text": "만약 메뉴 이름이 없다면 어떨까요?",
                    "speech_text": "만약 메뉴 이름이 없다면 어떨까요?",
                    "highlight": ["메뉴"],
                }
            ],
        },
        {
            "beat_id": "first_result",
            "lines": [
                {
                    "display_text": "손님이 재료를 하나씩 설명해요.",
                    "speech_text": "손님이 재료를 하나씩 설명해요.",
                    "highlight": ["재료"],
                }
            ],
        },
        {
            "beat_id": "second_result",
            "lines": [
                {
                    "display_text": "주문이 길어지고 헷갈려요.",
                    "speech_text": "주문이 길어지고 헷갈려요.",
                    "highlight": ["주문"],
                }
            ],
        },
        {
            "beat_id": "third_result",
            "lines": [
                {
                    "display_text": "같은 음료를 다시 설명해요.",
                    "speech_text": "같은 음료를 다시 설명해요.",
                    "highlight": ["다시"],
                }
            ],
        },
        {
            "beat_id": "reality",
            "lines": [
                {
                    "display_text": "현실의 메뉴 이름은 주문을 짧게 해요.",
                    "speech_text": "현실의 메뉴 이름은 주문을 짧게 해요.",
                    "highlight": ["주문"],
                }
            ],
        },
    ],
}
HYPOTHETICAL_SPLIT: dict[str, Any] = {
    "scenes": [
        {"beat_id": "question", "beat_label": "만약 질문", "line_indices": [0]},
        {"beat_id": "first_result", "beat_label": "결과 1", "line_indices": [1]},
        {"beat_id": "second_result", "beat_label": "결과 2", "line_indices": [2]},
        {"beat_id": "third_result", "beat_label": "결과 3", "line_indices": [3]},
        {"beat_id": "reality", "beat_label": "현실", "line_indices": [4]},
    ]
}
RAW_USER_SCRIPT = "첫 문장이다. 둘째 문장이다. 셋째 문장이다."
USER_SPLIT: dict[str, Any] = {
    "scenes": [
        {"beat_id": "hook", "beat_label": "훅", "line_indices": [0]},
        {"beat_id": "first", "beat_label": "첫 번째", "line_indices": [1]},
        {"beat_id": "second", "beat_label": "두 번째", "line_indices": [2]},
    ]
}
CASES = {
    "numbered_three": (NUMBERED_SCRIPT, NUMBERED_SPLIT),
    "single_analogy": (ANALOGY_SCRIPT, ANALOGY_SPLIT),
    "hypothetical": (HYPOTHETICAL_SCRIPT, HYPOTHETICAL_SPLIT),
}


def _run(
    video: Any, *responses: dict[str, Any] | Exception
) -> tuple[SetScriptOp, RecordingLlm]:
    llm = RecordingLlm(*responses)
    ops = write_script(video, llm=llm, catalog=StubCatalog(), ctx=FakeContext())
    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, SetScriptOp)
    return op, llm


def test_criterion_3_story_structures_have_different_beat_orders() -> None:
    orders: list[tuple[str, ...]] = []
    for structure, (script, split) in CASES.items():
        video = make_video(story_structure=structure, script=None, origins={})
        op, _ = _run(video, script, split)
        orders.append(tuple(scene.beat_id for scene in op.scenes))
    assert len(set(orders)) == 3
    assert orders[0] == ("hook", "first", "second", "third", "recap")
    assert orders[1] == ("familiar", "mapping", "concept", "reality")
    assert orders[2] == (
        "question",
        "first_result",
        "second_result",
        "third_result",
        "reality",
    )


def test_criterion_3_script_routes_read_different_prompts() -> None:
    numbered, numbered_llm = _run(
        make_video(story_structure="numbered_three", script=None, origins={}),
        NUMBERED_SCRIPT,
        NUMBERED_SPLIT,
    )
    analogy, analogy_llm = _run(
        make_video(story_structure="single_analogy", script=None, origins={}),
        ANALOGY_SCRIPT,
        ANALOGY_SPLIT,
    )
    assert numbered.scenes[0].beat_id == "hook"
    assert analogy.scenes[0].beat_id == "familiar"
    assert numbered_llm.requests[0].route == "script.numbered_three"
    assert analogy_llm.requests[0].route == "script.default"
    assert numbered_llm.requests[0].system != analogy_llm.requests[0].system
    assert "# Style notes" in numbered_llm.requests[0].system
    assert "# Style notes" in analogy_llm.requests[0].system


def test_criterion_18_material_keywords_enter_the_script() -> None:
    video = make_video(
        story_structure="numbered_three",
        script=None,
        origins={},
        material=["원두는 신선도가 중요하다."],
    )
    op, llm = _run(video, NUMBERED_SCRIPT, NUMBERED_SPLIT)
    assert "원두는 신선도가 중요하다." in llm.requests[0].parts[0].text
    texts = [line.display_text for scene in op.scenes for line in scene.lines]
    assert any("원두" in text for text in texts)


def test_criterion_18_user_script_sentences_stay_verbatim() -> None:
    script = {"source": "user", "raw_text": RAW_USER_SCRIPT, "title": "합성 대본"}
    video = make_video(script=script)
    op, llm = _run(video, USER_SPLIT)
    assert [request.task for request in llm.requests] == [LlmTask.split]
    texts = [line.display_text for scene in op.scenes for line in scene.lines]
    assert texts == ["첫 문장이다.", "둘째 문장이다.", "셋째 문장이다."]
    assert op.script.source is ScriptSource.user
    assert op.script.raw_text == RAW_USER_SCRIPT


def test_generated_script_op_carries_the_title_and_joined_lines() -> None:
    video = make_video(story_structure="numbered_three", script=None, origins={})
    op, _ = _run(video, NUMBERED_SCRIPT, NUMBERED_SPLIT)
    assert op.script.source is ScriptSource.llm
    assert op.script.title == NUMBERED_SCRIPT["title"]
    assert op.script.raw_text is not None
    assert op.script.raw_text.split("\n")[0] == "커피는 세 가지만 보면 돼요."


def test_scene_and_line_ids_are_app_typeids() -> None:
    video = make_video(story_structure="numbered_three", script=None, origins={})
    op, _ = _run(video, NUMBERED_SCRIPT, NUMBERED_SPLIT)
    ids = [scene.id for scene in op.scenes]
    ids.extend(line.id for scene in op.scenes for line in scene.lines)
    assert all(re.fullmatch(TYPEID_PATTERN, value) for value in ids)
    assert len(set(ids)) == len(ids)


def test_highlight_spans_match_the_words() -> None:
    video = make_video(story_structure="numbered_three", script=None, origins={})
    op, _ = _run(video, NUMBERED_SCRIPT, NUMBERED_SPLIT)
    line = op.scenes[0].lines[0]
    assert len(line.highlight) == 1
    span = line.highlight[0]
    assert line.display_text[span.start : span.end] == "세 가지"


def test_split_must_keep_line_order() -> None:
    bad_split = {
        "scenes": [
            {"beat_id": "first", "beat_label": "첫 번째", "line_indices": [1]},
            {"beat_id": "hook", "beat_label": "훅", "line_indices": [0]},
            {"beat_id": "second", "beat_label": "두 번째", "line_indices": [2]},
            {"beat_id": "third", "beat_label": "세 번째", "line_indices": [3]},
            {"beat_id": "recap", "beat_label": "한 줄 요약", "line_indices": [4]},
        ]
    }
    video = make_video(story_structure="numbered_three", script=None, origins={})
    with pytest.raises(AppError) as caught:
        _run(video, NUMBERED_SCRIPT, bad_split, bad_split)
    assert caught.value.code == "llm_invalid_output"


def test_script_must_cover_every_structure_beat() -> None:
    missing_recap = {
        "title": "커피 세 가지 기준",
        "beats": NUMBERED_SCRIPT["beats"][:4],
    }
    video = make_video(story_structure="numbered_three", script=None, origins={})
    with pytest.raises(AppError) as caught:
        _run(video, missing_recap, missing_recap)
    assert caught.value.code == "llm_invalid_output"


def test_split_must_keep_the_original_beat() -> None:
    hook_only = {
        "scenes": [
            {"beat_id": "hook", "beat_label": "훅", "line_indices": [index]}
            for index in range(5)
        ]
    }
    video = make_video(story_structure="numbered_three", script=None, origins={})
    with pytest.raises(AppError) as caught:
        _run(video, NUMBERED_SCRIPT, hook_only, hook_only)
    assert caught.value.code == "llm_invalid_output"


def test_split_request_carries_each_line_beat() -> None:
    video = make_video(story_structure="numbered_three", script=None, origins={})
    llm = RecordingLlm(NUMBERED_SCRIPT, NUMBERED_SPLIT)
    write_script(video, llm=llm, catalog=StubCatalog(), ctx=FakeContext())
    split_request = llm.requests[1]
    assert '"beat_id": "first"' in split_request.parts[0].text
