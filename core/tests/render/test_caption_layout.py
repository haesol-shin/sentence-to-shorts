"""Caption geometry of the builtin templates: bubble placement, text area and fit answers."""

from __future__ import annotations

import pytest

from app.caption_layout import (
    BUBBLE_OUTSET,
    PLATE_SIDE_PAD,
    POSITIONS,
    SAFE_BOTTOM,
    SAFE_TOP,
    bubble_box,
    caption_text_size,
    inside,
    safe_area,
    single_caption_fits,
)
from app.plugins.registry import Registry
from app.schemas.settings import CaptionPosition
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
