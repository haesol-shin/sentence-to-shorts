"""Start recovery after a forced stop (CONTRACTS 5.3, completion criterion 27)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.jobs import HEAVY, LIGHT, LocalJobContext
from app.schemas.job import Checkpoint, Job, JobErrorCode, JobKind, JobState, Stage
from app.storage.projects import new_typeid
from tests.jobs.support import Env, new_job, open_env, publish_clip, wait_until
from tests.recovery.crash_worker import clip_bytes

CORE = Path(__file__).resolve().parents[2]


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


def _kill_during_job(root: Path, kind: JobKind = JobKind.generate) -> tuple[Job, list[str], str]:
    """Queue a two-scene job, start a server process, kill it after scene one."""
    scenes = [new_typeid("s"), new_typeid("s")]
    env = open_env(root)
    try:
        job = env.jobs.create(new_job(kind, video_id=new_typeid("v")))
        env.inputs.save(job.id, {"scenes": scenes})
    finally:
        env.close()
    ready = root / "ready.txt"
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.recovery.crash_worker", str(root), str(ready)],
        cwd=CORE,
    )
    try:
        assert wait_until(ready.is_file, timeout_s=60), "server process never reached scene two"
    finally:
        process.kill()
        process.wait(timeout=30)
    return job, scenes, ready.read_text(encoding="utf-8")


def _resume(env: Env, built: list[str]) -> Job | None:
    def run_job(job: Job, ctx: LocalJobContext) -> dict[str, Any]:
        reused = {cp.scene_id: cp.artifact_id for cp in job.checkpoints}
        clips = {}
        for scene_id in ctx.input["scenes"]:
            if scene_id in reused:
                clips[scene_id] = reused[scene_id]
                continue
            built.append(scene_id)
            artifact = publish_clip(env.artifacts, ctx.job_dir, clip_bytes(scene_id), job.id)
            ctx.checkpoint(
                Checkpoint(
                    stage=Stage.clip,
                    scene_id=scene_id,
                    line_id=None,
                    artifact_id=artifact.id,
                    digest=artifact.digest,
                )
            )
            clips[scene_id] = artifact.id
        return {"clips": clips}

    return env.runner(run_job).run_once(HEAVY)


def test_27_killed_server_resumes_the_job_and_reuses_the_checkpoint(tmp_path: Path) -> None:
    job, scenes, first_clip = _kill_during_job(tmp_path)

    env = open_env(tmp_path)
    try:
        assert env.jobs.get(job.id).state is JobState.running
        assert (env.layout.cache / "j" / job.id).is_dir()
        changed = env.runner(lambda job, ctx: {}).recover()
        assert [(changed_job.id, outcome) for changed_job, outcome in changed] == [
            (job.id, "requeued")
        ]
        queued = env.jobs.get(job.id)
        assert queued.state is JobState.queued and queued.attempt == 2
        assert [cp.artifact_id for cp in queued.checkpoints] == [first_clip]
        # The published clip and its hold survive the forced stop.
        assert env.artifacts.path(first_clip).is_file()
        with env.db.read() as conn:
            holds = conn.execute(
                "SELECT holder FROM holds WHERE artifact_id = ?", (first_clip,)
            ).fetchall()
        assert holds == [(f"rev:{job.video_id}:1",)]

        built: list[str] = []
        finished = _resume(env, built)
    finally:
        env.close()
    assert finished is not None and finished.state is JobState.succeeded
    assert built == [scenes[1]]
    assert finished.result is not None
    assert finished.result["clips"][scenes[0]] == first_clip
    assert [cp.scene_id for cp in finished.checkpoints] == scenes


def test_27_checkpoint_with_a_wrong_digest_is_not_reused(tmp_path: Path) -> None:
    job, scenes, first_clip = _kill_during_job(tmp_path)

    env = open_env(tmp_path)
    try:
        env.artifacts.path(first_clip).write_bytes(b"damaged after the forced stop")
        env.runner(lambda job, ctx: {}).recover()
        built: list[str] = []
        finished = _resume(env, built)
    finally:
        env.close()
    assert finished is not None and finished.state is JobState.succeeded
    assert built == scenes
    assert finished.result is not None
    assert finished.result["clips"][scenes[0]] != first_clip
    assert first_clip not in {cp.artifact_id for cp in finished.checkpoints}


def test_27_restart_closes_what_cannot_resume(env: Env) -> None:
    cancelling = env.jobs.create(new_job(JobKind.generate))
    env.jobs.claim(HEAVY)
    env.jobs.request_cancel(cancelling.id)

    light = env.jobs.create(new_job(JobKind.draft))
    env.jobs.claim(LIGHT)

    exhausted = env.jobs.create(new_job(JobKind.preview, max_attempts=1))
    queued = env.jobs.create(new_job(JobKind.reference))

    changed = dict((job.id, outcome) for job, outcome in env.runner(lambda j, c: {}).recover())
    assert changed == {cancelling.id: "cancelled", light.id: "interrupted"}
    assert env.jobs.get(cancelling.id).state is JobState.cancelled
    interrupted = env.jobs.get(light.id)
    assert interrupted.state is JobState.failed and interrupted.error is not None
    assert interrupted.error.code is JobErrorCode.interrupted
    assert interrupted.error.retryable is True

    # A resumable kind with no attempt left also ends failed.
    env.jobs.claim(HEAVY)
    assert env.jobs.get(exhausted.id).state is JobState.running
    changed = dict((job.id, outcome) for job, outcome in env.runner(lambda j, c: {}).recover())
    assert changed == {exhausted.id: "interrupted"}
    closed = env.jobs.get(exhausted.id)
    assert closed.state is JobState.failed and closed.error is not None
    assert closed.error.retryable is False
    assert env.jobs.get(queued.id).state is JobState.queued


def test_27_restart_removes_only_stale_job_folders(env: Env, tmp_path: Path) -> None:
    active = env.jobs.create(new_job(JobKind.generate))
    stale = new_typeid("j")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    for name in ("j", "r"):
        (env.layout.cache / name / active.id).mkdir(parents=True)
        (env.layout.cache / name / stale).mkdir(parents=True)
        (env.layout.cache / name / stale / "part.bin").write_bytes(b"x")
        (env.layout.cache / name / "not-a-job").mkdir()
    link = env.layout.cache / "j" / new_typeid("j")
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        link = None  # type: ignore[assignment]

    env.runner(lambda j, c: {}).recover()

    for name in ("j", "r"):
        assert (env.layout.cache / name / active.id).is_dir()
        assert not (env.layout.cache / name / stale).exists()
        assert (env.layout.cache / name / "not-a-job").is_dir()
    assert (outside / "keep.txt").is_file()
    if link is not None:
        assert link.is_symlink()
