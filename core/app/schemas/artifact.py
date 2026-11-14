"""Artifact index rows and the timing artifact read by preview and mp4."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field
from typing_extensions import TypedDict

from app.schemas.common import (
    ArtifactRef,
    CaptionMode,
    ContractModel,
    Digest,
    EntityId,
    PinnedRef,
    RelPath,
    Timestamp,
)


class ArtifactKind(StrEnum):
    still_png = "still_png"
    part_png = "part_png"
    layer_png = "layer_png"
    tts_wav = "tts_wav"
    timing_json = "timing_json"
    clip_mp4 = "clip_mp4"
    mix_wav = "mix_wav"
    final_mp4 = "final_mp4"
    srt = "srt"
    bgm_wav = "bgm_wav"
    ref_frame_png = "ref_frame_png"
    ref_audio_wav = "ref_audio_wav"


class ArtifactRoot(StrEnum):
    data = "data"
    cache = "cache"


class MediaMeta(TypedDict, total=False):
    width: Annotated[int, Field(ge=1, le=4096)]
    height: Annotated[int, Field(ge=1, le=4096)]
    duration_ms: Annotated[int, Field(ge=0)]
    fps: Literal[30]
    sample_rate: Annotated[int, Field(ge=8000, le=48000)]
    channels: Literal[1, 2]


class Artifact(ContractModel):
    id: EntityId
    kind: ArtifactKind
    digest: Digest
    bytes: Annotated[int, Field(ge=1)]
    cache_key: Digest
    root: ArtifactRoot
    path: RelPath
    created_at: Timestamp
    job_id: EntityId | None
    media: MediaMeta


class CaptionPhrase(ContractModel):
    start_char: Annotated[int, Field(ge=0)]
    end_char: Annotated[int, Field(ge=1)]
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(ge=1)]


class AlignFallback(StrEnum):
    align_failed = "align_failed"
    align_low_confidence = "align_low_confidence"
    align_missing_words = "align_missing_words"
    align_unavailable = "align_unavailable"


class TimingCaption(ContractModel):
    mode_used: CaptionMode
    fallback_reason: AlignFallback | None
    phrases: list[CaptionPhrase]


class TimingLine(ContractModel):
    line_id: EntityId
    tts: ArtifactRef
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(ge=1)]
    speech_ms: Annotated[int, Field(ge=1)]
    caption: TimingCaption


class Timing(ContractModel):
    """timing_json artifact. Times are integer milliseconds from scene start."""

    schema_version: Literal[1]
    scene_id: EntityId
    voice: PinnedRef
    duration_ms: Annotated[int, Field(ge=1)]
    lines: Annotated[list[TimingLine], Field(min_length=1)]
