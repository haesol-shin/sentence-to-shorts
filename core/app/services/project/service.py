"""Project, revision and preset service contract."""

from __future__ import annotations

from app.ports import (
    AppSettings,
    CatalogPort,
    Issue,
    ProjectStore,
    ServiceDeps,
)
from app.schemas.api import CreateProjectRequest, CreateVideoRequest, PresetRequest
from app.schemas.change import ChangePlan, Op
from app.schemas.common import Origin
from app.schemas.preset import Preset
from app.schemas.project import Project
from app.schemas.settings import Settings
from app.schemas.video import Video


class ProjectService:
    def __init__(self, projects: ProjectStore, catalog: CatalogPort) -> None:
        self.projects = projects
        self.catalog = catalog

    def create_project(self, req: CreateProjectRequest) -> Project:
        raise NotImplementedError

    def create_video(self, project_id: str, req: CreateVideoRequest) -> Video:
        raise NotImplementedError

    def view(self, video_id: str) -> Video:
        raise NotImplementedError

    def apply_ops(self, video: Video, ops: list[Op], origin_default: Origin) -> Video:
        """Pure: apply ops to an in-memory video without writing any store."""
        raise NotImplementedError

    def validate(self, video: Video) -> list[Issue]:
        raise NotImplementedError

    def commit(self, plan: ChangePlan, base_revision: int) -> Video:
        raise NotImplementedError

    def undo(self, video_id: str, base_revision: int) -> Video:
        raise NotImplementedError

    def confirm_concept(self, video_id: str, base_revision: int) -> Video:
        raise NotImplementedError

    def confirm_script(self, video_id: str, base_revision: int) -> Video:
        raise NotImplementedError

    def confirm_scenes(self, video_id: str, base_revision: int) -> Video:
        raise NotImplementedError

    def pick_varied(
        self, project: Project, previous: list[Video], seed: int
    ) -> Settings:
        raise NotImplementedError

    def save_preset(self, project_id: str, req: PresetRequest) -> Preset:
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> ProjectService:
    return ProjectService(deps.project_store, deps.catalog)


__all__ = ["ProjectService", "create"]
