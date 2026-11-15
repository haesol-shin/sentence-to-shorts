from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mapping


def words(text: str, score: float = 0.9) -> list[dict]:
    tokens = text.split()
    return [
        {"word": token, "start": round(index * 0.3, 3), "end": round(index * 0.3 + 0.25, 3), "score": score}
        for index, token in enumerate(tokens)
    ]


class PhraseSplitTest(unittest.TestCase):
    def test_phrase_split_keeps_punctuation_and_spans(self) -> None:
        text = "가격은 12,500원이고, 성공률은 97.3퍼센트입니다."
        self.assertEqual(mapping.phrase_spans(text), [(0, 14), (15, 31)])
        self.assertEqual(text[0:14], "가격은 12,500원이고,")
        self.assertEqual(text[15:31], "성공률은 97.3퍼센트입니다.")


class SubstitutionTest(unittest.TestCase):
    def test_number_spelling_maps_the_display_span(self) -> None:
        display = "가격은 12,500원이고, 성공률은 97.3퍼센트입니다."
        speech = "가격은 만 이천오백 원이고, 성공률은 구십칠 점 삼 퍼센트입니다."
        result = mapping.judge(display, speech, words(speech), 4000)
        self.assertIsNone(result.failure, result.reasons)
        self.assertEqual(len(result.phrases), 2)

    def test_code_name_maps_the_display_span(self) -> None:
        display = "CPU와 GPU의 차이를 알고 있나요?"
        speech = "씨 피 유와 지 피 유의 차이를 알고 있나요?"
        result = mapping.judge(display, speech, words(speech), 4000)
        self.assertIsNone(result.failure, result.reasons)
        self.assertEqual(result.phrases[0].start_char, 0)
        self.assertEqual(result.phrases[0].end_char, len(display))

    def test_unrelated_word_change_is_a_missing_word(self) -> None:
        display = "값이 작아질수록 오차가 줄지만"
        speech = "값이 작아질수록 오류가 줄지만"
        result = mapping.judge(display, speech, words(speech), 4000)
        self.assertEqual(result.failure, "align_missing_words")
        self.assertIsNone(result.phrases)


class FailureTest(unittest.TestCase):
    def test_word_without_time_is_a_missing_word(self) -> None:
        display = "네. 아니요."
        speech = "네. 아니요."
        measured = words(speech)
        measured[1]["start"] = None
        result = mapping.judge(display, speech, measured, 4000)
        self.assertEqual(result.failure, "align_missing_words")

    def test_low_word_score_is_low_confidence(self) -> None:
        display = "네. 아니요."
        speech = "네. 아니요."
        measured = words(speech, score=mapping.LOW_CONFIDENCE_SCORE - 0.01)
        result = mapping.judge(display, speech, measured, 4000)
        self.assertEqual(result.failure, "align_low_confidence")
        self.assertIsNone(result.phrases)

    def test_phrase_time_outside_speech_is_a_missing_word(self) -> None:
        display = "네. 아니요."
        speech = "네. 아니요."
        result = mapping.judge(display, speech, words(speech), 300)
        self.assertEqual(result.failure, "align_missing_words")
        self.assertIn("phrase time outside the speech", result.reasons)

    def test_sentence_count_mismatch_is_a_missing_word(self) -> None:
        display = "네. 아니요."
        speech = "네 아니요."
        result = mapping.judge(display, speech, words(speech), 4000)
        self.assertEqual(result.failure, "align_missing_words")

    def test_unaligned_speech_is_a_missing_word(self) -> None:
        result = mapping.judge("네.", "네.", [], 4000)
        self.assertEqual(result.failure, "align_missing_words")


if __name__ == "__main__":
    unittest.main()
