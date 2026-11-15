"""Catalog listing, manifests and package media."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.routers.deps import runtime
from app.schemas.api import CatalogItem, CatalogList, CatalogManifest
from app.schemas.bgm_entry import BuiltinBgm, SfxEntry
from app.schemas.style_manifest import StyleManifest
from app.schemas.voice_manifest import VoiceManifest

router = APIRouter()

MEDIA_TYPES = {".png": "image/png", ".wav": "audio/wav", ".ogg": "audio/ogg"}


def _media_file(manifest: object, name: str) -> tuple[Path, str] | None:
    relative: str | None = None
    if isinstance(manifest, VoiceManifest):
        relative = manifest.sample.file
    elif isinstance(manifest, StyleManifest):
        relative = manifest.preview
    elif isinstance(manifest, (BuiltinBgm, SfxEntry)):
        relative = manifest.file
    if relative is None or Path(relative).name != name:
        return None
    media_type = MEDIA_TYPES.get(Path(relative).suffix)
    if media_type is None:
        return None
    return Path(relative), media_type


def _page(items: list[CatalogItem], cursor: str | None, limit: int) -> CatalogList:
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    window = items[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(items) else None
    return CatalogList(items=window, next_cursor=next_cursor)


@router.get("/catalog/{kind}", operation_id="listCatalog", response_model=CatalogList)
def list_catalog(
    request: Request,
    kind: str,
    video_id: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CatalogList:
    app = runtime(request)
    video = app.project_store.get_video(video_id) if video_id else None
    items = app.catalog.list(kind, video=video)
    if q:
        needle = q.casefold()
        items = [
            item
            for item in items
            if needle in item.label.ko.casefold() or needle in item.label.en.casefold()
        ]
    return _page(items, cursor, limit)


@router.get(
    "/catalog/{kind}/{item_id}",
    operation_id="getCatalogItem",
    response_model=CatalogManifest,
)
def get_catalog_item(request: Request, kind: str, item_id: str) -> Any:
    return runtime(request).catalog.get(kind, item_id)


@router.get("/catalog/{kind}/{item_id}/media/{name}", operation_id="getCatalogMedia")
def get_catalog_media(
    request: Request, kind: str, item_id: str, name: str
) -> FileResponse:
    app = runtime(request)
    manifest = app.catalog.get(kind, item_id)
    found = _media_file(manifest, name)
    if found is None:
        raise HTTPException(status_code=404, detail="catalog media not found")
    relative, media_type = found
    ref = app.catalog.pin(kind, item_id)
    path = app.catalog.package_dir(kind, ref) / relative
    return FileResponse(path, media_type=media_type)


@router.get("/bgm/{item_id}/audio", operation_id="getBgmAudio")
def get_bgm_audio(request: Request, item_id: str) -> FileResponse:
    app = runtime(request)
    manifest = app.catalog.get("bgm", item_id)
    if not isinstance(manifest, BuiltinBgm):
        raise HTTPException(status_code=404, detail="bgm audio not found")
    ref = app.catalog.pin("bgm", item_id)
    path = app.catalog.package_dir("bgm", ref) / manifest.file
    media_type = MEDIA_TYPES.get(Path(manifest.file).suffix, "application/octet-stream")
    return FileResponse(path, media_type=media_type)
