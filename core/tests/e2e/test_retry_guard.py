"""A retry obeys the same one-active-job rule as a new request."""

from __future__ import annotations

import pytest

from app.bootstrap import build_runtime
from app.ports import AppError
from app.schemas.api import CreateProjectRequest
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import JobKind, JobState


def test_retry_is_refused_while_a_newer_job_of_the_kind_is_active(app_settings) -> None:  # type: ignore[no-untyped-def]
    runtime = build_runtime(app_settings)
    try:
        jobs = runtime.submitter
        project = runtime.services.project.create_project(
            CreateProjectRequest(title="Retry guard", language="ko")
        ).id

        def submit(digest: str):  # type: ignore[no-untyped-def]
            return jobs.submit(
                JobKind.draft,
                owner_id=PERSONAL_OWNER_ID,
                project_id=project,
                video_id=None,
                base_revision=None,
                request_digest=digest,
                input={},
                idempotency_key=None,
            ).job

        old = submit("a" * 64)
        runtime.job_store.request_cancel(old.id)
        newer = submit("b" * 64)

        with pytest.raises(AppError) as refused:
            jobs.retry(old.id)
        assert refused.value.code == "job_running"
        assert refused.value.detail == {"job_id": newer.id}
        assert runtime.job_store.get(old.id).state is JobState.cancelled

        runtime.job_store.request_cancel(newer.id)
        retried = jobs.retry(old.id)
        assert retried.id == old.id
        assert retried.state is JobState.queued
        assert retried.attempt == 2
    finally:
        runtime.close()
