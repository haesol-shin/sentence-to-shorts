"""Display-to-speech mapping: K4, E2 and K5 words, and every failure code."""

from __future__ import annotations

import pytest

from app.tools.align import mapping

K4_DISPLAY = "가격은 12,500원이고, 성공률은 97.3퍼센트입니다."
K4_SPEECH = "가격은 만 이천오백 원이고, 성공률은 구십칠 점 삼 퍼센트입니다."
E2_DISPLAY = "The price is $12.50."
E2_SPEECH = "The price is twelve dollars and fifty cents."
K5_DISPLAY = "CPU와 GPU의 차이를 알고 있나요? Python API로 WAV 파일을 저장해 보세요."
K5_SPEECH = (
    "씨 피 유와 지 피 유의 차이를 알고 있나요? "
    "파이썬 에이 피 아이로 더블유 에이 브이 파일을 저장해 보세요."
)


def words(text: str, score: float = 0.9, low: tuple[str, ...] = ()) -> list[dict]:
    return [
        {
            "word": token,
            "start": round(index * 0.25, 3),
            "end": round(index * 0.25 + 0.2, 3),
            "score": 0.0 if token in low else score,
        }
        for index, token in enumerate(text.split())
    ]


def test_15_k4_number_spelling_maps_the_two_phrases() -> None:
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, words(K4_SPEECH), 3000)
    assert result.failure is None, result.reasons
    assert [(span.start_char, span.end_char) for span in result.phrases or []] == [
        (0, 14),
        (15, 31),
    ]
    assert K4_DISPLAY[0:14] == "가격은 12,500원이고,"
    assert result.phrases[0].start_ms == 0
    assert result.phrases[0].end_ms == 950


def test_15_e2_currency_maps_the_display_span() -> None:
    result = mapping.judge(E2_DISPLAY, E2_SPEECH, words(E2_SPEECH), 3000)
    assert result.failure is None, result.reasons
    assert len(result.phrases) == 1
    span = result.phrases[0]
    assert (span.start_char, span.end_char) == (0, len(E2_DISPLAY))
    assert (span.start_ms, span.end_ms) == (0, 1950)


def test_15_k5_code_names_map_when_the_scores_pass() -> None:
    result = mapping.judge(K5_DISPLAY, K5_SPEECH, words(K5_SPEECH), 6000)
    assert result.failure is None, result.reasons
    assert [(span.start_char, span.end_char) for span in result.phrases or []] == [
        (0, 21),
        (22, len(K5_DISPLAY)),
    ]


def test_15_k5_low_word_scores_fall_back_to_sentence_caption() -> None:
    measured = words(K5_SPEECH, low=("씨", "피", "지"))
    result = mapping.judge(K5_DISPLAY, K5_SPEECH, measured, 6000)
    assert result.failure == "align_low_confidence"
    assert result.phrases is None


@pytest.mark.parametrize("score", [mapping.LOW_CONFIDENCE_SCORE, 0.5])
def test_15_the_threshold_keeps_a_word_at_the_boundary(score: float) -> None:
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, words(K4_SPEECH, score=score), 3000)
    assert result.failure is None


def test_15_a_word_below_the_threshold_is_low_confidence() -> None:
    measured = words(K4_SPEECH, score=mapping.LOW_CONFIDENCE_SCORE - 0.01)
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, measured, 3000)
    assert result.failure == "align_low_confidence"


def test_15_a_word_without_a_score_is_low_confidence() -> None:
    measured = words(K4_SPEECH)
    del measured[0]["score"]
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, measured, 3000)
    assert result.failure == "align_low_confidence"


def test_15_a_currency_symbol_is_substitutable() -> None:
    display = "가격은 $입니다."
    speech = "가격은 달러입니다."
    result = mapping.judge(display, speech, words(speech), 3000)
    assert result.failure is None, result.reasons


def test_15_an_unrelated_word_change_is_a_missing_word() -> None:
    display = "값이 작아질수록 오차가 줄지만"
    speech = "값이 작아질수록 오류가 줄지만"
    result = mapping.judge(display, speech, words(speech), 3000)
    assert result.failure == "align_missing_words"
    assert result.phrases is None


def test_15_an_unordered_word_time_is_align_failed_before_missing_words() -> None:
    measured = words(K4_SPEECH)
    measured[1]["start"], measured[1]["end"] = 0.0, 0.1
    measured[2]["start"] = None
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, measured, 3000)
    assert result.failure == "align_missing_words"
    measured[2]["start"] = 0.5
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, measured, 3000)
    assert result.failure == "align_failed"


def test_15_a_word_without_a_time_is_a_missing_word() -> None:
    measured = words(K4_SPEECH)
    measured[0]["end"] = None
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, measured, 3000)
    assert result.failure == "align_missing_words"


def test_15_a_word_count_mismatch_is_a_missing_word() -> None:
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, words(K4_SPEECH)[:-1], 3000)
    assert result.failure == "align_missing_words"


def test_15_a_phrase_outside_the_speech_is_a_missing_word() -> None:
    result = mapping.judge(K4_DISPLAY, K4_SPEECH, words(K4_SPEECH), 100)
    assert result.failure == "align_missing_words"
    assert "phrase time outside the speech" in " ".join(result.reasons)


def test_15_a_phrase_count_mismatch_is_a_missing_word() -> None:
    result = mapping.judge("네. 아니요.", "네 아니요.", words("네 아니요."), 3000)
    assert result.failure == "align_missing_words"


def test_15_no_aligned_word_is_a_missing_word() -> None:
    result = mapping.judge("네.", "네.", [], 3000)
    assert result.failure == "align_missing_words"


def test_15_phrase_spans_keep_the_punctuation() -> None:
    assert mapping.phrase_spans("가격은 12,500원이고, 성공률은 97.3퍼센트입니다.") == [
        (0, 14),
        (15, 31),
    ]
