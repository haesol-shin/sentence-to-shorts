"""Job listing, status, cancel and retry endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Request

from app.routers.deps import runtime
from app.schemas.api import JobList
from app.schemas.job import Job

router = APIRouter()


@router.get("/jobs", operation_id="listJobs", response_model=JobList)
def list_jobs(
    request: Request,
    video_id: str | None = None,
    state: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> JobList:
    jobs = runtime(request).job_store.unfinished()
    if video_id:
        jobs = [job for job in jobs if job.video_id == video_id]
    if state:
        jobs = [job for job in jobs if job.state == state]
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
    return runtime(request).job_store.request_cancel(jid)


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
    return runtime(request).job_store.requeue(jid)
