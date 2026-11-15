"""Display-to-speech phrase mapping and verdicts for the alignment probe.

Pure functions and no model. The rules follow the alignment contract: a phrase
span maps a display_text character range to speech milliseconds, the mapping
must cover the line, and a broken or low-confidence mapping turns the line into
a sentence caption instead of a guessed one.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

# A word score is the mean character score reported by the aligner. The probe
# records every score, so a different threshold can be replayed from the JSON.
LOW_CONFIDENCE_SCORE = 0.25

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


@dataclass(frozen=True)
class PhraseSpan:
    """Display text character span with speech milliseconds."""

    start_char: int
    end_char: int
    start_ms: int
    end_ms: int


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
    if any(_DIGIT.search(token.text) for token in display_tokens):
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
    for start_char, end_char in spans:
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


def judge(
    display_text: str,
    speech_text: str,
    words: list[dict],
    speech_ms: int,
) -> MappingResult:
    """Map a line and return phrases or a fallback reason.

    Failure precedence is "align_failed", "align_missing_words",
    "align_low_confidence". The order is recorded in the result document.
    """
    display_phrases = phrase_spans(display_text)
    speech_phrases = phrase_spans(speech_text)
    if not words:
        return MappingResult(None, "align_missing_words", ["no aligned words"], len(display_phrases), len(speech_phrases))
    missing_timing: list[str] = []
    for word in words:
        start = _word_field(word, "start")
        end = _word_field(word, "end")
        if start is None or end is None or end <= start:
            missing_timing.append(str(word.get("word", "")))
    if missing_timing:
        return MappingResult(
            None,
            "align_missing_words",
            ["words without usable times: " + " ".join(missing_timing)],
            len(display_phrases),
            len(speech_phrases),
        )
    display_tokens = tokenize(display_text)
    speech_tokens = tokenize(speech_text)
    if len(speech_tokens) != len(words):
        return MappingResult(
            None,
            "align_missing_words",
            [f"speech has {len(speech_tokens)} words and the aligner returned {len(words)}"],
            len(display_phrases),
            len(speech_phrases),
        )
    starts = [_word_field(word, "start") for word in words]
    ends = [_word_field(word, "end") for word in words]
    if any(starts[index] > starts[index + 1] for index in range(len(starts) - 1)) or any(
        ends[index] > ends[index + 1] for index in range(len(ends) - 1)
    ):
        return MappingResult(None, "align_failed", ["word times are not ordered"], len(display_phrases), len(speech_phrases))
    if len(display_phrases) != len(speech_phrases):
        return MappingResult(
            None,
            "align_missing_words",
            [f"display has {len(display_phrases)} phrases and speech has {len(speech_phrases)}"],
            len(display_phrases),
            len(speech_phrases),
        )
    display_ranges = _token_ranges(display_tokens, display_phrases)
    speech_ranges = _token_ranges(speech_tokens, speech_phrases)
    phrase_token_indexes: list[tuple[int, int, int, int]] = []
    for index, (start_char, end_char) in enumerate(display_phrases):
        display_range = display_ranges[index]
        speech_range = speech_ranges[index]
        if display_range[0] >= display_range[1] or speech_range[0] >= speech_range[1]:
            return MappingResult(
                None,
                "align_missing_words",
                [f"phrase {index} has no words on one side"],
                len(display_phrases),
                len(speech_phrases),
            )
        display_slice = display_tokens[display_range[0] : display_range[1]]
        speech_slice = speech_tokens[speech_range[0] : speech_range[1]]
        mapping, reasons = _map_pair(display_slice, speech_slice)
        if reasons:
            return MappingResult(
                None,
                "align_missing_words",
                reasons,
                len(display_phrases),
                len(speech_phrases),
            )
        speech_indexes = sorted({speech_index for group in mapping.values() for speech_index in group})
        if len(speech_indexes) != speech_range[1] - speech_range[0]:
            return MappingResult(
                None,
                "align_missing_words",
                [f"phrase {index} leaves spoken words unmapped"],
                len(display_phrases),
                len(speech_phrases),
            )
        first = speech_range[0]
        last = speech_range[1] - 1
        phrase_token_indexes.append((start_char, end_char, first, last))
    phrases = [
        PhraseSpan(
            start_char=start_char,
            end_char=end_char,
            start_ms=round(_word_field(words[first], "start") * 1000),
            end_ms=round(_word_field(words[last], "end") * 1000),
        )
        for start_char, end_char, first, last in phrase_token_indexes
    ]
    phrase_reasons = _validate_phrases(phrases, display_text, speech_ms)
    if phrase_reasons:
        return MappingResult(None, "align_missing_words", phrase_reasons, len(display_phrases), len(speech_phrases))
    low = [
        str(word.get("word", ""))
        for word in words
        if (_score_field(word) is None or _score_field(word) < LOW_CONFIDENCE_SCORE)
    ]
    if low:
        return MappingResult(
            None,
            "align_low_confidence",
            [f"word score below {LOW_CONFIDENCE_SCORE}: " + " ".join(low)],
            len(display_phrases),
            len(speech_phrases),
        )
    return MappingResult(phrases, None, [], len(display_phrases), len(speech_phrases))
