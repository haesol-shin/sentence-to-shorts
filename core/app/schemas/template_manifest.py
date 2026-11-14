"""Template manifest: a layout that returns one RGBA layer per scene."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

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
    left: Point
    center: Point
    right: Point


class TemplateTest(ContractModel):
    scene: RelPath
    layer_digest: Digest | None


class TemplateManifest(ContractModel):
    schema_version: Literal[1]
    api_version: Literal[1]
    id: CatalogId
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    label: LocalizedText
    origin: PackageOrigin
    status: PackageStatus
    renderer: TemplateRenderer
    regions: Regions
    character_anchors: CharacterAnchors
    caption_modes: Annotated[
        list[CaptionMode], Field(min_length=1, json_schema_extra={"uniqueItems": True})
    ]
    dialog_box: bool
    test: TemplateTest
    provenance: Provenance | None
