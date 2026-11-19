"""Caption geometry on the 1080x1920 frame: the safe band, plates and presets.

A caption block sits at one of five presets inside the safe band. Its plate is
the block plus a 4px pad above and below, so a preset change moves the plate
with its text. A template that draws its own box (a dialog bubble or a sandbox
layer) keeps the plate fixed and moves only the text inside it. This module is
the only home for those numbers, so the still, the clip and the template
validator cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from app.schemas.common import Box
from app.schemas.settings import CaptionPosition

SAFE_TOP = 1030
"""Top of the band that platform UI leaves uncovered, on the 1080x1920 frame."""

SAFE_BOTTOM = 1230
"""Bottom of that band."""

SAFE_HEIGHT = SAFE_BOTTOM - SAFE_TOP

FRAME_WIDTH = 1080
"""Width of the output frame; the safe band spans it edge to edge."""

PLATE_PAD = 4
"""Space above and below a text block inside its plate."""

PLATE_GAP = 8
"""Shortest empty band between two plates that share the safe band."""

CAPTION_INSET = 24
"""Space between the template caption region and the text it holds."""

DIALOG_CAPTION_INSET = 12
"""Tighter inset inside a dialog bubble or a template-drawn box."""

CAPTION_MAX_LINES = 2
"""Lines one caption layer may use inside its plate."""

POSITIONS: tuple[CaptionPosition, ...] = (
    CaptionPosition.top,
    CaptionPosition.upper,
    CaptionPosition.middle,
    CaptionPosition.lower,
    CaptionPosition.bottom,
)
"""The five presets, from the top of the safe band to its bottom."""

STEPS = len(POSITIONS) - 1


def safe_area() -> Box:
    """The whole band that captions may use."""
    return Box(x=0, y=SAFE_TOP, w=FRAME_WIDTH, h=SAFE_HEIGHT)


def caption_inner(region: Box, *, dialog: bool) -> Box:
    """The caption text area inside a template's caption region."""
    inset = DIALOG_CAPTION_INSET if dialog else CAPTION_INSET
    return Box(
        x=region.x + inset,
        y=region.y + inset,
        w=region.w - 2 * inset,
        h=region.h - 2 * inset,
    )


def plate_height(block_height: int) -> int:
    """Height of the plate around a text block."""
    return block_height + 2 * PLATE_PAD


def line_height(size: int) -> int:
    """Height of one caption text line at ``size`` pixels."""
    return size * 5 // 4


def smallest_caption_height(pixel_size: int | None) -> int:
    """Height of the smallest caption block a layer may draw at its line limit."""
    return line_height((pixel_size or 12) * 2) * CAPTION_MAX_LINES


def _offset(free: int, position: CaptionPosition) -> int:
    """How far down a ``free``-px gap the preset asks for, from nothing to all."""
    return round(free * POSITIONS.index(position) / STEPS)


def plate_box(inner: Box, block_height: int, position: CaptionPosition) -> Box:
    """The plate that follows a text block, kept inside the safe band.

    ``inner`` gives the text width: the caption region without its insets.
    ``top`` puts the plate at the top of the band and ``bottom`` at its bottom.
    """
    height = plate_height(block_height)
    return Box(
        x=inner.x,
        y=SAFE_TOP + _offset(SAFE_HEIGHT - height, position),
        w=inner.w,
        h=height,
    )


def text_box(plate: Box, block_height: int) -> Box:
    """The area a text block is drawn in: its plate without the pad."""
    return Box(x=plate.x, y=plate.y + PLATE_PAD, w=plate.w, h=block_height)


def fixed_text_box(inner: Box, block_height: int, position: CaptionPosition) -> Box:
    """The area a text block is drawn in when its plate cannot move.

    A dialog bubble or a template-drawn box owns the plate, so the preset moves
    the text through the space the block leaves.
    """
    return Box(
        x=inner.x,
        y=inner.y + _offset(inner.h - block_height, position),
        w=inner.w,
        h=block_height,
    )


def inside(box: Box, area: Box) -> bool:
    """Whether all of ``box`` is inside ``area``."""
    return (
        box.x >= area.x
        and box.y >= area.y
        and box.x + box.w <= area.x + area.w
        and box.y + box.h <= area.y + area.h
    )


def intersects(first: Box, second: Box) -> bool:
    """Whether two boxes share at least one pixel; boxes that only touch do not."""
    return (
        first.x < second.x + second.w
        and second.x < first.x + first.w
        and first.y < second.y + second.h
        and second.y < first.y + first.h
    )


def separated(first: Box, second: Box) -> bool:
    """Whether two plates leave ``PLATE_GAP`` empty pixels between them."""
    if intersects(first, second):
        return False
    horizontal = max(
        second.x - (first.x + first.w), first.x - (second.x + second.w)
    )
    vertical = max(
        second.y - (first.y + first.h), first.y - (second.y + second.h)
    )
    return max(horizontal, vertical) >= PLATE_GAP


def rank_pairs(primary_count: int, extra_count: int) -> Iterator[tuple[int, int]]:
    """Size ranks to try for two layers: total cost, then the larger, then primary.

    Both layers start at their largest size. A pair that costs less in total is
    tried first, so the primary stays as large as the extra layer allows.
    """
    for total in range(primary_count + extra_count - 1):
        first = max(0, total - extra_count + 1)
        last = min(primary_count - 1, total)
        pairs = [(primary, total - primary) for primary in range(first, last + 1)]
        yield from sorted(pairs, key=lambda pair: (max(pair), pair[0]))


@dataclass(frozen=True)
class CaptionPair:
    """Plates of two caption layers that sit in the safe band without touching."""

    primary: Box
    extra: Box
    primary_rank: int
    extra_rank: int


def place_pair(
    inner: Box,
    primary_heights: Sequence[int | None],
    primary_position: CaptionPosition,
    extra_heights: Sequence[int | None],
    extra_position: CaptionPosition,
) -> CaptionPair | None:
    """First size pair that fits both plates, or ``None`` when no pair fits.

    ``*_heights`` holds the block height at each size rank, or ``None`` when the
    text does not fit at that size.
    """
    for primary_rank, extra_rank in rank_pairs(
        len(primary_heights), len(extra_heights)
    ):
        primary_block = primary_heights[primary_rank]
        extra_block = extra_heights[extra_rank]
        if primary_block is None or extra_block is None:
            continue
        primary = plate_box(inner, primary_block, primary_position)
        extra = plate_box(inner, extra_block, extra_position)
        if not inside(primary, safe_area()) or not inside(extra, safe_area()):
            continue
        if not separated(primary, extra):
            continue
        return CaptionPair(
            primary=primary,
            extra=extra,
            primary_rank=primary_rank,
            extra_rank=extra_rank,
        )
    return None


__all__ = [
    "CAPTION_INSET",
    "CAPTION_MAX_LINES",
    "CaptionPair",
    "DIALOG_CAPTION_INSET",
    "FRAME_WIDTH",
    "PLATE_GAP",
    "PLATE_PAD",
    "POSITIONS",
    "SAFE_BOTTOM",
    "SAFE_HEIGHT",
    "SAFE_TOP",
    "caption_inner",
    "fixed_text_box",
    "inside",
    "intersects",
    "line_height",
    "place_pair",
    "plate_box",
    "plate_height",
    "rank_pairs",
    "safe_area",
    "separated",
    "smallest_caption_height",
    "text_box",
]
