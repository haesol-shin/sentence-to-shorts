"""Caption style package: a sandbox program that draws a plate-local RGBA layer."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import (
    CatalogId,
    ContractModel,
    Digest,
    LocalizedText,
    PackageOrigin,
    PackageStatus,
    RelPath,
)


class CaptionSandboxRenderer(ContractModel):
    kind: Literal["sandbox"]
    program: RelPath
    program_digest: Digest
    runtime_digest: Digest
    entry: Literal["draw_caption_box"]
    max_ms_per_box: Annotated[int, Field(ge=100, le=20000)]


class CaptionTestPlate(ContractModel):
    w: Annotated[int, Field(ge=16, le=1080)]
    h: Annotated[int, Field(ge=16, le=1920)]


class CaptionTest(ContractModel):
    """Calibration plate and SHA-256 of its decoded row-major RGBA bytes."""

    plate: CaptionTestPlate
    layer_digest: Digest


class CaptionStyleManifest(ContractModel):
    schema_version: Literal[1]
    api_version: Literal[1]
    id: CatalogId
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    label: LocalizedText
    origin: PackageOrigin
    status: PackageStatus
    renderer: CaptionSandboxRenderer
    test: CaptionTest
