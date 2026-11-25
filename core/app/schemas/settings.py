"""Production settings shared by project defaults, video snapshots and presets."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.common import (
    CaptionMode,
    CatalogId,
    CharacterRole,
    ContractModel,
    Language,
    Mood,
    Origin,
    PinnedRef,
)


class Register(StrEnum):
    friendly = "friendly"
    neutral = "neutral"
    casual = "casual"


class Humor(StrEnum):
    none = "none"
    light = "light"


class ProgressMode(StrEnum):
    numbered = "numbered"
    phases = "phases"
    none = "none"


class Transition(StrEnum):
    cut = "cut"
    fade = "fade"


class CharacterMotion(StrEnum):
    none = "none"
    pop = "pop"
    bob = "bob"


class CaptionPosition(StrEnum):
    top = "top"
    upper = "upper"
    middle = "middle"
    lower = "lower"
    bottom = "bottom"


class CaptionPlace(ContractModel):
    """A caption plate in frame pixels, read from a reference video or picked by hand.

    ``y`` is the top of the plate, not of the text. The saved value stays inside
    the place area; the store clamps a write before this model validates it, so
    the checks here are the safety net for other write paths.
    """

    y: Annotated[int, Field(ge=288)]
    x: Annotated[int, Field(ge=48)]
    w: Annotated[int, Field(ge=120)]
    align: Literal["left", "center", "right"] = "center"

    @model_validator(mode="after")
    def _fits_width(self) -> "CaptionPlace":
        if self.x + self.w > 888:
            raise ValueError("place x + w exceeds 888")
        return self


class Format(ContractModel):
    card_id: CatalogId | None
    story_structure: CatalogId
    layout: PinnedRef
    character_role: CharacterRole
    register_value: Annotated[Register, Field(alias="register")]
    humor: Humor
    progress_mode: ProgressMode
    scene_count: Annotated[int, Field(ge=3, le=20)]

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CharacterSlots(ContractModel):
    body: CatalogId
    face: CatalogId
    hair: CatalogId | None
    hat: CatalogId | None
    outfit: CatalogId | None
    prop: CatalogId | None


class CharacterSpec(ContractModel):
    """Concrete part combination. Null when character_role is none."""

    preset_id: CatalogId | None
    slots: CharacterSlots


class Visual(ContractModel):
    art_style: PinnedRef
    theme_id: CatalogId
    character: CharacterSpec | None


class BgmSettings(ContractModel):
    enabled: bool
    mood: Mood
    entry: PinnedRef | None
    gain_db_x10: Annotated[int, Field(ge=-400, le=0)]
    ducking: bool


class Audio(ContractModel):
    voice: PinnedRef
    bgm: BgmSettings
    sfx_enabled: bool


class CaptionLayer(ContractModel):
    """A second caption language drawn in the same safe band as the primary."""

    language: CatalogId
    mode: CaptionMode
    font_id: PinnedRef
    position: CaptionPosition


class Caption(ContractModel):
    mode: CaptionMode
    font_id: PinnedRef
    position: CaptionPosition
    highlight: bool
    typing_sound: PinnedRef | None = None
    place: CaptionPlace | None = None
    extra: Annotated[list[CaptionLayer], Field(max_length=1)] = Field(
        default_factory=list
    )


class Motion(ContractModel):
    transition: Transition
    character_motion: CharacterMotion


class LockKey(StrEnum):
    story_structure = "story_structure"
    layout = "layout"
    character_role = "character_role"
    register = "register"
    humor = "humor"
    art_style = "art_style"
    theme = "theme"
    character = "character"
    voice = "voice"
    bgm = "bgm"
    caption_mode = "caption_mode"
    caption_font = "caption_font"
    background = "background"
    transition = "transition"


class LockState(StrEnum):
    locked = "locked"
    varied = "varied"


ORIGIN_POINTER_PATTERN = (
    r"^/(language|target_duration_s|format|visual|audio|caption|motion)(/[a-z_]+)*$"
)

ORIGIN_RANK: dict[Origin, int] = {
    Origin.user: 5,
    Origin.reference: 4,
    Origin.preset: 3,
    Origin.card: 2,
    Origin.llm: 1,
    Origin.default: 0,
    Origin.derived: 0,
}


def higher_origin_pointers(
    origins: Mapping[str, Origin | str], pointer: str, incoming: Origin
) -> list[str]:
    """Higher-origin settings pointers equal to, containing or contained by a write.

    Pointers are relative to settings. Slash boundaries keep sibling field names
    distinct; sorting preserves the project guard's restoration order.
    """
    rank = ORIGIN_RANK[incoming]
    return sorted(
        key for key, value in origins.items()
        if (key == pointer or key.startswith(pointer + "/") or pointer.startswith(key + "/"))
        and ORIGIN_RANK[Origin(value)] > rank
    )


LockMap = dict[LockKey, LockState]
OriginMap = Annotated[
    dict[Annotated[str, Field(pattern=ORIGIN_POINTER_PATTERN)], Origin],
    Field(json_schema_extra={"additionalProperties": False}),
]
ExtraInstructions = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=20)
]


class Settings(ContractModel):
    language: Language
    target_duration_s: Literal[30, 60, 120]
    format: Format
    visual: Visual
    audio: Audio
    caption: Caption
    motion: Motion
    locks: LockMap
    origins: OriginMap
    extra_instructions: ExtraInstructions


class PresetCaption(ContractModel):
    """Primary caption a preset stores. The extra language layer is not saved."""

    mode: CaptionMode
    font_id: PinnedRef
    position: CaptionPosition
    highlight: bool
    typing_sound: PinnedRef | None = None
    place: CaptionPlace | None = None


class PresetSettings(ContractModel):
    """Settings saved in a preset. Language, length, topic, script and results are not saved."""

    format: Format
    visual: Visual
    audio: Audio
    caption: PresetCaption
    motion: Motion
    locks: LockMap
    extra_instructions: ExtraInstructions
