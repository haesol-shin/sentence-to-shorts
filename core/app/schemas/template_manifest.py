"""Template manifest: a layout that returns one RGBA layer per scene."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.common import (
    Box,
    CaptionMode,
    CatalogId,
    ContractModel,
    Digest,
    LocalizedText,
    PackageOrigin,
    PackageStatus,
    Point,
    Provenance,
    RelPath,
)
from app.schemas.scene import PlacementAnchor


class TemplateBuiltinRenderer(ContractModel):
    kind: Literal["builtin"]
    module: CatalogId


class TemplateSandboxRenderer(ContractModel):
    kind: Literal["sandbox"]
    program: RelPath
    program_digest: Digest
    runtime_digest: Digest
    entry: Literal["render_layer"]
    max_ms_per_scene: Annotated[int, Field(ge=100, le=20000)]


TemplateRenderer = Annotated[
    TemplateBuiltinRenderer | TemplateSandboxRenderer, Field(discriminator="kind")
]


class Regions(ContractModel):
    """caption must stay inside the vertical safe area checked by the registry validator."""

    title: Box | None
    progress: Box | None
    visual: Box
    caption: Box


class CharacterAnchors(ContractModel):
    """Feet points of a three by three grid over the visual area.

    The unprefixed points are the bottom row that saved scenes use. A template
    written before the upper rows existed leaves those points empty, and an
    empty point is drawn at the same column of the bottom row.
    """

    left: Point
    center: Point
    right: Point
    middle_left: Point | None = None
    middle_center: Point | None = None
    middle_right: Point | None = None
    top_left: Point | None = None
    top_center: Point | None = None
    top_right: Point | None = None

    def point(self, anchor: PlacementAnchor) -> Point:
        point = getattr(self, anchor.value)
        if point is not None:
            return point
        return getattr(self, anchor.value.rsplit("_", 1)[-1])


class TemplateTest(ContractModel):
    scene: RelPath
    layer_digest: Digest | None


class TemplateManifest(ContractModel):
    """A template package.

    ``picture`` is where the background and a framed template's frame are drawn. The
    scene content (character, elements) is laid out in ``regions.visual``, so a picture
    taller than the visual region lets the background run on below the content without
    growing the character. ``None`` draws the picture in the visual region, as templates
    written before this field did.
    """

    schema_version: Literal[1]
    api_version: Literal[1]
    id: CatalogId
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    label: LocalizedText
    origin: PackageOrigin
    status: PackageStatus
    renderer: TemplateRenderer
    regions: Regions
    picture: Box | None = None
    character_anchors: CharacterAnchors
    caption_modes: Annotated[
        list[CaptionMode], Field(min_length=1, json_schema_extra={"uniqueItems": True})
    ]
    dialog_box: bool
    test: TemplateTest
    provenance: Provenance | None

    @model_validator(mode="after")
    def _check_picture(self) -> TemplateManifest:
        picture, visual = self.picture, self.regions.visual
        if picture is not None and not (
            picture.x <= visual.x
            and picture.y <= visual.y
            and visual.x + visual.w <= picture.x + picture.w
            and visual.y + visual.h <= picture.y + picture.h
        ):
            raise ValueError("picture must contain the visual region")
        return self
