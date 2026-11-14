"""Glyph coverage from the font cmap.

A code point that the cmap does not map has no glyph in the font, so FreeType
draws the .notdef box and another platform may draw a different fallback. The
probe records those code points instead of guessing from a rasterized sample.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont


@dataclass(frozen=True)
class FontInfo:
    cmap: dict[int, str]
    units_per_em: int
    glyph_count: int
    family: str
    style: str


def load(font_path: Path) -> FontInfo:
    with TTFont(str(font_path), lazy=True) as font:
        cmap = font.getBestCmap() or {}
        return FontInfo(
            cmap=cmap,
            units_per_em=font["head"].unitsPerEm,
            glyph_count=len(cmap),
            family=font["name"].getDebugName(1) or "",
            style=font["name"].getDebugName(2) or "",
        )


def missing_glyphs(cmap: dict[int, str], text: str) -> list[dict]:
    """Return the code points of text that the cmap does not map, once each."""
    missing: list[dict] = []
    seen: set[int] = set()
    for char in text:
        code = ord(char)
        if code in cmap or code in seen:
            continue
        seen.add(code)
        missing.append(
            {
                "codepoint": f"U+{code:04X}",
                "char": char,
                "name": unicodedata.name(char, "UNKNOWN"),
            }
        )
    return missing
