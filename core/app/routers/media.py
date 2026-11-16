"""Generated style, template and BGM endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, Request, UploadFile

from app.ports import UploadSource
from app.routers.deps import request_digest, runtime
from app.schemas.api import BgmCodeRequest, Job, StyleRequest, TemplateRequest
from app.schemas.common import Mood
from app.schemas.job import JobKind

router = APIRouter()


def _submit(
    app: Any,
    kind: JobKind,
    body: Any,
    *,
    video_id: str | None,
    project_id: str | None,
    key: str | None,
) -> Job:
    return app.submitter.submit(
        kind,
        project_id=project_id,
        video_id=video_id,
        base_revision=getattr(body, "base_revision", None),
        request_digest=request_digest(body),
        input=body.model_dump(mode="json", by_alias=True),
        idempotency_key=key,
    )


@router.post("/styles", operation_id="createStyle", response_model=Job, status_code=202)
def create_style(
    request: Request,
    body: StyleRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request),
        JobKind.style,
        body,
        video_id=body.video_id,
        project_id=None,
        key=idempotency_key,
    )


@router.post(
    "/templates",
    operation_id="createTemplate",
    response_model=Job,
    status_code=202,
)
def create_template(
    request: Request,
    body: TemplateRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request),
        JobKind.template,
        body,
        video_id=body.video_id,
        project_id=None,
        key=idempotency_key,
    )


@router.post(
    "/bgm/code",
    operation_id="createBgmCode",
    response_model=Job,
    status_code=202,
)
def create_bgm_code(
    request: Request,
    body: BgmCodeRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request),
        JobKind.bgm_code,
        body,
        video_id=None,
        project_id=body.project_id,
        key=idempotency_key,
    )


@router.post(
    "/bgm/uploads",
    operation_id="uploadBgm",
    response_model=Job,
    status_code=202,
)
async def upload_bgm(
    request: Request,
    project_id: Annotated[str, Form()],
    file: UploadFile = File(...),
    mood: Mood = Form(
        default_factory=lambda: Mood.calm,
        description="Defaults to calm when omitted.",
    ),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    """Validate upload metadata; submission integration is tracked separately."""
    return runtime(request).services.sound.submit_upload(
        project_id, UploadSource(file.filename, file.content_type, file.file), idempotency_key
    )
