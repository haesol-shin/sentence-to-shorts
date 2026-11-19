"""Caption language catalog row: one language and the font script it needs."""

from __future__ import annotations

from typing import Literal

from app.schemas.common import CatalogId, ContractModel, LocalizedText
from app.schemas.font_manifest import FontScript


class CaptionLanguageManifest(ContractModel):
    """Data file core/app/catalog/caption_languages/<id>.json."""

    schema_version: Literal[1]
    id: CatalogId
    label: LocalizedText
    script: FontScript
