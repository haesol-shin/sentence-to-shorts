"""Map the screen text of a line onto the words the aligner timed.

The aligner hears the spoken text, which can spell a number or a code name
differently from the screen text. A phrase span must stay inside the display
text and the line's speech, cover every non-space display character, and keep
word scores at or above ``LOW_CONFIDENCE_SCORE``. A broken or unsure mapping
returns a failure code and no phrases, so the line becomes a sentence caption
without an invented time. Failure precedence is ``align_failed``,
``align_missing_words``, ``align_low_confidence``.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from app.ports import PhraseSpan

LOW_CONFIDENCE_SCORE = 0.25
"""A word below this mean character score makes the line a sentence caption."""

FAILED = "align_failed"
LOW_CONFIDENCE = "align_low_confidence"
MISSING_WORDS = "align_missing_words"
UNAVAILABLE = "align_unavailable"

_PHRASE_END = set(".!?。？！,;:")
_PUNCTUATION = "".join(
    [
        "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
        "…、。！？，．：；·",
        "“”‘’「」『』〈〉《》（）［］｛｝",
    ]
)
_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_ASCII_LETTER = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"[0-9]")
_CURRENCY = re.compile(r"[$€£¥₩]")


@dataclass(frozen=True)
class MappingResult:
    phrases: list[PhraseSpan] | None
    failure: str | None
    reasons: list[str]
    display_phrases: int
    speech_phrases: int


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


def tokenize(text: str) -> list[Token]:
    """Split on whitespace and keep character offsets."""
    return [Token(match.group(), match.start(), match.end()) for match in re.finditer(r"\S+", text)]


def phrase_spans(text: str) -> list[tuple[int, int]]:
    """Split at sentence punctuation and commas, keeping the punctuation."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    for token in tokenize(text):
        if start is None:
            start = token.start
        end = token.end
        if token.text[-1] in _PHRASE_END:
            spans.append((start, end))
            start = None
    if start is not None:
        spans.append((start, end))
    return spans


def normalize(token: str) -> str:
    return unicodedata.normalize("NFC", token).strip(_PUNCTUATION).casefold()


def _substitutable(display_tokens: list[Token], speech_tokens: list[Token]) -> bool:
    """True when the pair can differ by number spelling or a code name."""
    if any(_DIGIT.search(token.text) or _CURRENCY.search(token.text) for token in display_tokens):
        return True
    if any(_ASCII_LETTER.search(token.text) for token in display_tokens) and any(
        _HANGUL.search(token.text) for token in speech_tokens
    ):
        return True
    return any(
        len(token.text) >= 2
        and token.text.isascii()
        and token.text.upper() == token.text
        and _ASCII_LETTER.search(token.text)
        for token in display_tokens
    )


def _word_field(word: dict, key: str) -> float | None:
    value = word.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _score_field(word: dict) -> float | None:
    value = word.get("score")
    return float(value) if isinstance(value, (int, float)) else None


def _map_pair(
    display_tokens: list[Token],
    speech_tokens: list[Token],
) -> tuple[dict[int, list[int]], list[str]]:
    """Map display token indexes to speech token indexes for one phrase pair."""
    display_keys = [normalize(token.text) for token in display_tokens]
    speech_keys = [normalize(token.text) for token in speech_tokens]
    mapping: dict[int, list[int]] = {}
    reasons: list[str] = []
    matcher = difflib.SequenceMatcher(a=display_keys, b=speech_keys, autojunk=False)
    for tag, d1, d2, s1, s2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(d2 - d1):
                mapping[d1 + offset] = [s1 + offset]
        elif tag == "replace":
            if not _substitutable(display_tokens[d1:d2], speech_tokens[s1:s2]):
                reasons.append(
                    "display words without a spoken counterpart: "
                    + " ".join(token.text for token in display_tokens[d1:d2])
                )
            group = list(range(s1, s2))
            for index in range(d1, d2):
                mapping[index] = group
        elif tag == "delete":
            reasons.append(
                "display words without a spoken counterpart: "
                + " ".join(token.text for token in display_tokens[d1:d2])
            )
        elif tag == "insert":
            reasons.append(
                "spoken words without a display counterpart: "
                + " ".join(token.text for token in speech_tokens[s1:s2])
            )
    return mapping, reasons


def _token_ranges(tokens: list[Token], spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return the token index range covered by each phrase span."""
    ranges: list[tuple[int, int]] = []
    pointer = 0
    for _, end_char in spans:
        first = pointer
        while pointer < len(tokens) and tokens[pointer].start < end_char:
            pointer += 1
        ranges.append((first, pointer))
    return ranges


def _validate_phrases(phrases: list[PhraseSpan], display_text: str, speech_ms: int) -> list[str]:
    reasons: list[str] = []
    previous_end = 0
    covered = [False] * len(display_text)
    for span in phrases:
        if not 0 <= span.start_char < span.end_char <= len(display_text):
            reasons.append("phrase outside the display text")
            continue
        if span.start_char < previous_end:
            reasons.append("phrase order is not increasing")
        if not 0 <= span.start_ms < span.end_ms <= speech_ms:
            reasons.append("phrase time outside the speech")
        for index in range(span.start_char, span.end_char):
            covered[index] = True
        previous_end = span.end_char
    for index, is_covered in enumerate(covered):
        if not is_covered and not display_text[index].isspace():
            reasons.append(f"display character {index} is not mapped")
            break
    return reasons


def _timing_failure(words: list[dict]) -> tuple[str, str] | None:
    """A missing or out-of-order word time, with the code the contract names."""
    missing = [
        str(word.get("word", ""))
        for word in words
        if (_word_field(word, "start") is None or _word_field(word, "end") is None)
        or (_word_field(word, "end") or 0) <= (_word_field(word, "start") or 0)
    ]
    if missing:
        return MISSING_WORDS, "words without usable times: " + " ".join(missing)
    starts = [_word_field(word, "start") for word in words]
    ends = [_word_field(word, "end") for word in words]
    if any(starts[index] > starts[index + 1] for index in range(len(starts) - 1)) or any(
        ends[index] > ends[index + 1] for index in range(len(ends) - 1)
    ):
        return FAILED, "word times are not ordered"
    return None


def _phrase_rows(
    display_text: str,
    speech_text: str,
    words: list[dict],
) -> tuple[list[tuple[int, int, int, int]] | None, str | None, list[str]]:
    """Display span and first/last spoken word indexes for every phrase."""
    display_phrases = phrase_spans(display_text)
    speech_phrases = phrase_spans(speech_text)
    if len(display_phrases) != len(speech_phrases):
        return (
            None,
            MISSING_WORDS,
            [f"display has {len(display_phrases)} phrases and speech has {len(speech_phrases)}"],
        )
    display_tokens = tokenize(display_text)
    speech_tokens = tokenize(speech_text)
    display_ranges = _token_ranges(display_tokens, display_phrases)
    speech_ranges = _token_ranges(speech_tokens, speech_phrases)
    rows: list[tuple[int, int, int, int]] = []
    for index, (start_char, end_char) in enumerate(display_phrases):
        display_range = display_ranges[index]
        speech_range = speech_ranges[index]
        if display_range[0] >= display_range[1] or speech_range[0] >= speech_range[1]:
            return (None, MISSING_WORDS, [f"phrase {index} has no words on one side"])
        display_slice = display_tokens[display_range[0] : display_range[1]]
        speech_slice = speech_tokens[speech_range[0] : speech_range[1]]
        mapping, reasons = _map_pair(display_slice, speech_slice)
        if reasons:
            return (None, MISSING_WORDS, reasons)
        speech_indexes = sorted({item for group in mapping.values() for item in group})
        if len(speech_indexes) != speech_range[1] - speech_range[0]:
            return (None, MISSING_WORDS, [f"phrase {index} leaves spoken words unmapped"])
        rows.append((start_char, end_char, speech_range[0], speech_range[1] - 1))
    return rows, None, []


def judge(
    display_text: str,
    speech_text: str,
    words: list[dict],
    speech_ms: int,
) -> MappingResult:
    """Return phrase spans for the line, or the sentence-caption failure code."""
    display_phrases = phrase_spans(display_text)
    speech_phrases = phrase_spans(speech_text)
    counts = len(display_phrases), len(speech_phrases)
    if not words:
        return MappingResult(None, MISSING_WORDS, ["no aligned words"], *counts)
    timing = _timing_failure(words)
    if timing is not None:
        failure, reason = timing
        return MappingResult(None, failure, [reason], *counts)
    speech_words = len(tokenize(speech_text))
    if speech_words != len(words):
        return MappingResult(
            None,
            MISSING_WORDS,
            [f"speech has {speech_words} words and the aligner returned {len(words)}"],
            *counts,
        )
    rows, failure, reasons = _phrase_rows(display_text, speech_text, words)
    if rows is None:
        return MappingResult(None, failure, reasons, *counts)
    phrases = [
        PhraseSpan(
            start_char=start_char,
            end_char=end_char,
            start_ms=round((_word_field(words[first], "start") or 0.0) * 1000),
            end_ms=round((_word_field(words[last], "end") or 0.0) * 1000),
        )
        for start_char, end_char, first, last in rows
    ]
    phrase_reasons = _validate_phrases(phrases, display_text, speech_ms)
    if phrase_reasons:
        return MappingResult(None, MISSING_WORDS, phrase_reasons, *counts)
    low = [
        str(word.get("word", ""))
        for word in words
        if _score_field(word) is None or _score_field(word) < LOW_CONFIDENCE_SCORE
    ]
    if low:
        return MappingResult(
            None,
            LOW_CONFIDENCE,
            [f"word score below {LOW_CONFIDENCE_SCORE}: " + " ".join(low)],
            *counts,
        )
    return MappingResult(phrases, None, [], *counts)
