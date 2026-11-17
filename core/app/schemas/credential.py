"""Owner credentials: metadata of one key slot per owner and provider."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.schemas.api import LlmAdapter
from app.schemas.common import ContractModel, EntityId, Timestamp


class CredentialInfo(ContractModel):
    """A stored key's metadata. The secret itself never leaves the vault."""

    id: EntityId
    provider: LlmAdapter
    label: Annotated[str, Field(max_length=40)] | None
    last4: Annotated[str, Field(pattern=r"^.{4}$")]
    created_at: Timestamp
    last_used_at: Timestamp | None


__all__ = ["CredentialInfo"]
