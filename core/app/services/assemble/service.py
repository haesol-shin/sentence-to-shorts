"""Final assembly and subtitle contract."""

from __future__ import annotations

from pathlib import Path

from app.ports import AppSettings, JobContext, MediaPort, ServiceDeps
from app.schemas.artifact import Timing
from app.schemas.video import Video


class AssembleService:
    def __init__(self, media: MediaPort) -> None:
        self.media = media

    def final(self, clips: list[Path], mix: Path, *, ctx: JobContext) -> Path:
        raise NotImplementedError

    def srt(self, video: Video, timings: list[Timing]) -> str:
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> AssembleService:
    return AssembleService(deps.media)


__all__ = ["AssembleService", "create"]
