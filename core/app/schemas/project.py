"""A project groups videos made with the same settings."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ContractModel, EntityId, OwnerId, Timestamp
from app.schemas.settings import Settings


class Project(ContractModel):
    schema_version: Literal[1]
    id: EntityId
    owner_id: OwnerId
    title: Annotated[str, Field(min_length=1, max_length=80)]
    created_at: Timestamp
    updated_at: Timestamp
    defaults: Settings
    video_ids: Annotated[
        list[EntityId], Field(max_length=500, json_schema_extra={"uniqueItems": True})
    ]
