"""Caption text: bundled font, glyph coverage, width-based wrapping and drawing.

Wrapping measures real glyph advances of the selected font at the size it is
drawn. Text is drawn only with the font of the package: a code point missing
from its cmap fails with ``font_missing_glyph`` and no other font is tried.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import ImageDraw, ImageFont

from app.ports import AppError, CatalogPort, UnknownCatalogId
from app.schemas.common import Box, PinnedRef
from app.schemas.font_manifest import FontManifest
from app.schemas.script import Span

HANGUL_MEDIAL = range(0x1160, 0x11A8)
HANGUL_FINAL = range(0x11A8, 0x1200)
UNDERLINE_GAP_FONT_PX = 1


@dataclass(frozen=True)
class Unit:
    """One grapheme as drawn (NFC) and whether a highlight span covers it."""

    text: str
    highlight: bool

    @property
    def space(self) -> bool:
        return self.text.isspace()


def _joins_previous(char: str) -> bool:
    code = ord(char)
    return unicodedata.combining(char) != 0 or code in HANGUL_MEDIAL or code in HANGUL_FINAL


def units(text: str, highlight: list[Span] | None = None) -> list[Unit]:
    """Split into graphemes, compose each to NFC and keep highlight offsets of ``text``.

    Highlight spans index the stored display text, so composition happens per
    grapheme after the spans are mapped.
    """
    covered = [False] * len(text)
    for span in highlight or []:
        for index in range(span.start, min(span.end, len(text))):
            covered[index] = True
    result: list[Unit] = []
    start = 0
    for index in range(1, len(text) + 1):
        if index < len(text) and _joins_previous(text[index]):
            continue
        piece = text[start:index]
        result.append(
            Unit(unicodedata.normalize("NFC", piece), any(covered[start:index]))
        )
        start = index
    return result


@dataclass
class CaptionFont:
    id: str
    path: Path
    pixel_size: int | None
    _sizes: dict[int, ImageFont.FreeTypeFont] = field(default_factory=dict)

    @cached_property
    def cmap(self) -> frozenset[int]:
        font = TTFont(str(self.path), lazy=True)
        try:
            return frozenset(font.getBestCmap() or {})
        finally:
            font.close()

    def at(self, size: int) -> ImageFont.FreeTypeFont:
        font = self._sizes.get(size)
        if font is None:
            font = ImageFont.truetype(
                str(self.path), size, layout_engine=ImageFont.Layout.BASIC
            )
            self._sizes[size] = font
        return font

    def sizes(self, largest: int, smallest: int) -> list[int]:
        """Candidate sizes from large to small; whole multiples of a pixel font's grid."""
        if self.pixel_size:
            step = self.pixel_size
            return [k * step for k in range(largest // step, 0, -1) if k * step >= smallest]
        return list(range(largest, smallest - 1, -4))

    def check(self, text: str, where: str) -> None:
        missing = sorted(
            {
                f"U+{ord(char):04X}"
                for unit in units(text)
                for char in unit.text
                if not char.isspace() and ord(char) not in self.cmap
            }
        )
        if missing:
            raise AppError(
                "font_missing_glyph",
                detail={"font": self.id, "where": where, "code_points": missing[:20]},
            )


def open_font(catalog: CatalogPort, ref: PinnedRef) -> CaptionFont:
    try:
        manifest = catalog.get("font", ref.id, ref.revision)
        root = catalog.package_dir("font", ref)
    except UnknownCatalogId as error:
        raise AppError("unknown_catalog_id", detail={"kind": "font", "id": ref.id}) from error
    if not isinstance(manifest, FontManifest):
        raise AppError("unknown_catalog_id", detail={"kind": "font", "id": ref.id})
    return CaptionFont(id=manifest.id, path=root / manifest.file, pixel_size=manifest.pixel_size)


@dataclass(frozen=True)
class TextLine:
    units: tuple[Unit, ...]
    width: int

    @property
    def text(self) -> str:
        return "".join(unit.text for unit in self.units)


@dataclass(frozen=True)
class TextBlock:
    size: int
    line_height: int
    lines: tuple[TextLine, ...]

    @property
    def height(self) -> int:
        """Every line keeps its full line height, so the last underline stays inside."""
        return self.line_height * len(self.lines)


def _width(font: ImageFont.FreeTypeFont, items: list[Unit]) -> int:
    return int(round(font.getlength("".join(unit.text for unit in items))))


def _words(items: list[Unit]) -> list[list[Unit]]:
    words: list[list[Unit]] = []
    current: list[Unit] = []
    for unit in items:
        if unit.space:
            if current:
                words.append(current)
                current = []
        else:
            current.append(unit)
    if current:
        words.append(current)
    return words


def wrap(font: ImageFont.FreeTypeFont, items: list[Unit], max_width: int) -> list[TextLine]:
    """Greedy wrap at spaces; a word wider than a line breaks between graphemes."""
    lines: list[list[Unit]] = []
    current: list[Unit] = []
    for word in _words(items):
        joined = [*current, Unit(" ", False), *word] if current else word
        if _width(font, joined) <= max_width:
            current = joined
            continue
        if current:
            lines.append(current)
            current = []
        if _width(font, word) <= max_width:
            current = list(word)
            continue
        for unit in word:
            if current and _width(font, [*current, unit]) > max_width:
                lines.append(current)
                current = []
            current.append(unit)
    if current:
        lines.append(current)
    return [TextLine(tuple(line), _width(font, line)) for line in lines]


def wrap_code(font: ImageFont.FreeTypeFont, text: str, max_width: int) -> list[TextLine]:
    """Keep every source line break and indent; a line wider than the box continues
    on the next line, split between graphemes. A tab counts as four spaces."""
    lines: list[list[Unit]] = []
    for source in text.replace("\t", "    ").split("\n"):
        current: list[Unit] = []
        for unit in units(source):
            if current and _width(font, [*current, unit]) > max_width:
                lines.append(current)
                current = []
            current.append(unit)
        lines.append(current)
    return [TextLine(tuple(line), _width(font, line)) for line in lines]


def fit(
    font: CaptionFont,
    text: str,
    highlight: list[Span] | None,
    *,
    width: int,
    height: int,
    max_lines: int,
    sizes: list[int],
    where: str,
    code: bool = False,
) -> TextBlock:
    """The largest size whose wrapped lines fit the box; ``text_overflow`` otherwise.

    ``code`` keeps the text's own line breaks and spaces instead of reflowing words.
    """
    font.check(text, where)
    items = units(text, highlight)
    for size in sizes:
        face = font.at(size)
        lines = wrap_code(face, text, width) if code else wrap(face, items, width)
        if not lines:
            continue
        block = TextBlock(size=size, line_height=size * 5 // 4, lines=tuple(lines))
        too_wide = any(line.width > width for line in lines)
        if len(lines) <= max_lines and block.height <= height and not too_wide:
            return block
    raise AppError("text_overflow", detail={"where": where, "font": font.id})


Rgb = tuple[int, int, int]


def draw_block(
    draw: ImageDraw.ImageDraw,
    font: CaptionFont,
    block: TextBlock,
    box: Box,
    *,
    color: Rgb,
    highlight_color: Rgb,
    valign: str = "middle",
    align: str = "center",
) -> list[Box]:
    """Draw lines centred (or left aligned) in ``box``; highlights get a colour and an
    underline."""
    face = font.at(block.size)
    stroke = max(2, block.size // (font.pixel_size or 12))
    free = box.h - block.height
    top = box.y + {"top": 0, "middle": free // 2, "bottom": free}[valign]
    placed: list[Box] = []
    for index, line in enumerate(block.lines):
        y = top + index * block.line_height
        x0 = box.x if align == "left" else box.x + (box.w - line.width) // 2
        for unit_index, unit in enumerate(line.units):
            prefix = "".join(item.text for item in line.units[:unit_index])
            x = x0 + int(round(face.getlength(prefix)))
            fill = highlight_color if unit.highlight else color
            draw.text((x, y), unit.text, font=face, fill=fill)
            if unit.highlight and not unit.space:
                end = x0 + int(round(face.getlength(prefix + unit.text)))
                base = y + block.size + stroke * UNDERLINE_GAP_FONT_PX
                draw.rectangle((x, base, max(x, end - 1), base + stroke - 1), fill=fill)
        placed.append(Box(x=x0, y=y, w=max(1, line.width), h=block.line_height))
    return placed


__all__ = [
    "CaptionFont",
    "TextBlock",
    "TextLine",
    "Unit",
    "draw_block",
    "fit",
    "open_font",
    "units",
    "wrap",
]
