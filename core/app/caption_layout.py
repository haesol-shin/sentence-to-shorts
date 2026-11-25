"""Caption geometry on the 1080x1920 frame: the safe band, plates and presets.

A caption block sits at one of five presets inside the safe band. Its plate is
the block plus a 4px pad above and below, so a preset change moves the plate
with its text. A video read from a reference may instead store a pixel place
inside the wider place area; that place wins over the preset. The dialog bubble
of the builtin dialog template moves the same way: the preset places the bubble
in the band and the text stays centred in it. A sandbox layer draws its own box,
which cannot move, so the preset moves only the text inside that box. Text keeps
a side pad to the plate, bubble or box. This module is the only home for those
numbers, so the still, the clip and the template validator cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.schemas.common import Box
from app.schemas.settings import CaptionPlace, CaptionPosition
from app.schemas.template_manifest import TemplateManifest

SAFE_TOP = 1030
"""Top of the band that platform UI leaves uncovered, on the 1080x1920 frame."""

SAFE_BOTTOM = 1230
"""Bottom of that band."""

SAFE_HEIGHT = SAFE_BOTTOM - SAFE_TOP

FRAME_WIDTH = 1080
"""Width of the output frame; the safe band spans it edge to edge."""

FRAME_HEIGHT = 1920
"""Height of the output frame."""

PLACE_LEFT = 48
PLACE_TOP = 288
PLACE_WIDTH = 840
PLACE_HEIGHT = 960
"""The published vertical safe zone of the platform on the 1080x1920 frame:
48 to 888 across and 288 to 1248 down. A stored place stays inside it."""

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

PLATE_SIDE_PAD = 40
"""Shortest space between caption text and the left or right side of its plate."""

BUBBLE_OUTSET = 18
"""How far the dialog bubble reaches outside the template caption region: the three
skin cells of its border."""

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


def place_area() -> Box:
    """The area a stored pixel place may use: the platform's vertical safe zone."""
    return Box(x=PLACE_LEFT, y=PLACE_TOP, w=PLACE_WIDTH, h=PLACE_HEIGHT)


def place_box(place: CaptionPlace, block_height: int) -> Box:
    """The plate at a stored place: ``place.y`` is the top of the plate, not of the text."""
    return Box(x=place.x, y=place.y, w=place.w, h=plate_height(block_height))


def placed_box(place: CaptionPlace, block_height: int) -> Box | None:
    """The plate at ``place`` after the store clamp, or ``None`` when it cannot fit.

    The render and the two-layer fit check both need the same plate: a place at
    the bottom of the area moves up by the block height so its plate stays inside.
    """
    raw, _ = clamp_place(place.model_dump(), block_height)
    box = Box(
        x=raw["x"], y=raw["y"], w=raw["w"], h=plate_height(block_height)
    )
    return box if inside(box, place_area()) else None


def clamp_place(
    raw: Mapping[str, Any], block_height: int | None = None
) -> tuple[dict[str, Any], bool]:
    """Cut a raw place into ``place_area`` and report whether it moved.

    The store clamps before model validation, so a rounded corner or a fractional
    ratio cannot leave a plate outside the area. Values that are not a mapping
    with integer ``x``, ``y`` and ``w`` pass through: the model rejects them.
    """
    if not isinstance(raw, Mapping):
        return dict(raw), False  # type: ignore[arg-type]
    numbers = [raw.get(key) for key in ("x", "y", "w")]
    if any(
        isinstance(value, bool) or not isinstance(value, int) for value in numbers
    ):
        return dict(raw), False
    x, y, w = numbers
    area = place_area()
    kept_w = min(w, area.w)
    kept_x = min(max(x, area.x), area.x + area.w - kept_w)
    bottom = area.y + area.h - 2 * PLATE_PAD
    highest = max(area.y, bottom - (block_height or 0))
    kept_y = min(max(y, area.y), highest)
    clamped = dict(raw)
    clamped.update(x=kept_x, y=kept_y, w=kept_w)
    return clamped, (kept_x, kept_y, kept_w) != (x, y, w)


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


def smallest_caption_size(pixel_size: int | None) -> int:
    """The smallest text size used to check caption positions."""
    return (pixel_size or 12) * 2


def smallest_caption_height(pixel_size: int | None) -> int:
    """Height of the smallest caption block a layer may draw at its line limit."""
    return line_height(smallest_caption_size(pixel_size)) * CAPTION_MAX_LINES


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
    """The area a text block is drawn in when its box cannot move.

    A template-drawn (sandbox) box owns its place, so the preset moves the text
    through the space the block leaves.
    """
    return Box(
        x=inner.x,
        y=inner.y + _offset(inner.h - block_height, position),
        w=inner.w,
        h=block_height,
    )


def side_padded(inner: Box) -> Box:
    """``inner`` without ``PLATE_SIDE_PAD`` on its left and right."""
    return Box(
        x=inner.x + PLATE_SIDE_PAD,
        y=inner.y,
        w=max(1, inner.w - 2 * PLATE_SIDE_PAD),
        h=inner.h,
    )


def bubble_box(region: Box, position: CaptionPosition) -> Box:
    """The dialog bubble around a caption region, kept inside the safe band.

    The bubble does not change size with its text and the text is centred in it.
    ``top`` puts the bubble at the top of the band and ``bottom`` at its bottom, like a plate.
    """
    height = region.h + 2 * BUBBLE_OUTSET
    return Box(
        x=region.x - BUBBLE_OUTSET,
        y=SAFE_TOP + _offset(SAFE_HEIGHT - height, position),
        w=region.w + 2 * BUBBLE_OUTSET,
        h=height,
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


def place_pair_with_primary(
    inner: Box,
    primary_place: CaptionPlace,
    primary_heights: Sequence[int | None],
    extra_heights: Sequence[int | None],
    extra_position: CaptionPosition,
) -> CaptionPair | None:
    """First size pair whose primary stays at its place and whose extra keeps clear.

    The primary plate follows ``primary_place``; its size rank walks from the
    largest to the smallest. The extra layer keeps its preset inside ``inner``.
    ``None`` means no pair keeps both plates apart, so the caller drops the
    second layer instead of failing the render.
    """
    extra_area = safe_area()
    for primary_rank, primary_block in enumerate(primary_heights):
        if primary_block is None:
            continue
        primary = placed_box(primary_place, primary_block)
        if primary is None:
            continue
        for extra_rank, extra_block in enumerate(extra_heights):
            if extra_block is None:
                continue
            extra = plate_box(inner, extra_block, extra_position)
            if not inside(extra, extra_area) or not separated(primary, extra):
                continue
            return CaptionPair(
                primary=primary,
                extra=extra,
                primary_rank=primary_rank,
                extra_rank=extra_rank,
            )
    return None


def supports_caption_pair(template: TemplateManifest) -> bool:
    return not template.dialog_box and template.renderer.kind == "builtin"


def draws_bubble(template: TemplateManifest) -> bool:
    """Whether the app draws the template's caption bubble and moves it with the preset."""
    return template.dialog_box and template.renderer.kind == "builtin"


def caption_text_size(template: TemplateManifest) -> tuple[int, int]:
    """Widest line and tallest block of one caption layer in the template."""
    region = template.regions.caption
    inner = caption_inner(region, dialog=template.dialog_box)
    width = region.w + 2 * BUBBLE_OUTSET if draws_bubble(template) else inner.w
    return max(1, width - 2 * PLATE_SIDE_PAD), inner.h


def caption_region_fits(template: TemplateManifest) -> bool:
    """Whether the template keeps its captions inside the safe band at every preset."""
    region = template.regions.caption
    if not inside(region, safe_area()):
        return False
    if not draws_bubble(template):
        return True
    return (
        region.h + 2 * BUBBLE_OUTSET <= SAFE_HEIGHT
        and region.x >= BUBBLE_OUTSET
        and region.x + region.w + BUBBLE_OUTSET <= FRAME_WIDTH
    )


def caption_pair_fits(
    template: TemplateManifest,
    primary_pixel_size: int | None,
    primary: CaptionPosition,
    extra_pixel_size: int | None,
    extra: CaptionPosition,
    place: CaptionPlace | None = None,
) -> bool:
    """Whether the template has room for the smallest two-line plates.

    A stored place pins the primary plate, so the save check and the layout
    route search the same extra positions around it.
    """
    if not supports_caption_pair(template):
        return False
    inner = caption_inner(template.regions.caption, dialog=False)
    primary_height = smallest_caption_height(primary_pixel_size)
    extra_height = smallest_caption_height(extra_pixel_size)
    if place is not None:
        return place_pair_with_primary(
            inner, place, (primary_height,), (extra_height,), extra
        ) is not None
    return place_pair(
        inner,
        (primary_height,),
        primary,
        (extra_height,),
        extra,
    ) is not None


def single_caption_fits(
    template: TemplateManifest, pixel_size: int | None, position: CaptionPosition
) -> bool:
    region = template.regions.caption
    height = smallest_caption_height(pixel_size)
    if supports_caption_pair(template):
        inner = caption_inner(region, dialog=False)
        return inside(plate_box(inner, height, position), safe_area())
    if draws_bubble(template):
        return caption_region_fits(template) and height <= caption_text_size(template)[1]
    inner = caption_inner(region, dialog=template.dialog_box)
    return height <= inner.h and inside(region, safe_area())


__all__ = [
    "BUBBLE_OUTSET",
    "CAPTION_INSET",
    "CAPTION_MAX_LINES",
    "CaptionPair",
    "DIALOG_CAPTION_INSET",
    "FRAME_HEIGHT",
    "FRAME_WIDTH",
    "PLATE_GAP",
    "PLATE_PAD",
    "PLATE_SIDE_PAD",
    "PLACE_HEIGHT",
    "PLACE_LEFT",
    "PLACE_TOP",
    "PLACE_WIDTH",
    "POSITIONS",
    "SAFE_BOTTOM",
    "SAFE_HEIGHT",
    "SAFE_TOP",
    "bubble_box",
    "caption_inner",
    "caption_pair_fits",
    "caption_region_fits",
    "caption_text_size",
    "clamp_place",
    "draws_bubble",
    "fixed_text_box",
    "inside",
    "intersects",
    "line_height",
    "place_area",
    "place_box",
    "place_pair",
    "place_pair_with_primary",
    "placed_box",
    "plate_box",
    "plate_height",
    "rank_pairs",
    "safe_area",
    "separated",
    "side_padded",
    "single_caption_fits",
    "smallest_caption_height",
    "smallest_caption_size",
    "supports_caption_pair",
    "text_box",
]
