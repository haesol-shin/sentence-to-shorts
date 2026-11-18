"""Caption geometry on the 1080x1920 frame: the safe band, plates and presets.

A caption block sits at one of five presets inside the safe band. Its plate is
the block plus a 4px pad above and below, so a preset change moves the plate
with its text. A template that draws its own box (a dialog bubble or a sandbox
layer) keeps the plate fixed and moves only the text inside it. This module is
the only home for those numbers, so the still, the clip and the template
validator cannot drift apart.
"""

from __future__ import annotations

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


def plate_height(block_height: int) -> int:
    """Height of the plate around a text block."""
    return block_height + 2 * PLATE_PAD


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


__all__ = [
    "FRAME_WIDTH",
    "PLATE_GAP",
    "PLATE_PAD",
    "POSITIONS",
    "SAFE_BOTTOM",
    "SAFE_HEIGHT",
    "SAFE_TOP",
    "fixed_text_box",
    "inside",
    "intersects",
    "plate_box",
    "plate_height",
    "safe_area",
    "text_box",
]
