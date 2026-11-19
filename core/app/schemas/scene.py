"""Source data of one scene. Build results live in the artifact index, not here."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.schemas.common import CatalogId, ContractModel, EntityId, PinnedRef
from app.schemas.script import Line


class ElementKind(StrEnum):
    label = "label"
    code = "code"
    asset = "asset"
    material = "material"


class Anchor(StrEnum):
    left = "left"
    center = "center"
    right = "right"
    top = "top"
    bottom = "bottom"


class PlacementAnchor(StrEnum):
    """Feet point of the character on a three by three grid over the visual area.

    The unprefixed values are the bottom row that saved scenes use. The middle
    and top prefixes lift the character above that row.
    """

    top_left = "top_left"
    top_center = "top_center"
    top_right = "top_right"
    middle_left = "middle_left"
    middle_center = "middle_center"
    middle_right = "middle_right"
    left = "left"
    center = "center"
    right = "right"


class SceneMotion(StrEnum):
    none = "none"
    pop = "pop"
    bob = "bob"
    move = "move"


class CueAt(StrEnum):
    start = "start"
    end = "end"


class TransitionIn(StrEnum):
    cut = "cut"
    fade = "fade"


class Placement(ContractModel):
    anchor: PlacementAnchor
    expression_id: CatalogId
    pose_id: CatalogId
    motion: SceneMotion


class Element(ContractModel):
    id: EntityId
    kind: ElementKind
    value: Annotated[str, Field(min_length=1, max_length=300)]
    anchor: Anchor
    reveal_line_id: EntityId | None


class SfxCue(ContractModel):
    sfx_id: PinnedRef
    line_id: EntityId
    at: CueAt
    offset_ms: Annotated[int, Field(ge=-500, le=2000)]


class SceneVisual(ContractModel):
    background_id: CatalogId
    characters: Annotated[list[Placement], Field(max_length=1)]
    elements: Annotated[list[Element], Field(max_length=6)]
    sfx: Annotated[list[SfxCue], Field(max_length=2)]
    transition_in: TransitionIn


class Scene(ContractModel):
    id: EntityId
    beat_id: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,24}$")]
    beat_label: Annotated[str, Field(min_length=1, max_length=40)]
    lines: Annotated[list[Line], Field(min_length=1, max_length=4)]
    visual: SceneVisual | None
