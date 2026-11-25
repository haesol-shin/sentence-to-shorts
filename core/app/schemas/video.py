"""Immutable video revision snapshot and the derived build view."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import (
    ArtifactRef,
    ContractModel,
    Digest,
    EntityId,
    HexColor,
    LocalizedText,
    OwnerId,
    Timestamp,
)
from app.schemas.scene import Scene
from app.schemas.script import Script
from app.schemas.settings import Settings


class VideoStage(StrEnum):
    draft = "draft"
    concept_confirmed = "concept_confirmed"
    script_confirmed = "script_confirmed"
    scenes_confirmed = "scenes_confirmed"


STAGE_ORDER = (
    VideoStage.draft,
    VideoStage.concept_confirmed,
    VideoStage.script_confirmed,
    VideoStage.scenes_confirmed,
)


def stage_after_script_rewrite(stage: VideoStage) -> VideoStage:
    """A script rewrite clears script and scene gates, never the concept lock."""
    if STAGE_ORDER.index(stage) >= STAGE_ORDER.index(VideoStage.concept_confirmed):
        return VideoStage.concept_confirmed
    return VideoStage.draft


class CreatedBy(StrEnum):
    create = "create"
    next_video = "next_video"
    draft_job = "draft_job"
    change = "change"
    confirm = "confirm"
    undo = "undo"
    system = "system"


class ReferenceKind(StrEnum):
    file = "file"
    link = "link"


class ReferenceHost(StrEnum):
    youtube = "youtube"
    instagram = "instagram"
    tiktok = "tiktok"


class ReferenceStatus(StrEnum):
    analyzed = "analyzed"
    failed = "failed"


class ArtifactState(StrEnum):
    fresh = "fresh"
    stale = "stale"
    missing = "missing"
    building = "building"
    failed = "failed"


class Material(ContractModel):
    id: EntityId
    text: Annotated[str, Field(min_length=1, max_length=20000)]


class DerivedFrom(ContractModel):
    video_id: EntityId
    revision: Annotated[int, Field(ge=1)]


class Measured(ContractModel):
    duration_ms: Annotated[int, Field(ge=0)]
    scene_count: Annotated[int, Field(ge=0)]
    silence_ratio: Annotated[float, Field(ge=0, le=1)]
    has_bgm: bool


MAX_REFERENCE_FRAMES = 4
REFERENCE_FRAME_PATTERN = r"^frame_[0-3]\.png$"
"""Kept frames are named in stored order, so a style job can find them without a path."""


class ReferenceLook(ContractModel):
    """The look kept from a reference so a later style request can copy it."""

    palette: Annotated[list[HexColor], Field(max_length=5)]
    frames: Annotated[
        list[Annotated[str, Field(pattern=REFERENCE_FRAME_PATTERN)]],
        Field(max_length=MAX_REFERENCE_FRAMES),
    ]


class ReferenceSummary(ContractModel):
    """Kept after the source file is deleted. Holds no URL, no frame bytes and no transcript."""

    id: EntityId
    kind: ReferenceKind
    host: ReferenceHost | None
    status: ReferenceStatus
    source_deleted: bool
    measured: Measured | None
    style: ReferenceLook | None


class Video(ContractModel):
    schema_version: Literal[2]
    id: EntityId
    project_id: EntityId
    owner_id: OwnerId
    revision: Annotated[int, Field(ge=1)]
    parent_revision: Annotated[int, Field(ge=1)] | None
    created_at: Timestamp
    created_by: CreatedBy
    change_id: EntityId | None
    stage: VideoStage
    derived_from: DerivedFrom | None
    topic: Annotated[str, Field(max_length=500)]
    material: Annotated[list[Material], Field(max_length=5)]
    reference: ReferenceSummary | None
    settings: Settings
    script: Script | None
    scene_order: Annotated[
        list[EntityId], Field(max_length=30, json_schema_extra={"uniqueItems": True})
    ]
    scenes: Annotated[dict[EntityId, Scene], Field(max_length=30)]


class ArtifactStatus(ContractModel):
    state: ArtifactState
    cache_key: Digest | None
    artifact: ArtifactRef | None
    error_code: Annotated[str, Field(max_length=40)] | None


class SceneBuild(ContractModel):
    still: ArtifactStatus
    tts: dict[EntityId, ArtifactStatus]
    timing: ArtifactStatus
    layer: ArtifactStatus | None
    clip: ArtifactStatus


class VideoBuild(ContractModel):
    """Derived view, never persisted. Computed from cache keys and the artifact index."""

    video_id: EntityId
    revision: Annotated[int, Field(ge=1)]
    scenes: dict[EntityId, SceneBuild]
    mix: ArtifactStatus
    final: ArtifactStatus
    srt: ArtifactStatus
    estimated_ms: Annotated[int, Field(ge=0)]
    actual_ms: Annotated[int, Field(ge=0)] | None
    attribution: list[LocalizedText]


class RevisionInfo(ContractModel):
    revision: Annotated[int, Field(ge=1)]
    created_at: Timestamp
    created_by: CreatedBy
    change_id: EntityId | None
