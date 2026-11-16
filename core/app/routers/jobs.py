"""Job listing, status, cancel and retry endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Request

from app.ports import AppError
from app.routers.deps import runtime
from app.schemas.api import JobList
from app.schemas.job import Job, JobState

router = APIRouter()


@router.get("/jobs", operation_id="listJobs", response_model=JobList)
def list_jobs(
    request: Request,
    video_id: str | None = None,
    state: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> JobList:
    try:
        wanted = None if state is None else JobState(state)
    except ValueError:
        raise AppError("validation_failed", detail={"field": "state"}) from None
    jobs = runtime(request).submitter.find(video_id=video_id, state=wanted)
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    window = jobs[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(jobs) else None
    return JobList(items=window, next_cursor=next_cursor)


@router.get("/jobs/{jid}", operation_id="getJob", response_model=Job)
def get_job(request: Request, jid: str) -> Job:
    return runtime(request).job_store.get(jid)


@router.post(
    "/jobs/{jid}/cancel",
    operation_id="cancelJob",
    response_model=Job,
    status_code=202,
)
def cancel_job(request: Request, jid: str) -> Job:
    app = runtime(request)
    job = app.job_store.request_cancel(jid)
    app.runner.discard_reference_upload(jid)
    return job


@router.post(
    "/jobs/{jid}/retry",
    operation_id="retryJob",
    response_model=Job,
    status_code=202,
)
def retry_job(
    request: Request,
    jid: str,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    app = runtime(request)
    if not app.runner.reference_source_available(jid):
        raise AppError("job_not_retryable")
    return app.submitter.retry(jid)
