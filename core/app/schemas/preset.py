"""Saved format. Created only by an explicit user action."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ContractModel, EntityId, OwnerId, Timestamp
from app.schemas.settings import PresetSettings
from app.schemas.video import DerivedFrom


class Preset(ContractModel):
    schema_version: Literal[1]
    id: EntityId
    owner_id: OwnerId
    project_id: EntityId
    name: Annotated[str, Field(min_length=1, max_length=60)]
    created_at: Timestamp
    from_video: DerivedFrom | None
    settings: PresetSettings
