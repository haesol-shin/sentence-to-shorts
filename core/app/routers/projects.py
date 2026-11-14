"""Project, video view, revision and preset endpoints."""

from __future__ import annotations

from typing import Annotated, TypeVar

from fastapi import APIRouter, Header, Query, Request

from app.routers.deps import runtime
from app.schemas.api import (
    CreateProjectRequest,
    CreateVideoRequest,
    PresetList,
    PresetRequest,
    ProjectList,
    ProjectSummary,
    RevisionList,
    VideoView,
)
from app.schemas.preset import Preset
from app.schemas.project import Project
from app.schemas.video import Video
from app.services.pipeline.dependencies import build_view

router = APIRouter()
OWNER_ID = "owner"
PageItem = TypeVar("PageItem")


def _page(
    items: list[PageItem], cursor: str | None, limit: int
) -> tuple[list[PageItem], str | None]:
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    window = items[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(items) else None
    return window, next_cursor


@router.post(
    "/projects",
    operation_id="createProject",
    response_model=Project,
    status_code=201,
)
def create_project(
    request: Request,
    body: CreateProjectRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Project:
    return runtime(request).services.project.create_project(body)


@router.get("/projects", operation_id="listProjects", response_model=ProjectList)
def list_projects(
    request: Request,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ProjectList:
    projects = runtime(request).project_store.list_projects(OWNER_ID)
    summaries = [
        ProjectSummary(
            id=project.id,
            title=project.title,
            updated_at=project.updated_at,
            video_count=len(project.video_ids),
        )
        for project in projects
    ]
    window, next_cursor = _page(summaries, cursor, limit)
    return ProjectList(items=window, next_cursor=next_cursor)


@router.get("/projects/{pid}", operation_id="getProject", response_model=Project)
def get_project(request: Request, pid: str) -> Project:
    return runtime(request).project_store.get_project(pid)


@router.delete(
    "/projects/{pid}",
    operation_id="deleteProject",
    response_model=None,
    status_code=204,
)
def delete_project(request: Request, pid: str) -> None:
    runtime(request).project_store.delete_project(pid)


@router.post(
    "/projects/{pid}/videos",
    operation_id="createVideo",
    response_model=Video,
    status_code=201,
)
def create_video(
    request: Request,
    pid: str,
    body: CreateVideoRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Video:
    return runtime(request).services.project.create_video(pid, body)


@router.get("/videos/{vid}", operation_id="getVideo", response_model=VideoView)
def get_video(request: Request, vid: str) -> VideoView:
    app = runtime(request)
    video = app.services.project.view(vid)
    build = build_view(video, app.services)
    return VideoView(video=video, build=build, open_jobs=[], pending_change=None)


@router.get(
    "/videos/{vid}/revisions",
    operation_id="listVideoRevisions",
    response_model=RevisionList,
)
def list_video_revisions(
    request: Request,
    vid: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> RevisionList:
    revisions = runtime(request).project_store.list_revisions(vid)
    window, next_cursor = _page(revisions, cursor, limit)
    return RevisionList(items=window, next_cursor=next_cursor)


@router.get(
    "/videos/{vid}/revisions/{revision}",
    operation_id="getVideoRevision",
    response_model=Video,
)
def get_video_revision(request: Request, vid: str, revision: int) -> Video:
    return runtime(request).project_store.get_video(vid, revision)


@router.post(
    "/projects/{pid}/presets",
    operation_id="createPreset",
    response_model=Preset,
    status_code=201,
)
def create_preset(
    request: Request,
    pid: str,
    body: PresetRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Preset:
    return runtime(request).services.project.save_preset(pid, body)


@router.get(
    "/projects/{pid}/presets",
    operation_id="listPresets",
    response_model=PresetList,
)
def list_presets(
    request: Request,
    pid: str,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PresetList:
    presets = runtime(request).project_store.list_presets(pid)
    window, next_cursor = _page(presets, cursor, limit)
    return PresetList(items=window, next_cursor=next_cursor)
