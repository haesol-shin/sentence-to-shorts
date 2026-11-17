"""Ledger reads: unknown prices stay null and rounding happens once per line."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.jobs import LIGHT, SqliteJobStore
from app.schemas.api import Metrics
from app.schemas.job import Effort, JobKind, Stage, Usage
from app.schemas.usage import UsageEvent
from app.storage.sqlite import Database
from app.storage.usage import PriceTable, SqliteUsageReader, TokenPrice
from tests.jobs.support import DEADLINES, new_job

VIDEO = "v_0hzb7bexv28termtt2ypc6trzt"


def _event(job_id: str, attempt: int, call_seq: int) -> UsageEvent:
    return UsageEvent(
        id=f"{job_id}:{attempt}:{call_seq}:0",
        owner_id="owner",
        occurred_at=datetime.now(UTC),
        job_id=job_id,
        attempt=attempt,
        call_seq=call_seq,
        try_index=0,
        stage=Stage.llm_draft,
        provider="fixture",
        model="fixture",
        credential_id=None,
        input_tokens=1,
        output_tokens=None,
        cache_read_tokens=None,
        cache_write_tokens=None,
        outcome="ok",
        price_version="test",
    )


def _job(db: Database):
    store = SqliteJobStore(db, deadlines_s=DEADLINES)
    store.create(new_job(JobKind.draft, video_id=VIDEO))
    claimed = store.claim(LIGHT)
    assert claimed is not None
    return store, claimed


def test_unknown_price_is_null_not_zero(db: Database) -> None:
    store, job = _job(db)
    event = _event(job.id, job.attempt, 1)
    store.usage_event(job.id, job.attempt, event.model_dump(mode="json"))
    reader = SqliteUsageReader(db, PriceTable(version="test", llm={}))
    assert reader.video_cost("owner", VIDEO) is None


def test_cost_rounds_once_per_line(db: Database) -> None:
    store, job = _job(db)
    for call_seq in (1, 2):
        event = _event(job.id, job.attempt, call_seq)
        store.usage_event(job.id, job.attempt, event.model_dump(mode="json"))
    prices = PriceTable(
        version="test",
        llm={
            ("fixture", "fixture"): TokenPrice(
                input=1_500_000, output=None, cache_read=None, cache_write=None
            )
        },
    )
    reader = SqliteUsageReader(db, prices)
    # Two tokens at 1.5 micro USD each: one rounding on the two-token line gives
    # 3, while rounding each event first would give 4.
    assert reader.video_cost("owner", VIDEO) == 3


def test_usage_rejects_float_cost() -> None:
    with pytest.raises(ValidationError):
        Usage(
            stage=Stage.llm_draft,
            provider="fixture",
            model="fixture",
            effort=Effort.low,
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=None,
            cache_write_tokens=None,
            cost_usd=0.5,  # type: ignore[call-arg]
            wall_ms=1,
            retries=0,
        )
    with pytest.raises(ValidationError):
        Metrics(
            active_ms=0,
            waiting_ms=0,
            job_wall_ms=0,
            input_tokens=None,
            output_tokens=None,
            cost_micro_usd=1.5,
            regenerated_scene_ids=[],
        )
