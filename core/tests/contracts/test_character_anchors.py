"""Character positions: the nine grid values and the points that render them."""

from __future__ import annotations

import pytest

from app.schemas.scene import Placement, PlacementAnchor
from app.schemas.template_manifest import CharacterAnchors

PLACEMENT = {
    "expression_id": "expr_happy",
    "pose_id": "pose_idle",
    "motion": "none",
}
BOTTOM = {
    "left": {"x": 270, "y": 960},
    "center": {"x": 540, "y": 960},
    "right": {"x": 810, "y": 960},
}


@pytest.mark.parametrize("anchor", [anchor.value for anchor in PlacementAnchor])
def test_29_every_grid_value_validates_as_a_placement(anchor: str) -> None:
    placement = Placement.model_validate({**PLACEMENT, "anchor": anchor})
    assert placement.anchor.value == anchor


def test_29_template_without_upper_anchors_draws_on_its_bottom_row() -> None:
    anchors = CharacterAnchors.model_validate(BOTTOM)
    for anchor in PlacementAnchor:
        column = anchor.value.rsplit("_", 1)[-1]
        assert anchors.point(anchor) == getattr(anchors, column)
