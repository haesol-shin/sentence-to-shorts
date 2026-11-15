"""Runner: results, errors, deadline, cancel with a child process tree, job folders."""

from __future__ import annotations

import errno
import os
import sqlite3
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.jobs import HEAVY, LIGHT, JobRunner, LocalJobContext
from app.ports import AppError
from app.schemas.job import (
    Checkpoint,
    Effort,
    Job,
    JobErrorCode,
    JobKind,
    JobState,
    Stage,
    StageState,
    Usage,
)
from app.tools.process import run
from tests.jobs.support import DEADLINES, Env, new_job, open_env, publish_clip, wait_until

SCENE = "s_01jdq7c3v8m4n5p6q7r8s9t0vw"


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


def _alive(pid: int) -> bool:
    if sys.platform.startswith("linux"):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return False
        if stat.rsplit(")", 1)[1].split()[0] == "Z":
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_runner_success_records_result_progress_stages_and_usage(env: Env) -> None:
    job = env.jobs.create(new_job(JobKind.draft))
    env.inputs.save(job.id, {"message": "hi"})
    seen: dict[str, Any] = {}

    def run_job(current: Job, ctx: LocalJobContext) -> dict[str, Any]:
        seen["input"] = ctx.input
        (ctx.job_dir / "work.txt").write_text("partial", encoding="utf-8")
        with ctx.stage(Stage.llm_draft):
            ctx.progress(done=1, total=2)
            ctx.record_usage(
                Usage(
                    stage=Stage.llm_draft,
                    provider="fixture",
                    model="fixture-model",
                    effort=Effort.low,
                    input_tokens=10,
                    output_tokens=5,
                    cache_read_tokens=None,
                    cost_usd=None,
                    wall_ms=3,
                    retries=0,
                )
            )
        return {"ops": 2}

    finished = env.runner(run_job).run_once(LIGHT)
    assert finished is not None and finished.state is JobState.succeeded
    assert seen["input"] == {"message": "hi"}
    assert finished.result == {"ops": 2}
    assert finished.progress.done == 1 and finished.progress.stage is Stage.llm_draft
    assert [(s.stage, s.state) for s in finished.stages] == [(Stage.llm_draft, StageState.done)]
    assert finished.stages[0].ended_ms is not None
    assert [u.model for u in finished.usage] == ["fixture-model"]
    assert not (env.layout.cache / "j" / job.id).exists()


def test_runner_error_becomes_a_job_error_and_keeps_partial_output(env: Env) -> None:
    env.jobs.create(new_job(JobKind.generate))

    def run_job(current: Job, ctx: LocalJobContext) -> dict[str, Any]:
        artifact = publish_clip(env.artifacts, ctx.job_dir, b"scene one", current.id)
        ctx.checkpoint(
            Checkpoint(
                stage=Stage.clip,
                scene_id=SCENE,
                line_id=None,
                artifact_id=artifact.id,
                digest=artifact.digest,
            )
        )
        with ctx.stage(Stage.tts):
            raise AppError("tts_failed", detail={"scene_id": SCENE, "engine": "fixture"})

    failed = env.runner(run_job).run_once(HEAVY)
    assert failed is not None and failed.state is JobState.failed
    assert failed.error is not None
    assert failed.error.code is JobErrorCode.tts_failed
    assert failed.error.stage is Stage.tts and failed.error.scene_id == SCENE
    assert failed.error.retryable is True
    assert failed.partial is True and len(failed.checkpoints) == 1
    assert failed.stages[-1].state is StageState.failed


def test_runner_unexpected_exception_is_internal_without_text(env: Env) -> None:
    env.jobs.create(new_job(JobKind.chat))

    def run_job(current: Job, ctx: LocalJobContext) -> dict[str, Any]:
        raise RuntimeError("private prompt text")

    failed = env.runner(run_job).run_once(LIGHT)
    assert failed is not None and failed.error is not None
    assert failed.error.code is JobErrorCode.internal and failed.error.detail == {}
    assert "private prompt text" not in failed.model_dump_json()


def test_runner_deadline_exceeded_fails_the_attempt(tmp_path: Path) -> None:
    env = open_env(tmp_path, {**DEADLINES, JobKind.precheck.value: 1})
    runner = env.runner(lambda job, ctx: ctx.cancel.wait(30) and ctx.cancel.raise_if_set())
    try:
        job = env.jobs.create(new_job(JobKind.precheck))
        runner.start()
        assert wait_until(lambda: env.jobs.get(job.id).state is JobState.failed)
        failed = env.jobs.get(job.id)
    finally:
        runner.stop()
        env.close()
    assert failed.error is not None
    assert failed.error.code is JobErrorCode.deadline_exceeded
    assert failed.error.retryable is True


def test_cancel_running_job_stops_the_child_tree_then_cancels(env: Env, tmp_path: Path) -> None:
    pids = tmp_path / "pids.txt"
    script = (
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open(sys.argv[1], 'w').write(f'{os.getpid()} {child.pid}')\n"
        "time.sleep(60)\n"
    )

    def run_job(current: Job, ctx: LocalJobContext) -> dict[str, Any]:
        result = run([sys.executable, "-c", script, str(pids)], cancel=ctx.cancel)
        ctx.cancel.raise_if_set()
        return {"returncode": result.returncode}

    job = env.jobs.create(new_job(JobKind.generate))
    runner = env.runner(run_job)
    runner.start()
    try:
        assert wait_until(lambda: pids.is_file() and len(pids.read_text().split()) == 2)
        parent, grandchild = (int(value) for value in pids.read_text().split())
        assert env.jobs.request_cancel(job.id).state is JobState.cancelling
        assert wait_until(lambda: env.jobs.get(job.id).state is JobState.cancelled)
    finally:
        runner.stop()
    assert not _alive(parent)
    if os.name == "posix":
        assert wait_until(lambda: not _alive(grandchild), timeout_s=5)
    cancelled = env.jobs.get(job.id)
    assert cancelled.result is None and cancelled.ended_at is not None


class _FullDiskArtifacts:
    """Artifact store whose job folder cannot be created."""

    def job_dir(self, job_id: str) -> Path:
        raise OSError(errno.ENOSPC, "synthetic disk full")


def test_runner_context_failure_fails_the_job_and_keeps_the_queue(env: Env) -> None:
    first = env.jobs.create(new_job(JobKind.draft))
    second = env.jobs.create(new_job(JobKind.chat))
    runner = JobRunner(
        env.jobs,
        _FullDiskArtifacts(),  # type: ignore[arg-type]
        env.inputs,
        lambda job, ctx: {},
        cache_dir=env.layout.cache,
        poll_s=0.02,
        watch_s=0.02,
    )
    runner.start()
    try:
        assert wait_until(lambda: env.jobs.get(second.id).state is JobState.failed)
    finally:
        runner.stop()
    failed = env.jobs.get(first.id)
    assert failed.state is JobState.failed and failed.error is not None
    assert failed.error.code is JobErrorCode.disk_full


def test_runner_deadline_crossed_between_watcher_ticks_is_a_timeout(tmp_path: Path) -> None:
    env = open_env(tmp_path, {**DEADLINES, JobKind.draft.value: 1})
    runner = JobRunner(
        env.jobs,
        env.artifacts,
        env.inputs,
        lambda job, ctx: time.sleep(1.1) or {"late": True},
        cache_dir=env.layout.cache,
        watch_s=60,
    )
    try:
        job = env.jobs.create(new_job(JobKind.draft))
        finished = runner.run_once(LIGHT)
    finally:
        env.close()
    assert finished is not None and finished.id == job.id
    assert finished.state is JobState.failed and finished.result is None
    assert finished.error is not None
    assert finished.error.code is JobErrorCode.deadline_exceeded


def test_runner_store_error_on_finish_is_not_swallowed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = env.jobs.create(new_job(JobKind.draft))

    def broken_finish(*args: Any, **kwargs: Any) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(env.jobs, "finish", broken_finish)
    with pytest.raises(sqlite3.OperationalError):
        env.runner(lambda current, ctx: {}).run_once(LIGHT)
    assert env.jobs.get(job.id).state is JobState.running
