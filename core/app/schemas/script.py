"""Script metadata and the line model owned by a scene."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.schemas.common import ContractModel, EntityId


class ScriptSource(StrEnum):
    user = "user"
    llm = "llm"


class Speaker(StrEnum):
    narrator = "narrator"
    character = "character"


class Span(ContractModel):
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=1)]


class Line(ContractModel):
    id: EntityId
    display_text: Annotated[str, Field(min_length=1, max_length=300)]
    speech_text: Annotated[str, Field(min_length=1, max_length=500)]
    speaker: Speaker
    highlight: Annotated[list[Span], Field(max_length=4)]


class Script(ContractModel):
    source: ScriptSource
    raw_text: Annotated[str, Field(max_length=20000)] | None
    title: Annotated[str, Field(min_length=1, max_length=80)] | None
