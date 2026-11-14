"""Voice manifest: engine, model revision and speaker settings."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from app.schemas.common import (
    CatalogId,
    ContractModel,
    Digest,
    Language,
    License,
    LocalizedText,
    RelPath,
)


class VoiceModel(ContractModel):
    runtime_item: CatalogId
    repo: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


SPEED_VALUES = tuple(round(hundredths / 100, 2) for hundredths in range(80, 126))


def _speed_step(value: float) -> float:
    if value not in SPEED_VALUES:
        raise ValueError("speed must be one of 0.80 to 1.25 in 0.01 steps")
    return value


class VoiceSettings(ContractModel):
    speed: Annotated[
        float,
        Field(
            ge=0.8,
            le=1.25,
            json_schema_extra={"enum": list(SPEED_VALUES)},
        ),
        AfterValidator(_speed_step),
    ]
    seed: Annotated[int, Field(ge=0, le=2147483647)]


class VoiceOutput(ContractModel):
    sample_rate: Literal[16000, 22050, 24000, 44100, 48000]
    channels: Literal[1]


class VoiceSample(ContractModel):
    file: RelPath
    sha256: Digest


class VoiceManifest(ContractModel):
    schema_version: Literal[1]
    id: CatalogId
    label: LocalizedText
    engine_id: CatalogId
    model: VoiceModel | None
    speaker: Annotated[str, Field(min_length=1, max_length=64)]
    languages: Annotated[
        list[Language], Field(min_length=1, json_schema_extra={"uniqueItems": True})
    ]
    settings: VoiceSettings
    output: VoiceOutput
    sample: VoiceSample
    license: License
    cloning: Literal[False]
