"""Video editing, generation gates and reference endpoints."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.caption_layout import (
    POSITIONS,
    caption_pair_fits,
    single_caption_fits,
    smallest_caption_size,
)
from app.ports import AppError, canonical_json
from app.routers.deps import request_digest, runtime
from app.schemas.api import (
    ActivityRequest,
    BaseRevision,
    CaptionLayout,
    CaptionLayoutPair,
    ChangeRequest,
    DraftRequest,
    Job,
    LinkRequest,
    MessageRequest,
    Metrics,
    PreviewRequest,
)
from app.schemas.change import ChangePlan
from app.schemas.common import PERSONAL_OWNER_ID, CatalogId, PinnedRef
from app.schemas.job import JobKind
from app.schemas.video import Video
from app.services.pipeline.dependencies import plan_change
from app.services.reference.links import platform_of

router = APIRouter()


def _submit(
    app: Any,
    response: Response,
    kind: JobKind,
    body: Any,
    *,
    video_id: str | None,
    key: str | None,
) -> Job:
    result = app.submitter.submit(
        kind,
        owner_id=PERSONAL_OWNER_ID,
        project_id=None,
        video_id=video_id,
        base_revision=getattr(body, "base_revision", None),
        request_digest=request_digest(body),
        input=body.model_dump(mode="json", by_alias=True),
        idempotency_key=key,
    )
    response.status_code = result.status
    return result.job


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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request), response, JobKind.draft, body, video_id=vid, key=idempotency_key
    )


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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request), response, JobKind.script, body, video_id=vid, key=idempotency_key
    )


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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request), response, JobKind.preview, body, video_id=vid, key=idempotency_key
    )


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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request), response, JobKind.chat, body, video_id=vid, key=idempotency_key
    )


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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request), response, JobKind.precheck, body, video_id=vid, key=idempotency_key
    )


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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return _submit(
        runtime(request), response, JobKind.generate, body, video_id=vid, key=idempotency_key
    )


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
        result = app.submitter.submit(
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
        saved = app.job_inputs.load(result.job.id)
        if saved is None:
            raise AppError("internal")
        if result.status == 200 and saved.get("upload_path") != str(path):
            keep = False
        response.status_code = result.status
        return result.job
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
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    app = runtime(request)
    if app.settings.deployment == "hosted":
        raise AppError("link_disabled")
    platform_of(body.url)
    return _submit(app, response, JobKind.reference, body, video_id=vid, key=idempotency_key)


@router.post(
    "/videos/{vid}/activity",
    operation_id="recordActivity",
    response_model=None,
    status_code=204,
)
def record_activity(
    request: Request,
    vid: str,
    body: ActivityRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> None:
    runtime(request).project_store.add_activity(vid, body.spans)


def _pinned_query(value: str | None) -> PinnedRef | None:
    """A pinned font reference sent as a JSON query value."""
    if value is None:
        return None
    try:
        return PinnedRef.model_validate_json(value)
    except ValidationError as error:
        raise AppError("validation_failed") from error


@router.get(
    "/videos/{vid}/caption-layout",
    operation_id="getCaptionLayout",
    response_model=CaptionLayout,
)
def get_caption_layout(
    request: Request,
    vid: str,
    font_id: Annotated[str | None, Query()] = None,
    extra_language: Annotated[CatalogId | None, Query()] = None,
    extra_font_id: Annotated[str | None, Query()] = None,
) -> CaptionLayout:
    app = runtime(request)
    settings = app.project_store.get_video(vid).settings
    caption = settings.caption
    layout = settings.format.layout
    template = app.catalog.get("template", layout.id, layout.revision)
    primary_ref = _pinned_query(font_id) or caption.font_id
    primary = app.catalog.get("font", primary_ref.id, primary_ref.revision)
    primary_px = smallest_caption_size(primary.pixel_size)
    place = caption.place
    saved_extra = caption.extra[0] if caption.extra else None
    language = extra_language or (saved_extra.language if saved_extra else None)
    if language is None:
        if place is not None:
            fits = [CaptionLayoutPair(primary=None, extra=None, fits=True)]
        else:
            fits = [
                CaptionLayoutPair(
                    primary=position,
                    extra=position,
                    fits=single_caption_fits(template, primary.pixel_size, position),
                )
                for position in POSITIONS
            ]
        return CaptionLayout(
            primary_px=primary_px,
            extra_px=None,
            place=place,
            pairs=fits,
        )

    app.catalog.get("caption_language", language)
    extra_ref = _pinned_query(extra_font_id) or (
        saved_extra.font_id if saved_extra else primary_ref
    )
    extra = app.catalog.get("font", extra_ref.id, extra_ref.revision)
    if place is not None:
        pairs = [
            CaptionLayoutPair(
                primary=None,
                extra=extra_position,
                fits=caption_pair_fits(
                    template, primary.pixel_size, caption.position,
                    extra.pixel_size, extra_position, place,
                ),
            )
            for extra_position in POSITIONS
        ]
    else:
        pairs = [
            CaptionLayoutPair(
                primary=primary_position,
                extra=extra_position,
                fits=caption_pair_fits(
                    template, primary.pixel_size, primary_position,
                    extra.pixel_size, extra_position,
                ),
            )
            for primary_position in POSITIONS
            for extra_position in POSITIONS
        ]
    return CaptionLayout(
        primary_px=primary_px,
        extra_px=smallest_caption_size(extra.pixel_size),
        place=place,
        pairs=pairs,
    )


@router.get("/videos/{vid}/metrics", operation_id="getMetrics", response_model=Metrics)
def get_metrics(request: Request, vid: str) -> Metrics:
    app = runtime(request)
    video = app.project_store.get_video(vid)
    metrics = app.project_store.metrics(vid)
    return metrics.model_copy(
        update={"cost_micro_usd": app.usage.video_cost(video.owner_id, vid)}
    )


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
