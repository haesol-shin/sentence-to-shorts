"""RuntimeSetup: one queued prepare job, run through the real job runner."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.jobs import LocalJobContext
from app.runtime.lock import host_platform
from app.runtime.setup import RuntimeSetup
from app.schemas.api import RuntimeItemState
from app.schemas.common import TYPEID_PATTERN
from app.schemas.job import Job, JobErrorCode, JobKind, JobState, Stage
from tests.jobs.support import Env, open_env, wait_until
from tests.runtime.support import FakeTransport, lock_item, make_settings, make_zip, noise, url_of

OS_NAME, ARCH = host_platform()
BLOB = make_zip({"tool": noise(600_000, "tool")}, modes={"tool": 0o755})


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


def setup_for(tmp_path: Path, env: Env, blob: bytes = BLOB, sha: str | None = None):  # type: ignore[no-untyped-def]
    item = lock_item("tool", "tool", "tool.zip", blob, os_name=OS_NAME, arch=ARCH, sha256=sha)
    settings = make_settings(tmp_path, [item])
    transport = FakeTransport({url_of(item): blob})
    return RuntimeSetup(settings, object(), env.jobs, transport=transport), transport  # type: ignore[arg-type]


def test_setup_submit_creates_one_queued_job_and_returns_it_while_unfinished(
    tmp_path: Path, env: Env
) -> None:
    setup, _transport = setup_for(tmp_path, env)
    first = setup.submit_prepare(idempotency_key="key-abcdefgh")
    assert first.kind is JobKind.runtime_prepare and first.state is JobState.queued
    assert first.idempotency_key == "key-abcdefgh" and first.max_attempts == 3
    assert re.fullmatch(TYPEID_PATTERN, first.id)
    assert setup.submit_prepare(idempotency_key=None).id == first.id
    assert env.jobs.get(first.id).state is JobState.queued


def test_setup_job_prepares_the_runtime_and_reports_download_progress(
    tmp_path: Path, env: Env
) -> None:
    setup, transport = setup_for(tmp_path, env)
    job = setup.submit_prepare(idempotency_key=None)

    def run_job(current: Job, ctx: LocalJobContext) -> dict[str, Any]:
        return setup.run_job(current, ctx)

    runner = env.runner(run_job)
    runner.start()
    try:
        assert wait_until(lambda: env.jobs.get(job.id).state is JobState.succeeded)
    finally:
        runner.stop()
    done = env.jobs.get(job.id)
    assert done.result == {"prepared": ["tool"]}
    assert {record.stage for record in done.stages} == {Stage.model_download, Stage.model_verify}
    assert done.progress.total == len(BLOB) and done.progress.done == len(BLOB)
    assert [item.state for item in setup.status()] == [RuntimeItemState.ready]
    assert transport.count == 1

    again = setup.submit_prepare(idempotency_key=None)
    assert again.id != job.id


def test_setup_job_fails_without_a_retry_when_the_download_has_the_wrong_hash(
    tmp_path: Path, env: Env
) -> None:
    setup, _transport = setup_for(tmp_path, env, sha="0" * 64)
    job = setup.submit_prepare(idempotency_key=None)
    runner = env.runner(lambda current, ctx: setup.run_job(current, ctx))
    runner.start()
    try:
        assert wait_until(lambda: env.jobs.get(job.id).state is JobState.failed)
    finally:
        runner.stop()
    error = env.jobs.get(job.id).error
    assert error is not None and error.code is JobErrorCode.model_hash_mismatch
    assert error.retryable is False
    assert [item.state for item in setup.status()] == [RuntimeItemState.missing]
