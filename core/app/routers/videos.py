"""Video editing, generation gates and reference endpoints."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, Request, Response, UploadFile
from fastapi.responses import FileResponse

from app.ports import AppError, canonical_json
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
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import JobKind
from app.schemas.video import Video
from app.services.pipeline.dependencies import plan_change
from app.services.reference.links import platform_of

router = APIRouter()


def _submit(
    app: Any, kind: JobKind, body: Any, *, video_id: str | None, key: str | None
) -> Job:
    return app.submitter.submit(
        kind,
        owner_id=PERSONAL_OWNER_ID,
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


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@router.post(
    "/videos/{vid}/references",
    operation_id="uploadReference",
    response_model=Job,
    status_code=202,
)
async def upload_reference(
    request: Request,
    response: Response,
    vid: str,
    base_revision: Annotated[int, Form()],
    file: UploadFile = File(...),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    """Stage the bounded upload before queuing; only the private job input holds its path."""
    app = runtime(request)
    video = app.project_store.get_video(vid)
    if video.revision != base_revision:
        raise AppError("revision_conflict", detail={"current_revision": video.revision})
    if file.content_type and not (
        file.content_type.startswith("video/") or file.content_type == "application/octet-stream"
    ):
        raise AppError("unsupported_media")
    form = await request.form()
    if set(form) != {"base_revision", "file"} or not isinstance(form["base_revision"], str):
        raise AppError("validation_failed")
    fields = {"base_revision": form["base_revision"]}
    temporary, path = app.runner.stage_reference_upload()
    folder = path.parent
    _sync_directory(folder.parent)
    keep = False
    staged = temporary.open("xb")
    try:
        with staged:
            digest = hashlib.sha256()
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > app.settings.app.uploads.reference_max_bytes:
                    raise AppError("payload_too_large")
                staged.write(chunk)
                digest.update(chunk)
            if not total:
                raise AppError("validation_failed")
            staged.flush()
            os.fsync(staged.fileno())
        os.replace(temporary, path)
        _sync_directory(folder)
        text = digest.hexdigest().encode("ascii") + canonical_json(fields)
        job = app.submitter.submit(
            JobKind.reference,
            owner_id=PERSONAL_OWNER_ID,
            project_id=None,
            video_id=vid,
            base_revision=base_revision,
            request_digest=hashlib.sha256(text).hexdigest(),
            input={"base_revision": base_revision, "upload_path": str(path)},
            idempotency_key=idempotency_key,
        )
        keep = True
        saved = app.job_inputs.load(job.id)
        if saved is None:
            raise AppError("internal")
        if saved.get("upload_path") != str(path):
            keep = False
            response.status_code = 200
        return job
    finally:
        temporary.unlink(missing_ok=True)
        if not keep:
            path.unlink(missing_ok=True)
            _sync_directory(folder)


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
    app = runtime(request)
    if app.settings.deployment == "hosted":
        raise AppError("link_disabled")
    platform_of(body.url)
    return _submit(app, JobKind.reference, body, video_id=vid, key=idempotency_key)


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
    app = runtime(request)
    video = app.project_store.get_video(vid)
    path = app.artifact_store.download_path(video.owner_id, vid, kind)
    return FileResponse(path, filename=f"{vid}{path.suffix}")
