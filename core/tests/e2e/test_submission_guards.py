"""Submission readiness and project deletion share the HTTP job boundary."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from functools import partial
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import AppRuntime, build_runtime
from app.ports import AppError
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import Job, JobKind, JobState
from app.schemas.project import Project
from app.schemas.video import Video
from tests.conftest import load_json


def _project_video(runtime: AppRuntime) -> tuple[Project, Video]:
    project = Project.model_validate(load_json("contracts/valid/project_min.json"))
    video = Video.model_validate(load_json("contracts/valid/video_ko_just_three.json"))
    project = project.model_copy(update={"video_ids": []})
    runtime.project_store.put_project(project)
    runtime.project_store.append_revision(video)
    return project, video


@pytest.mark.parametrize("retry", [False, True], ids=["submit", "retry"])
def test_uninstalled_runtime_refuses_generation_without_queuing(
    client: TestClient, retry: bool
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    # Park execution so seeded attempts cannot be consumed during HTTP checks.
    runtime.runner.stop()
    _, video = _project_video(runtime)
    before = []
    if retry:
        job = Job.model_validate(load_json("contracts/valid/job_queued.json"))
        job = job.model_copy(update={"kind": JobKind.generate})
        runtime.job_store.create(job)
        runtime.job_store.request_cancel(job.id)
        before = [job.id]
        path = f"/api/v1/jobs/{job.id}/retry"
        body = None
    else:
        path = f"/api/v1/videos/{video.id}/generate"
        body = {"base_revision": video.revision}

    assert client.get("/api/v1/runtime").json()["capabilities"]["render"] is False
    response = client.post(path, json=body)
    assert response.status_code == 503
    assert response.json()["code"] == "runtime_not_ready"
    assert [job.id for job in runtime.submitter.find()] == before
    assert runtime.job_store.unfinished() == []
    if retry:
        assert runtime.job_store.get(before[0]).state is JobState.cancelled


def test_http_delete_refuses_a_project_scoped_active_job(client: TestClient) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    runtime.runner.stop()
    project, _ = _project_video(runtime)
    job = Job.model_validate(load_json("contracts/valid/job_queued.json"))
    job = job.model_copy(update={"video_id": None})
    runtime.job_store.create(job)

    response = client.delete(f"/api/v1/projects/{project.id}")
    assert response.status_code == 409
    assert response.json()["code"] == "job_running"
    assert response.json()["job_id"] == job.id
    assert client.get(f"/api/v1/projects/{project.id}").status_code == 200


@pytest.mark.parametrize("retry", [False, True], ids=["submit", "retry"])
@pytest.mark.parametrize("video_scoped", [False, True], ids=["project", "video"])
@pytest.mark.parametrize("delete_first", [False, True], ids=["job-first", "delete-first"])
def test_deletion_and_job_submission_cannot_both_succeed(
    app_settings, monkeypatch: pytest.MonkeyPatch, retry: bool,
    video_scoped: bool, delete_first: bool,
) -> None:  # type: ignore[no-untyped-def]
    runtime = build_runtime(app_settings)
    entered, release, attempted = Event(), Event(), Event()
    try:
        project, video = _project_video(runtime)

        def submit() -> Job:
            return runtime.submitter.submit(
                JobKind.draft,
                owner_id=PERSONAL_OWNER_ID,
                project_id=None if video_scoped else project.id,
                video_id=video.id if video_scoped else None,
                base_revision=video.revision if video_scoped else None,
                request_digest="a" * 64,
                input={},
                idempotency_key=None,
            ).job

        action: Callable[[], Any] = submit
        if retry:
            old = submit()
            runtime.job_store.request_cancel(old.id)
            action = partial(runtime.submitter.retry, old.id)

        # Pause after the first operation's checks but before its durable
        # mutation. The competing operation must observe the committed outcome,
        # not slip between the guard and that mutation.
        if delete_first:
            target, method = runtime.project_store, "delete_project"
        elif retry:
            target, method = runtime.job_store, "requeue"
        else:
            target, method = runtime.job_inputs, "save"
        original = getattr(target, method)

        def paused(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            assert release.wait(10), "the mutation was not released"
            return original(*args, **kwargs)

        monkeypatch.setattr(target, method, paused)

        def delete() -> None:
            runtime.submitter.delete_project(project.id)

        first, second = (delete, action) if delete_first else (action, delete)

        def outcome(call: Callable[[], Any], *, competing: bool = False) -> Any:
            if competing:
                attempted.set()
            try:
                return call()
            except AppError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_result = pool.submit(outcome, first)
            try:
                assert entered.wait(10), "the first operation never reached its mutation"
                second_result = pool.submit(outcome, second, competing=True)
                assert attempted.wait(10), "the competitor never started"
                try:
                    second_result.result(timeout=1)
                except TimeoutError:
                    pass
            finally:
                release.set()
            winner = first_result.result(timeout=10)
            refused = second_result.result(timeout=10)

        assert not isinstance(winner, AppError)
        assert isinstance(refused, AppError)
        if delete_first:
            assert refused.code == "not_found"
            assert runtime.job_store.unfinished() == []
            with pytest.raises(AppError) as missing:
                runtime.project_store.get_project(project.id)
            assert missing.value.code == "not_found"
        else:
            assert refused.code == "job_running"
            assert refused.detail == {"job_id": winner.id}
            assert runtime.project_store.get_project(project.id).id == project.id
            assert runtime.job_store.get(winner.id).state is JobState.queued
    finally:
        release.set()
        runtime.close()
