"""BGM upload staging: ownership of the copied file and its cleanup."""

from __future__ import annotations

from pathlib import Path

from app.jobs import LIGHT
from app.schemas.job import Job, JobKind
from app.storage.projects import new_typeid
from tests.jobs.support import Env, new_job, open_env


def _stage(env: Env, *, max_attempts: int = 1) -> tuple[Job, Path]:
    root = env.layout.data / "staging" / "bgm"
    root.mkdir(parents=True, exist_ok=True)
    upload_id = new_typeid("u")
    path = root / upload_id
    path.write_bytes(b"synthetic upload")
    job = new_job(JobKind.bgm_upload, max_attempts=max_attempts)
    env.inputs.save(
        job.id,
        {
            "project_id": "p_06pxfteaw88hs93kkckw5j51ng",
            "mood": "calm",
            "upload_id": upload_id,
            "staging_path": str(path),
        },
    )
    env.jobs.create(job)
    return job, path


def test_bgm_staging_is_deleted_when_the_job_ends(tmp_path: Path) -> None:
    env = open_env(tmp_path)
    try:
        job, path = _stage(env)
        runner = env.runner(lambda job, ctx: {"bgm_id": "u_synthetic"})
        runner.run_once(LIGHT)
        assert env.jobs.get(job.id).state.value == "succeeded"
        assert not path.exists()
    finally:
        env.close()


def test_bgm_staging_is_deleted_when_a_queued_job_is_cancelled(tmp_path: Path) -> None:
    env = open_env(tmp_path)
    try:
        job, path = _stage(env)
        env.jobs.request_cancel(job.id)
        runner = env.runner(lambda job, ctx: {})
        assert runner.discard_bgm_upload(job.id) is True
        assert not path.exists()
    finally:
        env.close()


def test_start_removes_bgm_staging_no_active_job_references(tmp_path: Path) -> None:
    env = open_env(tmp_path)
    try:
        job, kept = _stage(env)
        root = kept.parent
        orphan = root / new_typeid("u")
        orphan.write_bytes(b"orphan")
        runner = env.runner(lambda job, ctx: {})
        runner.recover()
        assert kept.is_file()
        assert not orphan.exists()
    finally:
        env.close()
