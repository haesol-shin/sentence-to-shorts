"""Shared contract definitions: ids, digests, localized text and package licences."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final

from pydantic import AfterValidator, AnyUrl, BaseModel, ConfigDict, Field
from typing_extensions import TypeAliasType

TYPEID_PATTERN = r"^[a-z]{1,2}_[0-7][0-9a-hjkmnp-tv-z]{25}$"
"""TypeID: app prefix, underscore, 26 lowercase Crockford base32 characters of a UUIDv7."""

CATALOG_ID_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,47}$"
DIGEST_PATTERN = r"^[0-9a-f]{64}$"
REL_PATH_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,127}$"
REL_PATH_NOT = {"not": {"pattern": r"\.\.|//"}}
"""JSON Schema mirror of the parent and double-slash checks in _safe_relative."""
HEX_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return value


def _safe_relative(value: str) -> str:
    if ".." in value or "//" in value:
        raise ValueError("relative path must not contain a parent or double-slash segment")
    return value


class ContractModel(BaseModel):
    """Base for every contract object. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


EntityId = TypeAliasType(
    "EntityId",
    Annotated[
        str,
        Field(
            pattern=TYPEID_PATTERN,
            description=(
                "App-issued id. Prefix p project, v video, s scene, l line, e element, "
                "c change, j job, a artifact, u upload, ps preset, rf reference."
            ),
        ),
    ],
)
CatalogId = TypeAliasType(
    "CatalogId",
    Annotated[
        str,
        Field(
            pattern=CATALOG_ID_PATTERN,
            description="Registry id of a catalog item. Validated by registry lookup.",
        ),
    ],
)
Digest = TypeAliasType(
    "Digest",
    Annotated[str, Field(pattern=DIGEST_PATTERN, description="Lowercase SHA-256 hex.")],
)
Timestamp = TypeAliasType(
    "Timestamp",
    Annotated[
        datetime,
        Field(description="ISO 8601 date-time with a timezone."),
        AfterValidator(_aware),
    ],
)
RelPath = TypeAliasType(
    "RelPath",
    Annotated[
        str,
        Field(
            pattern=REL_PATH_PATTERN,
            json_schema_extra=REL_PATH_NOT,
            description=(
                "Relative path inside a package or data root. No absolute path, "
                "no parent segment, no backslash."
            ),
        ),
        AfterValidator(_safe_relative),
    ],
)
WavRelPath = TypeAliasType(
    "WavRelPath",
    Annotated[
        str,
        Field(
            pattern=rf"^{REL_PATH_PATTERN[1:-1]}\.wav$",
            json_schema_extra=REL_PATH_NOT,
        ),
        AfterValidator(_safe_relative),
    ],
)
BgmRelPath = TypeAliasType(
    "BgmRelPath",
    Annotated[
        str,
        Field(
            pattern=rf"^{REL_PATH_PATTERN[1:-1]}\.(wav|ogg)$",
            json_schema_extra=REL_PATH_NOT,
        ),
        AfterValidator(_safe_relative),
    ],
)
AssetRelPath = TypeAliasType(
    "AssetRelPath",
    Annotated[
        str,
        Field(
            pattern=rf"^{REL_PATH_PATTERN[1:-1]}\.(png|json)$",
            json_schema_extra=REL_PATH_NOT,
        ),
        AfterValidator(_safe_relative),
    ],
)
FontRelPath = TypeAliasType(
    "FontRelPath",
    Annotated[
        str,
        Field(
            pattern=rf"^{REL_PATH_PATTERN[1:-1]}\.(ttf|otf)$",
            json_schema_extra=REL_PATH_NOT,
        ),
        AfterValidator(_safe_relative),
    ],
)
HexColor = TypeAliasType("HexColor", Annotated[str, Field(pattern=HEX_COLOR_PATTERN)])


class Language(StrEnum):
    ko = "ko"
    en = "en"


class Origin(StrEnum):
    """Where a value came from. Precedence: user > reference > preset > card > llm > default."""

    user = "user"
    reference = "reference"
    preset = "preset"
    card = "card"
    llm = "llm"
    default = "default"
    derived = "derived"


class Mood(StrEnum):
    curious = "curious"
    playful = "playful"
    tense = "tense"
    energetic = "energetic"
    calm = "calm"
    reflective = "reflective"


class CaptionMode(StrEnum):
    sentence = "sentence"
    phrase = "phrase"
    typewriter = "typewriter"


class CharacterRole(StrEnum):
    none = "none"
    presenter = "presenter"
    subject = "subject"


class PackageOrigin(StrEnum):
    builtin = "builtin"
    user = "user"
    generated = "generated"


class PackageStatus(StrEnum):
    """Generated packages move draft -> validated -> ready. Only ready is listed."""

    draft = "draft"
    validated = "validated"
    ready = "ready"


class PinnedRef(ContractModel):
    id: CatalogId
    revision: Digest


class LocalizedText(ContractModel):
    ko: Annotated[str, Field(min_length=1, max_length=200)]
    en: Annotated[str, Field(min_length=1, max_length=200)]


OwnerId = TypeAliasType(
    "OwnerId", Annotated[str, Field(pattern=r"^[a-z0-9_-]{1,32}$")]
)

PERSONAL_OWNER_ID: Final = "owner"
"""The owner of every document in personal mode; the one literal value (CONTRACTS 1.1)."""


class ArtifactRef(ContractModel):
    id: EntityId
    digest: Digest
    cache_key: Digest


class Box(ContractModel):
    """Rectangle in output pixels of the 1080x1920 frame."""

    x: Annotated[int, Field(ge=0, le=1080)]
    y: Annotated[int, Field(ge=0, le=1920)]
    w: Annotated[int, Field(ge=1, le=1080)]
    h: Annotated[int, Field(ge=1, le=1920)]


class Point(ContractModel):
    x: Annotated[int, Field(ge=0, le=1080)]
    y: Annotated[int, Field(ge=0, le=1920)]


class License(ContractModel):
    spdx: Annotated[str, Field(pattern=r"^[A-Za-z0-9.+-]{2,40}$")]
    source_url: Annotated[AnyUrl, Field(max_length=500)]
    author: Annotated[str, Field(min_length=1, max_length=200)]
    commercial_ok: bool
    attribution: LocalizedText | None
    license_file: RelPath


class Provenance(ContractModel):
    """Generated package origin. Never contains prompts, URLs or user text."""

    request_digest: Digest
    parent: PinnedRef | None
    reference_digest: Digest | None
    job_id: EntityId
    provider: Annotated[str, Field(max_length=40)]
    model: Annotated[str, Field(max_length=80)]
