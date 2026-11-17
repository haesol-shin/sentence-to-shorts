"""Fallback stores used while the SQLite and file implementations are missing.

Every method raises NotImplementedError instead of pretending to persist data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.ports import AppSettings
from app.schemas.api import ActivitySpan, Metrics
from app.schemas.artifact import Artifact, ArtifactKind
from app.schemas.change import ChangePlan
from app.schemas.job import Job, JobError
from app.schemas.preset import Preset
from app.schemas.project import Project
from app.schemas.video import RevisionInfo, Video


class UnavailableProjectStore:
    """ProjectStore placeholder. The SQLite implementation replaces it."""

    def new_id(self, prefix: str) -> str:
        raise NotImplementedError("storage")

    def put_project(self, project: Project) -> None:
        raise NotImplementedError("storage")

    def get_project(self, project_id: str) -> Project:
        raise NotImplementedError("storage")

    def list_projects(self, owner_id: str) -> list[Project]:
        raise NotImplementedError("storage")

    def delete_project(self, project_id: str) -> None:
        raise NotImplementedError("storage")

    def append_revision(self, video: Video) -> Video:
        raise NotImplementedError("storage")

    def get_video(self, video_id: str, revision: int | None = None) -> Video:
        raise NotImplementedError("storage")

    def list_revisions(self, video_id: str) -> list[RevisionInfo]:
        raise NotImplementedError("storage")

    def put_change(self, plan: ChangePlan) -> None:
        raise NotImplementedError("storage")

    def get_change(self, change_id: str) -> ChangePlan:
        raise NotImplementedError("storage")

    def list_changes(self, video_id: str) -> list[ChangePlan]:
        raise NotImplementedError("storage")

    def put_preset(self, preset: Preset) -> None:
        raise NotImplementedError("storage")

    def list_presets(self, project_id: str) -> list[Preset]:
        raise NotImplementedError("storage")

    def add_activity(self, video_id: str, spans: list[ActivitySpan]) -> None:
        raise NotImplementedError("storage")

    def metrics(self, video_id: str) -> Metrics:
        raise NotImplementedError("storage")


class UnavailableJobStore:
    """JobStore placeholder. The SQLite implementation replaces it."""

    def create(self, job: Job) -> Job:
        raise NotImplementedError("storage")

    def get(self, job_id: str) -> Job:
        raise NotImplementedError("storage")

    def claim(self, queue: str) -> Job | None:
        raise NotImplementedError("storage")

    def progress(self, job_id: str, attempt: int, progress: dict[str, Any]) -> None:
        raise NotImplementedError("storage")

    def stage(self, job_id: str, attempt: int, record: dict[str, Any]) -> None:
        raise NotImplementedError("storage")

    def checkpoint(self, job_id: str, attempt: int, cp: dict[str, Any]) -> None:
        raise NotImplementedError("storage")

    def usage(self, job_id: str, attempt: int, usage: dict[str, Any]) -> None:
        raise NotImplementedError("storage")

    def usage_event(self, job_id: str, attempt: int, event: dict[str, Any]) -> None:
        raise NotImplementedError("storage")

    def finish(
        self,
        job_id: str,
        attempt: int,
        state: str,
        result: dict[str, Any] | None,
        error: JobError | None,
        partial: bool,
    ) -> bool:
        raise NotImplementedError("storage")

    def request_cancel(self, job_id: str) -> Job:
        raise NotImplementedError("storage")

    def requeue(self, job_id: str) -> Job:
        raise NotImplementedError("storage")

    def unfinished(self) -> list[Job]:
        raise NotImplementedError("storage")


class UnavailableArtifactStore:
    """ArtifactStore placeholder. The file implementation replaces it."""

    def find(self, owner_id: str, cache_key: str) -> Artifact | None:
        raise NotImplementedError("storage")

    def get(self, owner_id: str, artifact_id: str) -> Artifact:
        raise NotImplementedError("storage")

    def publish(
        self,
        owner_id: str,
        kind: ArtifactKind,
        cache_key: str,
        tmp: Path,
        media: dict[str, Any],
        job_id: str | None,
    ) -> Artifact:
        raise NotImplementedError("storage")

    def path(self, artifact_id: str) -> Path:
        raise NotImplementedError("storage")

    def download_path(self, owner_id: str, video_id: str, kind: str) -> Path:
        raise NotImplementedError("storage")

    def job_dir(self, job_id: str) -> Path:
        raise NotImplementedError("storage")

    def hold(self, artifact_ids: list[str], holder: str) -> None:
        raise NotImplementedError("storage")

    def release(self, holder: str) -> None:
        raise NotImplementedError("storage")

    def sweep(self) -> int:
        raise NotImplementedError("storage")


def create_project_store(settings: AppSettings) -> UnavailableProjectStore:
    return UnavailableProjectStore()


def create_job_store(settings: AppSettings) -> UnavailableJobStore:
    return UnavailableJobStore()


def create_artifact_store(settings: AppSettings) -> UnavailableArtifactStore:
    return UnavailableArtifactStore()
