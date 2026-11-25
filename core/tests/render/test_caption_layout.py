"""Caption geometry of the builtin templates: bubble placement, text area and fit answers."""

from __future__ import annotations

import pytest

from app.caption_layout import (
    BUBBLE_OUTSET,
    PLATE_PAD,
    PLATE_SIDE_PAD,
    POSITIONS,
    SAFE_BOTTOM,
    SAFE_TOP,
    bubble_box,
    caption_pair_fits,
    caption_text_size,
    clamp_place,
    inside,
    place_area,
    place_box,
    safe_area,
    single_caption_fits,
)
from app.plugins.registry import Registry
from app.schemas.settings import CaptionPlace, CaptionPosition
from app.schemas.template_manifest import TemplateManifest

NAMES = ["fixed_stage", "full_stage", "dialog_stage"]


def _template(registry: Registry, name: str) -> TemplateManifest:
    manifest = registry.get("template", name)
    assert isinstance(manifest, TemplateManifest)
    return manifest


def test_29_dialog_bubble_walks_through_the_band_from_top_to_bottom(registry: Registry) -> None:
    region = _template(registry, "dialog_stage").regions.caption
    bubbles = [bubble_box(region, position) for position in POSITIONS]
    assert bubbles[0].y == SAFE_TOP
    assert bubbles[-1].y + bubbles[-1].h == SAFE_BOTTOM
    assert [bubble.y for bubble in bubbles] == sorted({bubble.y for bubble in bubbles})
    for bubble in bubbles:
        assert inside(bubble, safe_area())
        assert (bubble.x, bubble.w) == (region.x - BUBBLE_OUTSET, region.w + 2 * BUBBLE_OUTSET)


@pytest.mark.parametrize("name", NAMES)
def test_29_text_keeps_a_side_pad_inside_the_widest_plate(registry: Registry, name: str) -> None:
    width, _ = caption_text_size(_template(registry, name))
    assert width == 936 - 2 * PLATE_SIDE_PAD


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("position", POSITIONS)
def test_29_builtin_templates_fit_the_smallest_caption_at_every_preset(
    registry: Registry, name: str, position: CaptionPosition
) -> None:
    assert single_caption_fits(_template(registry, name), 11, position)


def test_29_place_area_is_the_published_vertical_safe_zone() -> None:
    area = place_area()
    assert (area.x, area.y, area.w, area.h) == (48, 288, 840, 960)


def test_29_clamp_place_cuts_a_plate_into_the_place_area() -> None:
    clamped, moved = clamp_place({"x": 888, "y": 600, "w": 840, "align": "center"})
    assert moved
    assert (clamped["x"], clamped["y"], clamped["w"]) == (48, 600, 840)
    assert clamped["align"] == "center"
    narrow, moved = clamp_place({"x": 888, "y": 600, "w": 400})
    assert moved and (narrow["x"], narrow["w"]) == (488, 400)
    assert clamp_place({"x": 48, "y": 500, "w": 840})[1] is False


def test_29_clamp_place_lifts_a_plate_above_the_area_bottom() -> None:
    clamped, moved = clamp_place({"x": 48, "y": 1240, "w": 840}, block_height=100)
    assert moved
    assert clamped["y"] == 1140


def test_29_place_box_is_the_block_plus_the_plate_pad() -> None:
    plate = place_box(CaptionPlace(x=48, y=600, w=600), 90)
    assert (plate.x, plate.y, plate.w, plate.h) == (48, 600, 600, 90 + 2 * PLATE_PAD)
    assert inside(plate, place_area())


def test_29_place_pair_moves_a_bottom_place_up_for_its_block(registry: Registry) -> None:
    template = _template(registry, "fixed_stage")
    place = CaptionPlace(x=48, y=1240, w=840)
    assert caption_pair_fits(
        template, 11, CaptionPosition.bottom, 11, CaptionPosition.top, place
    )
