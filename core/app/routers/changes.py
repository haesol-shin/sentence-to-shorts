"""Change plan read, preview, apply and reject endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request

from app.ports import canonical_digest
from app.routers.deps import runtime
from app.schemas.api import BaseRevision, Job
from app.schemas.change import ChangePlan
from app.schemas.job import JobKind
from app.schemas.video import Video

router = APIRouter()


@router.get("/changes/{cid}", operation_id="getChange", response_model=ChangePlan)
def get_change(request: Request, cid: str) -> ChangePlan:
    return runtime(request).project_store.get_change(cid)


@router.post(
    "/changes/{cid}/preview",
    operation_id="previewChange",
    response_model=Job,
    status_code=202,
)
def preview_change(
    request: Request,
    cid: str,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    app = runtime(request)
    plan = app.project_store.get_change(cid)
    return app.submitter.submit(
        JobKind.preview,
        project_id=None,
        video_id=plan.video_id,
        base_revision=plan.base_revision,
        request_digest=canonical_digest({}),
        input={},
        idempotency_key=idempotency_key,
    )


@router.post("/changes/{cid}/apply", operation_id="applyChange", response_model=Video)
def apply_change(
    request: Request,
    cid: str,
    body: BaseRevision,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Video:
    app = runtime(request)
    plan = app.project_store.get_change(cid)
    return app.services.project.commit(plan, body.base_revision)


@router.post(
    "/changes/{cid}/reject",
    operation_id="rejectChange",
    response_model=ChangePlan,
)
def reject_change(
    request: Request,
    cid: str,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChangePlan:
    app = runtime(request)
    plan = app.project_store.get_change(cid)
    plan.status = "rejected"
    app.project_store.put_change(plan)
    return plan
