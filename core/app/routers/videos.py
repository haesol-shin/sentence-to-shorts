"""Video editing, generation gates and reference endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from fastapi.responses import FileResponse

from app.ports import AppError, UploadSource
from app.routers.deps import request_digest, runtime
from app.schemas.api import (
    ActivityRequest,
    BaseRevision,
    ChangeRequest,
    DraftRequest,
    Job,
    LinkRequest,
    MessageRequest,
    Metrics,
    PreviewRequest,
)
from app.schemas.change import ChangePlan
from app.schemas.job import JobKind
from app.schemas.video import Video
from app.services.pipeline.dependencies import plan_change

router = APIRouter()


def _submit(
    app: Any, kind: JobKind, body: Any, *, video_id: str | None, key: str | None
) -> Job:
    return app.submitter.submit(
        kind,
        project_id=None,
        video_id=video_id,
        base_revision=getattr(body, "base_revision", None),
        request_digest=request_digest(body),
        input=body.model_dump(mode="json", by_alias=True),
        idempotency_key=key,
    )


@router.post(
    "/videos/{vid}/draft",
    operation_id="createDraft",
    response_model=Job,
    status_code=202,
)
def create_draft(
    request: Request,
    vid: str,
    body: DraftRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(runtime(request), JobKind.draft, body, video_id=vid, key=idempotency_key)


@router.post(
    "/videos/{vid}/script",
    operation_id="runScript",
    response_model=Job,
    status_code=202,
)
def run_script(
    request: Request,
    vid: str,
    body: BaseRevision,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(runtime(request), JobKind.script, body, video_id=vid, key=idempotency_key)


@router.post(
    "/videos/{vid}/script/confirm",
    operation_id="confirmScript",
    response_model=Video,
)
def confirm_script(
    request: Request,
    vid: str,
    body: BaseRevision,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Video:
    return runtime(request).services.project.confirm_script(vid, body.base_revision)


@router.post(
    "/videos/{vid}/concept/confirm",
    operation_id="confirmConcept",
    response_model=Video,
)
def confirm_concept(
    request: Request,
    vid: str,
    body: BaseRevision,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Video:
    return runtime(request).services.project.confirm_concept(vid, body.base_revision)


@router.post(
    "/videos/{vid}/previews",
    operation_id="createPreviews",
    response_model=Job,
    status_code=202,
)
def create_previews(
    request: Request,
    vid: str,
    body: PreviewRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(runtime(request), JobKind.preview, body, video_id=vid, key=idempotency_key)


@router.post(
    "/videos/{vid}/scenes/confirm",
    operation_id="confirmScenes",
    response_model=Video,
)
def confirm_scenes(
    request: Request,
    vid: str,
    body: BaseRevision,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Video:
    return runtime(request).services.project.confirm_scenes(vid, body.base_revision)


@router.post(
    "/videos/{vid}/changes",
    operation_id="createChange",
    response_model=ChangePlan,
)
def create_change(
    request: Request,
    vid: str,
    body: ChangeRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ChangePlan:
    app = runtime(request)
    video = app.project_store.get_video(vid)
    if body.base_revision != video.revision:
        raise AppError("revision_conflict", detail={"current_revision": video.revision})
    plan = plan_change(video, body.ops, body.source, body.target, app.services)
    app.project_store.put_change(plan)
    if plan.requires_confirmation:
        return plan
    app.services.project.commit(plan, body.base_revision)
    return app.project_store.get_change(plan.id)


@router.post(
    "/videos/{vid}/messages",
    operation_id="sendMessage",
    response_model=Job,
    status_code=202,
)
def send_message(
    request: Request,
    vid: str,
    body: MessageRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(runtime(request), JobKind.chat, body, video_id=vid, key=idempotency_key)


@router.post("/videos/{vid}/undo", operation_id="undoVideo", response_model=Video)
def undo_video(
    request: Request,
    vid: str,
    body: BaseRevision,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Video:
    return runtime(request).services.project.undo(vid, body.base_revision)


@router.post(
    "/videos/{vid}/precheck",
    operation_id="runPrecheck",
    response_model=Job,
    status_code=202,
)
def run_precheck(
    request: Request,
    vid: str,
    body: BaseRevision,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(runtime(request), JobKind.precheck, body, video_id=vid, key=idempotency_key)


@router.post(
    "/videos/{vid}/generate",
    operation_id="generateVideo",
    response_model=Job,
    status_code=202,
)
def generate_video(
    request: Request,
    vid: str,
    body: BaseRevision,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(runtime(request), JobKind.generate, body, video_id=vid, key=idempotency_key)


@router.post(
    "/videos/{vid}/references",
    operation_id="uploadReference",
    response_model=Job,
    status_code=202,
)
async def upload_reference(
    request: Request,
    vid: str,
    base_revision: Annotated[int, Form()],
    file: UploadFile = File(...),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    """Multipart digest: SHA-256 of the file part, then canonical JSON of the other
    fields sorted by name (CONTRACTS 3). Streaming and hashing land with the jobs lane.
    """
    return runtime(request).services.reference.submit_upload(
        vid,
        base_revision,
        UploadSource(file.filename, file.content_type, file.file),
        idempotency_key,
    )


@router.post(
    "/videos/{vid}/references/link",
    operation_id="linkReference",
    response_model=Job,
    status_code=202,
)
def link_reference(
    request: Request,
    vid: str,
    body: LinkRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(runtime(request), JobKind.reference, body, video_id=vid, key=idempotency_key)


@router.post(
    "/videos/{vid}/activity",
    operation_id="recordActivity",
    response_model=None,
    status_code=204,
)
def record_activity(request: Request, vid: str, body: ActivityRequest) -> None:
    runtime(request).project_store.add_activity(vid, body.spans)


@router.get("/videos/{vid}/metrics", operation_id="getMetrics", response_model=Metrics)
def get_metrics(request: Request, vid: str) -> Metrics:
    return runtime(request).project_store.metrics(vid)


@router.get(
    "/videos/{vid}/download/{kind}",
    operation_id="downloadVideo",
    response_model=None,
)
def download_video(request: Request, vid: str, kind: str) -> FileResponse:
    path = runtime(request).artifact_store.download_path(vid, kind)
    return FileResponse(path, filename=f"{vid}{path.suffix}")
