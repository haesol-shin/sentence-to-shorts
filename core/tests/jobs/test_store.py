"""Job store: every transition of the CONTRACTS 5.1 table and the v2 migration."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.jobs import HEAVY, LIGHT, SqliteJobStore
from app.ports import AppError
from app.schemas.job import Job, JobError, JobErrorCode, JobKind, JobState
from app.storage.sqlite import SCHEMA_V1, Database, Migration, registered_migrations
from tests.jobs.support import DEADLINES, Env, new_job, open_env


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


def _error(code: JobErrorCode = JobErrorCode.render_failed) -> JobError:
    return JobError(code=code, retryable=True, stage=None, scene_id=None, detail={})


def test_transition_submit_creates_a_queued_job(env: Env) -> None:
    job = env.jobs.create(new_job())
    assert env.jobs.get(job.id).state is JobState.queued
    with pytest.raises(ValueError):
        env.jobs.create(new_job().model_copy(update={"state": JobState.running}))


def test_claim_two_threads_only_one_wins(env: Env) -> None:
    second_db = Database.open(env.layout.state_db)
    stores = [env.jobs, SqliteJobStore(second_db, deadlines_s=DEADLINES)]
    try:
        for _ in range(10):
            env.jobs.create(new_job())
            env.jobs.create(new_job())
            barrier = threading.Barrier(2)
            claimed: list[Job | None] = []

            def claim(store: SqliteJobStore) -> None:
                barrier.wait()
                claimed.append(store.claim(HEAVY))

            threads = [threading.Thread(target=claim, args=(store,)) for store in stores]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            won = [job for job in claimed if job is not None]
            assert len(won) == 1
            assert env.jobs.get(won[0].id).state is JobState.running
            assert env.jobs.finish(won[0].id, 1, "succeeded", {}, None, False)
    finally:
        second_db.close()


def test_claim_runs_one_job_per_queue(env: Env) -> None:
    first = env.jobs.create(new_job(JobKind.generate))
    env.jobs.create(new_job(JobKind.preview))
    light = env.jobs.create(new_job(JobKind.draft))

    running = env.jobs.claim(HEAVY)
    assert running is not None and running.id == first.id
    assert running.started_at is not None and running.deadline_at is not None
    assert env.jobs.claim(HEAVY) is None
    claimed_light = env.jobs.claim(LIGHT)
    assert claimed_light is not None and claimed_light.id == light.id


def test_finish_previous_attempt_returns_false(env: Env) -> None:
    job = env.jobs.create(new_job())
    assert env.jobs.claim(HEAVY) is not None
    assert env.jobs.finish(job.id, 1, "failed", None, _error(), False)
    assert env.jobs.requeue(job.id).attempt == 2
    assert env.jobs.claim(HEAVY) is not None

    assert env.jobs.finish(job.id, 1, "succeeded", {"late": True}, None, False) is False
    current = env.jobs.get(job.id)
    assert current.state is JobState.running and current.attempt == 2
    assert current.result is None

    assert env.jobs.finish(job.id, 2, "succeeded", {"ok": True}, None, False)
    done = env.jobs.get(job.id)
    assert done.state is JobState.succeeded and done.result == {"ok": True}
    assert done.ended_at is not None


def test_transition_running_ends_succeeded_or_failed(env: Env) -> None:
    ok = env.jobs.create(new_job(JobKind.draft))
    env.jobs.claim(LIGHT)
    assert env.jobs.finish(ok.id, 1, "succeeded", {"n": 1}, None, False)
    assert env.jobs.get(ok.id).state is JobState.succeeded

    bad = env.jobs.create(new_job(JobKind.draft))
    env.jobs.claim(LIGHT)
    assert env.jobs.finish(bad.id, 1, "failed", None, _error(), True)
    failed = env.jobs.get(bad.id)
    assert failed.state is JobState.failed and failed.partial is True
    assert failed.error is not None and failed.error.code is JobErrorCode.render_failed
    assert env.jobs.finish(bad.id, 1, "succeeded", {}, None, False) is False


def test_transition_queued_cancel_is_immediate(env: Env) -> None:
    job = env.jobs.create(new_job())
    cancelled = env.jobs.request_cancel(job.id)
    assert cancelled.state is JobState.cancelled
    assert env.jobs.get(job.id).ended_at is not None
    assert env.jobs.claim(HEAVY) is None


def test_transition_running_cancel_goes_through_cancelling(env: Env) -> None:
    job = env.jobs.create(new_job())
    env.jobs.claim(HEAVY)
    assert env.jobs.request_cancel(job.id).state is JobState.cancelling
    assert env.jobs.request_cancel(job.id).state is JobState.cancelling
    # A result that arrives after the cancel request is dropped.
    assert env.jobs.finish(job.id, 1, "succeeded", {}, None, False) is False
    assert env.jobs.confirm_cancelled(job.id, 2) is False
    assert env.jobs.confirm_cancelled(job.id, 1)
    assert env.jobs.get(job.id).state is JobState.cancelled


def test_transition_terminal_job_cannot_be_cancelled(env: Env) -> None:
    job = env.jobs.create(new_job())
    env.jobs.claim(HEAVY)
    env.jobs.finish(job.id, 1, "succeeded", {}, None, False)
    with pytest.raises(AppError) as raised:
        env.jobs.request_cancel(job.id)
    assert raised.value.code == "job_terminal"


def test_transition_retry_needs_a_failed_or_cancelled_job_with_attempts_left(env: Env) -> None:
    cancelled = env.jobs.create(new_job())
    env.jobs.request_cancel(cancelled.id)
    retried = env.jobs.requeue(cancelled.id)
    assert retried.state is JobState.queued and retried.attempt == 2
    assert retried.error is None and retried.ended_at is None

    last = env.jobs.create(new_job(JobKind.draft, max_attempts=1))
    env.jobs.claim(LIGHT)
    env.jobs.finish(last.id, 1, "failed", None, _error(), False)
    with pytest.raises(AppError) as exhausted:
        env.jobs.requeue(last.id)
    assert exhausted.value.code == "job_not_retryable"

    ok = env.jobs.create(new_job(JobKind.chat))
    env.jobs.claim(LIGHT)
    env.jobs.finish(ok.id, 1, "succeeded", {}, None, False)
    with pytest.raises(AppError) as succeeded:
        env.jobs.requeue(ok.id)
    assert succeeded.value.code == "job_not_retryable"


def test_transition_unknown_job_is_not_found(env: Env) -> None:
    with pytest.raises(AppError) as raised:
        env.jobs.get("j_01jdq7c3v8m4n5p6q7r8s9t0vw")
    assert raised.value.code == "not_found"


def test_migration_v2_adds_job_tables_without_touching_v1(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    Database.open(path, migrations=[Migration(1, SCHEMA_V1)]).close()
    raw = sqlite3.connect(path)
    try:
        raw.execute("INSERT INTO projects VALUES ('p_01jdq7c3v8m4n5p6q7r8s9t0vw', 'o', 't')")
        raw.commit()
    finally:
        raw.close()

    through_two = tuple(m for m in registered_migrations() if m.version <= 2)
    database = Database.open(path, migrations=through_two)
    try:
        assert database.user_version == 2
        with database.read() as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
            projects = conn.execute("SELECT id FROM projects").fetchall()
    finally:
        database.close()
    assert {"jobs", "idempotency", "projects", "artifacts", "holds"} <= tables
    assert projects == [("p_01jdq7c3v8m4n5p6q7r8s9t0vw",)]
    assert path.with_name("state.db.bak-1").is_file()
