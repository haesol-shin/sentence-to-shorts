"""Artifact byte serving with Range support."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.routers.deps import runtime

MEDIA_TYPES = {
    ".png": "image/png",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".srt": "application/x-subrip",
    ".json": "application/json",
}

router = APIRouter()


@router.get("/artifacts/{aid}", operation_id="getArtifact")
def get_artifact(request: Request, aid: str) -> FileResponse:
    path = runtime(request).artifact_store.path(aid)
    media_type = MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media_type)
