"""Change plan read, preview, apply and reject endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, Response

from app.ports import AppError, canonical_digest
from app.routers.deps import runtime
from app.schemas.api import BaseRevision, Job
from app.schemas.change import ChangePlan, ChangeStatus
from app.schemas.common import PERSONAL_OWNER_ID
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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    app = runtime(request)
    plan = app.project_store.get_change(cid)
    if plan.status is not ChangeStatus.proposed:
        raise AppError("change_stale")
    payload = {"change_id": plan.id}
    result = app.submitter.submit(
        JobKind.preview,
        owner_id=PERSONAL_OWNER_ID,
        project_id=None,
        video_id=plan.video_id,
        base_revision=plan.base_revision,
        request_digest=canonical_digest(payload),
        input=payload,
        idempotency_key=idempotency_key,
    )
    response.status_code = result.status
    return result.job


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
    if plan.status is ChangeStatus.rejected:
        return plan
    if plan.status is not ChangeStatus.proposed:
        raise AppError("change_stale")
    rejected = plan.model_copy(update={"status": ChangeStatus.rejected})
    app.project_store.put_change(rejected)
    return rejected
