"""Reference source lifecycle: copy per attempt, retain for retry, cleanup when done."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_runtime
from app.jobs import HEAVY, CancelFlag, LocalJobContext
from app.main import create_app
from app.ports import AppError
from app.schemas.job import Job, JobError, JobErrorCode, JobKind, JobState
from app.services.reference.service import ReferenceService
from tests.conftest import browser_client, pair
from tests.jobs.support import Env, new_job, open_env

JOB = "j_01jdq7c3v8m4n5p6q7r8s9t0vw"
DATA = b"the same staged reference bytes"


def _service(cache_dir: Path, *, max_bytes: int = 1024) -> ReferenceService:
    return ReferenceService(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        catalog=object(),  # type: ignore[arg-type]
        project_store=object(),  # type: ignore[arg-type]
        frames=object(),  # type: ignore[arg-type]
        cache_dir=cache_dir,
        max_upload_bytes=max_bytes,
        max_upload_ms=60_000,
    )


def _context(cache_dir: Path) -> LocalJobContext:
    return LocalJobContext(
        cancel_token=CancelFlag(),
        deadline=time.monotonic() + 60,
        job_dir=cache_dir / "j" / JOB,
        input_payload={"base_revision": 1, "upload_path": "staged"},
    )


def _stage(cache_dir: Path, name: str = "upload-0123456789abcdef.src") -> Path:
    folder = cache_dir / "reference-uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(DATA)
    return path


def test_20_reference_ingest_copies_the_staged_source(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    staged = _stage(cache_dir)
    service = _service(cache_dir)

    source = service.ingest(staged, None, ctx=_context(cache_dir))
    retried = service.ingest(staged, None, ctx=_context(cache_dir))

    assert staged.read_bytes() == DATA
    assert source.parent == cache_dir / "r" / JOB
    assert source != staged and source.read_bytes() == DATA
    assert retried.read_bytes() == DATA


def test_20_failed_ingest_keeps_the_staged_source_and_clears_the_attempt(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    staged = _stage(cache_dir)
    service = _service(cache_dir, max_bytes=len(DATA) - 1)

    with pytest.raises(AppError) as raised:
        service.ingest(staged, None, ctx=_context(cache_dir))

    assert raised.value.code == "upload_invalid"
    assert staged.read_bytes() == DATA
    assert not (cache_dir / "r" / JOB).exists()


def _stage_input(env: Env, job: Job) -> Path:
    folder = env.layout.cache / "reference-uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"upload-{job.id[2:]}.src"
    path.write_bytes(DATA)
    env.inputs.save(job.id, {"base_revision": 1, "upload_path": str(path)})
    return path


def _fail(
    env: Env,
    job: Job,
    *,
    code: JobErrorCode = JobErrorCode.internal,
    retryable: bool = True,
) -> Job:
    claimed = env.jobs.claim(HEAVY)
    assert claimed is not None and claimed.id == job.id
    error = JobError(code=code, retryable=retryable, stage=None, scene_id=None, detail={})
    assert env.jobs.finish(job.id, claimed.attempt, "failed", None, error, False)
    return env.jobs.get(job.id)


def _raw_attempt_folder(env: Env, job: Job) -> Path:
    return env.layout.cache / "r" / job.id / "frames"


def test_20_retryable_failure_keeps_the_source_and_success_removes_it(
    tmp_path: Path,
) -> None:
    env = open_env(tmp_path)
    try:
        job = env.jobs.create(new_job(JobKind.reference, max_attempts=2))
        staged = _stage_input(env, job)
        seen: list[bytes] = []

        def run_job(current: Job, ctx: LocalJobContext) -> dict[str, Any]:
            source = Path(ctx.input["upload_path"])
            seen.append(source.read_bytes())
            raw = _raw_attempt_folder(env, current)
            raw.mkdir(parents=True, exist_ok=True)
            (raw / "frame.png").write_bytes(b"raw frame")
            if len(seen) == 1:
                raise AppError("internal")
            return {"reference": {}}

        runner = env.runner(run_job)
        failed = runner.run_once(HEAVY)
        assert failed is not None and failed.state is JobState.failed
        assert failed.error is not None and failed.error.retryable
        assert staged.read_bytes() == DATA
        assert not _raw_attempt_folder(env, job).parent.exists()

        queued = env.jobs.requeue(job.id)
        assert queued.state is JobState.queued and queued.attempt == 2
        assert runner.run_once(HEAVY) is not None
        done = env.jobs.get(job.id)
        assert done.state is JobState.succeeded
        assert seen == [DATA, DATA]
        assert not staged.exists()
        assert not _raw_attempt_folder(env, job).parent.exists()
    finally:
        env.close()


def test_20_non_retryable_failure_removes_the_source(tmp_path: Path) -> None:
    env = open_env(tmp_path)
    try:
        job = env.jobs.create(new_job(JobKind.reference, max_attempts=2))
        staged = _stage_input(env, job)

        def run_job(current: Job, ctx: LocalJobContext) -> dict[str, Any]:
            raise AppError("upload_invalid")

        failed = env.runner(run_job).run_once(HEAVY)

        assert failed is not None and failed.state is JobState.failed
        assert failed.error is not None and not failed.error.retryable
        assert not staged.exists()
    finally:
        env.close()


def test_20_recovery_keeps_live_and_retryable_sources_and_drops_the_rest(
    tmp_path: Path,
) -> None:
    env = open_env(tmp_path)
    try:
        retry = env.jobs.create(new_job(JobKind.reference, max_attempts=2))
        retry_source = _stage_input(env, retry)
        assert _fail(env, retry, retryable=True).error.retryable  # type: ignore[union-attr]

        permanent = env.jobs.create(new_job(JobKind.reference, max_attempts=2))
        permanent_source = _stage_input(env, permanent)
        _fail(env, permanent, code=JobErrorCode.upload_invalid, retryable=False)

        exhausted = env.jobs.create(new_job(JobKind.reference, max_attempts=1))
        exhausted_source = _stage_input(env, exhausted)
        _fail(env, exhausted, retryable=True)

        done = env.jobs.create(new_job(JobKind.reference, max_attempts=1))
        done_source = _stage_input(env, done)
        assert env.jobs.claim(HEAVY) is not None
        assert env.jobs.finish(done.id, 1, "succeeded", {}, None, False)

        cancelled = env.jobs.create(new_job(JobKind.reference, max_attempts=2))
        cancelled_source = _stage_input(env, cancelled)
        assert env.jobs.request_cancel(cancelled.id).state is JobState.cancelled

        foreign = env.jobs.create(new_job(JobKind.reference, max_attempts=1))
        outside_source = tmp_path / "elsewhere" / "upload-foreign.src"
        outside_source.parent.mkdir()
        outside_source.write_bytes(b"foreign input")
        env.inputs.save(foreign.id, {"upload_path": str(outside_source)})
        assert env.jobs.claim(HEAVY) is not None
        assert env.jobs.finish(foreign.id, 1, "succeeded", {}, None, False)

        interrupted = env.jobs.create(new_job(JobKind.reference, max_attempts=2))
        interrupted_source = _stage_input(env, interrupted)
        assert env.jobs.claim(HEAVY) is not None

        live = env.jobs.create(new_job(JobKind.reference, max_attempts=2))
        live_source = _stage_input(env, live)

        uploads = env.layout.cache / "reference-uploads"
        orphan_src = uploads / "upload-orphan-src.src"
        orphan_src.write_bytes(b"orphan")
        orphan_part = uploads / "upload-orphan-part.part"
        orphan_part.write_bytes(b"partial")
        outside_target = tmp_path / "outside-target.bin"
        outside_target.write_bytes(b"not ours")
        outside_link = uploads / "upload-outside-link.src"
        linked = True
        try:
            outside_link.symlink_to(outside_target)
        except OSError:
            linked = False

        changed = env.runner(lambda job, ctx: None).recover()

        assert any(job.id == interrupted.id and outcome == "requeued" for job, outcome in changed)
        after = env.jobs.get(interrupted.id)
        assert after.state is JobState.queued and after.attempt == 2
        assert after.error is None
        assert interrupted_source.read_bytes() == DATA
        assert live_source.read_bytes() == DATA
        assert retry_source.read_bytes() == DATA
        assert not permanent_source.exists()
        assert not exhausted_source.exists()
        assert not done_source.exists()
        assert not cancelled_source.exists()
        assert not orphan_src.exists() and not orphan_part.exists()
        if linked:
            assert not outside_link.is_symlink()
        assert outside_target.read_bytes() == b"not ours"
        assert outside_source.read_bytes() == b"foreign input"
    finally:
        env.close()


@pytest.fixture
def paused_client(
    app_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    app_settings.app.uploads.reference_max_bytes = 1024
    runtime = build_runtime(app_settings)
    monkeypatch.setattr(runtime, "start", lambda: None)
    urls: list[str] = []
    app = create_app(runtime, pairing_display=urls.append)
    with browser_client(app, app_settings.port) as client:
        pair(client, urls[0].split("#pair=", 1)[1])
        yield client


def _new_video(client: TestClient) -> dict[str, Any]:
    project = client.post(
        "/api/v1/projects", json={"title": "Reference lifecycle", "language": "en"}
    )
    assert project.status_code == 201, project.text
    video = client.post(
        f"/api/v1/projects/{project.json()['id']}/videos",
        json={"from_video_id": None, "preset_id": None},
    )
    assert video.status_code == 201, video.text
    return video.json()


def test_20_queued_cancel_removes_the_staged_source_with_workers_paused(
    paused_client: TestClient,
) -> None:
    video = _new_video(paused_client)
    response = paused_client.post(
        f"/api/v1/videos/{video['id']}/references",
        data={"base_revision": str(video["revision"])},
        files={"file": ("synthetic.mp4", DATA, "video/mp4")},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    runtime = paused_client.app.state.runtime  # type: ignore[attr-defined]
    saved = runtime.job_inputs.load(job["id"])
    assert saved is not None
    source = Path(saved["upload_path"])
    assert source.parent == runtime.settings.cache_dir / "reference-uploads"
    assert source.suffix == ".src" and source.read_bytes() == DATA
    assert runtime.job_store.get(job["id"]).state is JobState.queued

    cancelled = paused_client.post(f"/api/v1/jobs/{job['id']}/cancel")

    assert cancelled.status_code == 202, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    assert not source.exists()
    assert list((runtime.settings.cache_dir / "reference-uploads").iterdir()) == []


def test_20_recovery_does_not_delete_sources_when_live_input_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = open_env(tmp_path)
    try:
        job = env.jobs.create(new_job(JobKind.reference, max_attempts=2))
        source = _stage_input(env, job)
        original_load = env.inputs.load

        def unavailable(job_id: str) -> dict[str, Any] | None:
            if job_id == job.id:
                raise OSError("synthetic input read failure")
            return original_load(job_id)

        monkeypatch.setattr(env.inputs, "load", unavailable)
        env.runner(lambda current, ctx: {}).recover()
        assert env.jobs.get(job.id).state is JobState.queued
        assert source.read_bytes() == DATA
    finally:
        env.close()


def test_20_cancelled_upload_cannot_be_retried_without_its_source(
    paused_client: TestClient,
) -> None:
    video = _new_video(paused_client)
    response = paused_client.post(
        f"/api/v1/videos/{video['id']}/references",
        data={"base_revision": str(video["revision"])},
        files={"file": ("synthetic.mp4", DATA, "video/mp4")},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    runtime = paused_client.app.state.runtime  # type: ignore[attr-defined]
    assert paused_client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 202

    retried = paused_client.post(f"/api/v1/jobs/{job_id}/retry")

    assert retried.status_code == 409, retried.text
    assert retried.json()["code"] == "job_not_retryable"
    assert runtime.job_store.get(job_id).state is JobState.cancelled
    assert runtime.job_store.unfinished() == []


def test_20_cleanup_recognizes_every_staged_name(paused_client: TestClient) -> None:
    runner = paused_client.app.state.runtime.runner  # type: ignore[attr-defined]
    part, source = runner.stage_reference_upload()
    part.write_bytes(b"partial")
    source.write_bytes(b"orphan")
    assert part.parent == source.parent and part.stem == source.stem

    runner.cleanup_reference_uploads()

    assert not part.exists() and not source.exists()
