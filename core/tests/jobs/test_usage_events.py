"""The job runner writes one ledger row per provider request."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.jobs import LIGHT, LocalJobContext
from app.ports import ProviderRequest
from app.schemas.job import Job, JobKind, JobState, Stage
from app.schemas.usage import UsageEvent
from tests.jobs.support import Env, new_job, open_env


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


def _request(try_index: int, *, outcome: str = "ok") -> ProviderRequest:
    return ProviderRequest(
        try_index=try_index,
        stage=Stage.llm_draft,
        provider="fixture",
        model="fixture",
        credential_id="k_01jdq7c3v8m4n5p6q7r8s9t0vw",
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=None,
        cache_write_tokens=2,
        outcome=outcome,  # type: ignore[arg-type]
    )


def _event(job_id: str, attempt: int, event_id: str) -> dict:
    return UsageEvent(
        id=event_id,
        owner_id="owner",
        occurred_at=datetime.now(UTC),
        job_id=job_id,
        attempt=attempt,
        call_seq=1,
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
        price_version="2026-11-17",
    ).model_dump(mode="json")


def _rows(env: Env, job: Job) -> list[tuple]:
    with env.db.read() as conn:
        return conn.execute(
            "SELECT id, owner_id, call_seq, try_index, outcome, cache_write_tokens "
            "FROM usage_events WHERE job_id = ? ORDER BY call_seq, try_index",
            (job.id,),
        ).fetchall()


def test_usage_event_per_try(env: Env) -> None:
    job = env.jobs.create(new_job(JobKind.draft))

    def run_job(current: Job, ctx: LocalJobContext) -> dict:
        ctx.record_request(_request(0))
        ctx.record_request(_request(1, outcome="failed"))
        return {}

    finished = env.runner(run_job).run_once(LIGHT)
    assert finished is not None and finished.state is JobState.succeeded
    rows = _rows(env, job)
    assert [(row[0], row[1], row[2], row[3], row[4]) for row in rows] == [
        (f"{job.id}:1:1:0", "owner", 1, 0, "ok"),
        (f"{job.id}:1:1:1", "owner", 1, 1, "failed"),
    ]
    assert rows[0][5] == 2


def test_usage_event_replay_is_idempotent(env: Env) -> None:
    job = env.jobs.create(new_job(JobKind.draft))
    claimed = env.jobs.claim(LIGHT)
    assert claimed is not None
    event = _event(job.id, claimed.attempt, f"{job.id}:1:9:0")
    env.jobs.usage_event(job.id, claimed.attempt, event)
    env.jobs.usage_event(job.id, claimed.attempt, event)
    assert len(_rows(env, job)) == 1
    env.jobs.finish(job.id, claimed.attempt, JobState.succeeded.value, {}, None, False)
    env.jobs.usage_event(job.id, claimed.attempt, event)
    assert len(_rows(env, job)) == 1
