"""Display text segmentation shared by timing, render, mix and cache keys.

One cluster is one shown character. The render service draws a cluster at once,
the voice service records its span, and the sound service strikes one key at the
span start. All three read this module, so a character that the renderer shows in
one frame and the sound service skips stay the same character.
"""

from __future__ import annotations

import unicodedata

ZWJ = "\u200d"
"""Zero width joiner. It binds the emoji before and after it into one cluster."""

_VARIATION_SELECTORS = range(0xFE00, 0xFE10)
_VARIATION_SELECTORS_SUPPLEMENT = range(0xE0100, 0xE01F0)
_EMOJI_MODIFIERS = range(0x1F3FB, 0x1F400)
_REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)
_HANGUL_MEDIAL = range(0x1160, 0x11A8)
_HANGUL_FINAL = range(0x11A8, 0x1200)


def _joins_previous(text: str, index: int) -> bool:
    """Whether the code point at ``index`` belongs to the cluster before it."""
    char = text[index]
    previous = text[index - 1]
    code = ord(char)
    if unicodedata.category(char).startswith("M"):
        return True
    if code in _VARIATION_SELECTORS or code in _VARIATION_SELECTORS_SUPPLEMENT:
        return True
    if code in _EMOJI_MODIFIERS:
        return True
    if char == ZWJ or previous == ZWJ:
        return True
    if code in _HANGUL_MEDIAL or code in _HANGUL_FINAL:
        return True
    if code in _REGIONAL_INDICATORS:
        before = index - 1
        count = 0
        while before >= 0 and ord(text[before]) in _REGIONAL_INDICATORS:
            count += 1
            before -= 1
        return count % 2 == 1
    return False


def clusters(text: str) -> list[tuple[int, int]]:
    """Code point spans of the grapheme clusters of ``text``, in order.

    Combining marks, Hangul jamo, variation selectors, emoji modifiers, emoji
    ZWJ sequences and regional indicator pairs stay with their base character.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(text) + 1):
        if index < len(text) and _joins_previous(text, index):
            continue
        spans.append((start, index))
        start = index
    return spans


def is_silent(cluster: str) -> bool:
    """A cluster that makes no typing sound: whitespace or starting punctuation."""
    if not cluster:
        return True
    return cluster.isspace() or unicodedata.category(cluster[0]).startswith("P")


def voiced_clusters(text: str) -> list[tuple[int, int]]:
    """Spans of the clusters that make a typing sound, in display order."""
    return [span for span in clusters(text) if not is_silent(text[span[0]:span[1]])]


__all__ = ["clusters", "is_silent", "voiced_clusters"]
