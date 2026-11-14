"""Reference video ingestion and analysis contract."""

from __future__ import annotations

from pathlib import Path

from app.ports import (
    AppSettings,
    DownloaderPort,
    JobContext,
    LlmPort,
    MediaPort,
    ReferenceOutcome,
    ServiceDeps,
    TranscriberPort,
    UploadSource,
)
from app.schemas.job import Job
from app.schemas.video import Video


class ReferenceService:
    def __init__(
        self,
        downloader: DownloaderPort,
        media: MediaPort,
        transcriber: TranscriberPort,
        llm: LlmPort,
    ) -> None:
        self.downloader = downloader
        self.media = media
        self.transcriber = transcriber
        self.llm = llm

    def ingest(
        self, upload: Path | None, url: str | None, *, ctx: JobContext
    ) -> Path:
        raise NotImplementedError

    def submit_upload(
        self,
        video_id: str,
        base_revision: int,
        upload: UploadSource,
        idempotency_key: str | None,
    ) -> Job:
        raise NotImplementedError

    def analyze(
        self, source: Path, video: Video, *, ctx: JobContext
    ) -> ReferenceOutcome:
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> ReferenceService:
    return ReferenceService(
        deps.downloader, deps.media, deps.transcriber, deps.llm
    )


__all__ = ["ReferenceService", "create"]
