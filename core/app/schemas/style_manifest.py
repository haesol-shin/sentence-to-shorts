"""Art style package manifest: builtin pixel style and generated packages."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.common import (
    HEX_COLOR_PATTERN,
    AssetRelPath,
    CaptionMode,
    CatalogId,
    CharacterRole,
    ContractModel,
    Digest,
    HexColor,
    License,
    LocalizedText,
    PackageOrigin,
    PackageStatus,
    PinnedRef,
    Provenance,
    RelPath,
)

MAX_SPRITE_GRID = 512
"""Cells a side in a stored sprite grid. The encoder and the renderer share it."""


class RenderScale(StrEnum):
    nearest = "nearest"
    smooth = "smooth"


class AssetKind(StrEnum):
    part = "part"
    expression = "expression"
    pose = "pose"
    background = "background"
    skin = "skin"
    icon = "icon"


class SlotName(StrEnum):
    body = "body"
    face = "face"
    hair = "hair"
    hat = "hat"
    outfit = "outfit"
    prop = "prop"


class BuiltinRenderer(ContractModel):
    kind: Literal["builtin"]
    module: CatalogId


class SandboxRenderer(ContractModel):
    kind: Literal["sandbox"]
    program: RelPath
    program_digest: Digest
    runtime_digest: Digest
    entry: Literal["build_assets"]


Renderer = Annotated[BuiltinRenderer | SandboxRenderer, Field(discriminator="kind")]


class Canvas(ContractModel):
    width: Annotated[int, Field(ge=90, le=1080)]
    height: Annotated[int, Field(ge=160, le=1920)]
    scale: RenderScale


class RigSlots(ContractModel):
    body: Annotated[list[CatalogId], Field(min_length=1)]
    face: Annotated[list[CatalogId], Field(min_length=1)]
    hair: list[CatalogId]
    hat: list[CatalogId]
    outfit: list[CatalogId]
    prop: list[CatalogId]


class Compat(ContractModel):
    asset_id: CatalogId
    body_ids: Annotated[list[CatalogId], Field(min_length=1)]


class Rig(ContractModel):
    slots: RigSlots
    expressions: Annotated[list[CatalogId], Field(min_length=1)]
    poses: Annotated[list[CatalogId], Field(min_length=1)]
    compat: list[Compat]


class Palette(ContractModel):
    """Theme colours. The five required keys are fixed; up to 11 extra keys are allowed."""

    bg: HexColor
    ink: HexColor
    accent: HexColor
    caption_text: HexColor
    caption_box: HexColor
    model_config = ConfigDict(extra="allow", json_schema_extra={"maxProperties": 16})

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):  # type: ignore[no-untyped-def]
        schema = handler(core_schema)
        schema.update(
            {
                "additionalProperties": False,
                "patternProperties": {
                    r"^[a-z_]{1,24}$": {
                        "type": "string",
                        "pattern": HEX_COLOR_PATTERN,
                    }
                },
            }
        )
        return schema

    @model_validator(mode="after")
    def _check_extra_colors(self) -> Palette:
        extras = self.model_extra or {}
        if len(extras) > 11:
            raise ValueError("palette allows at most 16 colours")
        for key, value in extras.items():
            if not re.fullmatch(r"[a-z_]{1,24}", key):
                raise ValueError(f"palette key {key} is not a colour name")
            if not isinstance(value, str) or not re.fullmatch(HEX_COLOR_PATTERN, value):
                raise ValueError(f"palette value for {key} is not a hex colour")
        return self


class Theme(ContractModel):
    id: CatalogId
    label: LocalizedText
    palette: Palette
    skin_id: CatalogId
    backgrounds: Annotated[list[CatalogId], Field(min_length=1, max_length=6)]


class StyleAsset(ContractModel):
    id: CatalogId
    kind: AssetKind
    slot: SlotName | None
    file: AssetRelPath
    sha256: Digest
    license_id: CatalogId


class Capabilities(ContractModel):
    layouts: Annotated[list[CatalogId], Field(min_length=1)]
    caption_modes: Annotated[list[CaptionMode], Field(min_length=1)]
    character_roles: Annotated[list[CharacterRole], Field(min_length=1)]


class StyleManifest(ContractModel):
    schema_version: Literal[1]
    api_version: Literal[1]
    id: CatalogId
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    label: LocalizedText
    origin: PackageOrigin
    status: PackageStatus
    extends: PinnedRef | None
    renderer: Renderer
    canvas: Canvas
    rig: Rig
    themes: Annotated[list[Theme], Field(min_length=1, max_length=6)]
    assets: Annotated[list[StyleAsset], Field(max_length=400)]
    fonts: Annotated[list[CatalogId], Field(min_length=1, max_length=3)]
    capabilities: Capabilities
    licenses: dict[CatalogId, License]
    provenance: Provenance | None
    preview: RelPath | None
