"""Records a job leaves for the owner: usage of a failed job, metrics after a build."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.jobs import LIGHT, LocalJobContext
from app.ports import AppError, ProviderRequest
from app.schemas.job import Job, JobKind, JobState, Stage, Usage
from app.storage.projects import SqliteProjectStore, new_typeid
from tests.jobs.support import Env, new_job, open_env


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


def _reply(
    try_index: int, *, input_tokens: int | None, output_tokens: int | None
) -> ProviderRequest:
    return ProviderRequest(
        try_index=try_index,
        stage=Stage.llm_draft,
        provider="fixture",
        model="fixture",
        credential_id=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=None,
        cache_write_tokens=None,
        outcome="ok",
    )


def _video(env: Env) -> str:
    """A video row the metrics query accepts; metrics read job records, not the video."""
    project_id, video_id = new_typeid("p"), new_typeid("v")
    with env.db.write() as conn:
        conn.execute(
            "INSERT INTO projects (id, owner_id, created_at) VALUES (?, 'owner', ?)",
            (project_id, "2026-11-17T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO videos (id, project_id, head) VALUES (?, ?, 1)", (video_id, project_id)
        )
    return video_id


def _usage() -> Usage:
    return Usage(
        stage=Stage.llm_draft,
        provider="fixture",
        model="fixture",
        effort=None,
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=None,
        wall_ms=1,
        retries=0,
    )


def test_27_failed_job_exposes_the_usage_the_ledger_holds(env: Env) -> None:
    job = env.jobs.create(new_job(JobKind.draft, max_attempts=1))

    def run_job(current: Job, ctx: LocalJobContext) -> dict:
        # One call answered, then its output failed validation twice: the adapter
        # raised, so `record_usage` never ran, yet both replies spent tokens.
        ctx.record_request(_reply(0, input_tokens=100, output_tokens=40))
        ctx.record_request(_reply(1, input_tokens=120, output_tokens=None))
        raise AppError("llm_invalid_output")

    finished = env.runner(run_job).run_once(LIGHT)
    assert finished is not None and finished.state is JobState.failed
    stored = env.jobs.get(job.id)
    assert [
        (u.stage, u.input_tokens, u.output_tokens, u.retries) for u in stored.usage
    ] == [(Stage.llm_draft, 220, 40, 1)]


def test_27_usage_the_job_already_recorded_is_not_added_again(env: Env) -> None:
    job = env.jobs.create(new_job(JobKind.draft, max_attempts=1))

    def run_job(current: Job, ctx: LocalJobContext) -> dict:
        ctx.record_request(_reply(0, input_tokens=10, output_tokens=5))
        ctx.record_usage(_usage())
        ctx.record_request(_reply(0, input_tokens=7, output_tokens=3))
        raise AppError("llm_invalid_output")

    env.runner(run_job).run_once(LIGHT)
    stored = env.jobs.get(job.id)
    assert [u.input_tokens for u in stored.usage] == [10, 7]


def test_27_metrics_return_tokens_rebuilt_scenes_and_build_time(env: Env) -> None:
    video_id = _video(env)
    store = SqliteProjectStore(env.db, env.layout)
    empty = store.metrics(video_id)
    assert (empty.input_tokens, empty.output_tokens, empty.job_wall_ms) == (None, None, 0)
    assert empty.regenerated_scene_ids == []

    job = env.jobs.create(new_job(JobKind.draft, video_id=video_id))

    def run_job(current: Job, ctx: LocalJobContext) -> dict:
        with ctx.stage(Stage.llm_draft):
            ctx.record_request(_reply(0, input_tokens=30, output_tokens=8))
            ctx.record_usage(_usage())
        return {
            "stages": [
                {
                    "stage": "llm_draft",
                    "state": "done",
                    "started_ms": 0,
                    "ended_ms": 1,
                    "cache_hits": 2,
                    "rebuilt_scene_ids": ["s_0hzb7bexv28termtt2ypc6trzt"],
                }
            ]
        }

    finished = env.runner(run_job).run_once(LIGHT)
    assert finished is not None and finished.state is JobState.succeeded

    record = env.jobs.get(job.id).stages[0]
    assert (record.cache_hits, record.rebuilt_scene_ids) == (
        2,
        ["s_0hzb7bexv28termtt2ypc6trzt"],
    )
    metrics = store.metrics(video_id)
    assert (metrics.input_tokens, metrics.output_tokens) == (30, 8)
    assert metrics.regenerated_scene_ids == ["s_0hzb7bexv28termtt2ypc6trzt"]
    assert metrics.job_wall_ms >= 0
    started, ended = finished.started_at, finished.ended_at
    assert started is not None and ended is not None
    assert metrics.job_wall_ms == int((ended - started).total_seconds() * 1000)
