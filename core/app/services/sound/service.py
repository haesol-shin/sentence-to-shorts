"""BGM selection, upload import and mix contract."""

from __future__ import annotations

from pathlib import Path

from app.ports import (
    AppSettings,
    CatalogPort,
    JobContext,
    MediaPort,
    ServiceDeps,
    UploadSource,
)
from app.schemas.artifact import Timing
from app.schemas.bgm_entry import BgmEntry
from app.schemas.common import PinnedRef
from app.schemas.job import Job
from app.schemas.settings import Settings
from app.schemas.video import Video


class SoundService:
    def __init__(self, media: MediaPort, catalog: CatalogPort) -> None:
        self.media = media
        self.catalog = catalog

    def pick_bgm(
        self, settings: Settings, recent: list[str], seed: int
    ) -> PinnedRef:
        raise NotImplementedError

    def import_upload(
        self, src: Path, project_id: str, *, ctx: JobContext
    ) -> BgmEntry:
        raise NotImplementedError

    def submit_upload(
        self, project_id: str, upload: UploadSource, idempotency_key: str | None
    ) -> Job:
        raise NotImplementedError

    def mix(
        self,
        video: Video,
        timings: list[Timing],
        tts: dict[str, Path],
        *,
        ctx: JobContext,
    ) -> Path:
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> SoundService:
    return SoundService(deps.media, deps.catalog)


__all__ = ["SoundService", "create"]
