"""BGM entries and sound effects, stored as catalog manifests."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import (
    BgmRelPath,
    CatalogId,
    ContractModel,
    Digest,
    EntityId,
    License,
    LocalizedText,
    Mood,
    OwnerId,
    Provenance,
    RelPath,
    Timestamp,
    WavRelPath,
)


class BgmSource(StrEnum):
    builtin = "builtin"
    upload = "upload"
    code = "code"


class BgmCommon(ContractModel):
    schema_version: Literal[1]
    id: CatalogId
    label: LocalizedText
    mood: Mood
    file: WavRelPath
    sha256: Digest
    duration_ms: Annotated[int, Field(ge=500, le=600000)]
    sample_rate: Literal[44100, 48000]
    channels: Literal[1, 2]
    loudness_lufs_x10: Annotated[int, Field(ge=-700, le=0)] | None
    true_peak_dbtp_x10: Annotated[int, Field(ge=-1000, le=0)] | None


class ReviewStatus(StrEnum):
    verified = "verified"
    pending = "pending"


class BuiltinBgm(BgmCommon):
    source: Literal["builtin"]
    file: BgmRelPath
    true_peak_dbtp_x10: Annotated[int, Field(ge=-1000, le=100)] | None
    license: License
    review_status: ReviewStatus


class UploadBgm(BgmCommon):
    source: Literal["upload"]
    owner_id: OwnerId
    project_id: EntityId
    upload_id: EntityId
    original_bytes: Annotated[int, Field(ge=1)]
    accepted_at: Timestamp


class BgmParams(ContractModel):
    bpm: Annotated[int, Field(ge=60, le=180)]
    bars: Annotated[int, Field(ge=1, le=16)]
    mood: Mood


class CodeBgm(BgmCommon):
    source: Literal["code"]
    sample_rate: Literal[44100]
    channels: Literal[1]
    duration_ms: Annotated[int, Field(ge=500, le=16000)]
    program: RelPath
    program_digest: Digest
    runtime_digest: Digest
    seed: Annotated[int, Field(ge=0, le=2147483647)]
    params: BgmParams
    provenance: Provenance


BgmEntry = Annotated[BuiltinBgm | UploadBgm | CodeBgm, Field(discriminator="source")]


class SfxKind(StrEnum):
    whoosh = "whoosh"
    pop = "pop"
    ding = "ding"
    click = "click"
    typing = "typing"
    impact = "impact"
    riser = "riser"


class SfxEntry(ContractModel):
    """One effect sound. A typing kind here is a legacy document, not a new cue."""

    schema_version: Literal[1]
    id: CatalogId
    label: LocalizedText
    kind: SfxKind
    file: WavRelPath
    sha256: Digest
    duration_ms: Annotated[int, Field(ge=20, le=5000)]
    license: License


class KeySound(ContractModel):
    """One key press of a typing sound entry."""

    file: WavRelPath
    sha256: Digest
    duration_ms: Annotated[int, Field(ge=20, le=1000)]


class TypingSoundEntry(ContractModel):
    """A set of key presses for typewriter captions. The ``keys`` member is the
    discriminator that keeps legacy ``SfxEntry`` manifests readable."""

    schema_version: Literal[1]
    id: CatalogId
    label: LocalizedText
    kind: Literal["typing"]
    keys: Annotated[list[KeySound], Field(min_length=1, max_length=64)]
    license: License
