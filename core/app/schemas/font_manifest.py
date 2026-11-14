"""Caption font manifest. The renderer never falls back to an OS font."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import (
    CatalogId,
    ContractModel,
    Digest,
    FontRelPath,
    License,
    LocalizedText,
)


class FontScript(StrEnum):
    hangul = "hangul"
    latin = "latin"
    digits = "digits"


class FontManifest(ContractModel):
    schema_version: Literal[1]
    id: CatalogId
    label: LocalizedText
    file: FontRelPath
    sha256: Digest
    scripts: Annotated[
        list[FontScript], Field(min_length=1, json_schema_extra={"uniqueItems": True})
    ]
    pixel_size: Annotated[int, Field(ge=6, le=64)] | None
    license: License
