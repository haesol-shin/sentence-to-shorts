"""Ledger of provider requests: one row per request, including failed ones."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ContractModel, EntityId, OwnerId, Timestamp
from app.schemas.job import Stage

UsageOutcome = Literal["ok", "failed"]


class UsageEvent(ContractModel):
    """One provider request. Tokens are normalized by the adapter that sent it.

    `input_tokens` excludes cache reads and cache writes. A value the provider
    did not report is None, never 0. Cost is not stored; it is computed from the
    price table when events are summed.
    """

    id: Annotated[str, Field(min_length=1, max_length=96)]
    owner_id: OwnerId
    occurred_at: Timestamp
    job_id: EntityId
    attempt: Annotated[int, Field(ge=1)]
    call_seq: Annotated[int, Field(ge=1)]
    try_index: Annotated[int, Field(ge=0)]
    stage: Stage
    provider: Annotated[str, Field(max_length=40)]
    model: Annotated[str, Field(max_length=80)] | None
    credential_id: Annotated[str, Field(max_length=64)] | None
    input_tokens: Annotated[int, Field(ge=0)] | None
    output_tokens: Annotated[int, Field(ge=0)] | None
    cache_read_tokens: Annotated[int, Field(ge=0)] | None
    cache_write_tokens: Annotated[int, Field(ge=0)] | None
    outcome: UsageOutcome
    price_version: Annotated[str, Field(max_length=32)] | None


class UsagePage(ContractModel):
    """One page of usage events, newest last, with an opaque continuation cursor."""

    items: list[UsageEvent]
    next_cursor: str | None


__all__ = ["UsageEvent", "UsageOutcome", "UsagePage"]
