"""Format cards and story structures stored as catalog data files."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from app.schemas.common import (
    CaptionMode,
    CatalogId,
    CharacterRole,
    ContractModel,
    LocalizedText,
    Mood,
)
from app.schemas.settings import Humor, ProgressMode, Register


class SceneCountRecommends(ContractModel):
    short_30: Annotated[int, Field(alias="30", ge=3, le=20)]
    minute_60: Annotated[int, Field(alias="60", ge=3, le=20)]
    minutes_120: Annotated[int, Field(alias="120", ge=3, le=20)]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CardFills(ContractModel):
    story_structure: CatalogId
    layout: CatalogId
    character_role: CharacterRole
    register_value: Annotated[Register, Field(alias="register")]
    humor: Humor

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CardRecommends(ContractModel):
    progress_mode: ProgressMode
    caption_mode: CaptionMode
    bgm_mood: Mood
    scene_count: SceneCountRecommends


class FormatCard(ContractModel):
    """Data file core/app/catalog/format_cards/<id>.json.

    fills are card values; recommends never overwrite user values.
    """

    schema_version: Literal[1]
    id: CatalogId
    label: LocalizedText
    example: LocalizedText
    fills: CardFills
    recommends: CardRecommends


class Beat(ContractModel):
    beat_id: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,24}$")]
    label: LocalizedText


class StoryStructure(ContractModel):
    schema_version: Literal[1]
    id: CatalogId
    label: LocalizedText
    beats: Annotated[list[Beat], Field(min_length=2, max_length=12)]
