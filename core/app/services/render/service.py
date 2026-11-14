"""Scene still and clip rendering contract."""

from __future__ import annotations

from pathlib import Path

from app.ports import (
    AppSettings,
    ArtifactStore,
    CatalogPort,
    JobContext,
    MediaPort,
    ServiceDeps,
)
from app.schemas.artifact import Timing
from app.schemas.video import Video


class RenderService:
    def __init__(
        self, media: MediaPort, artifacts: ArtifactStore, catalog: CatalogPort
    ) -> None:
        self.media = media
        self.artifacts = artifacts
        self.catalog = catalog

    def still(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
        timing: Timing | None,
        *,
        ctx: JobContext,
    ) -> Path:
        """Write a 540x960 PNG still to the job folder."""
        raise NotImplementedError

    def clip(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
        timing: Timing,
        *,
        ctx: JobContext,
    ) -> Path:
        """Write a silent mp4 clip to the job folder."""
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> RenderService:
    return RenderService(deps.media, deps.artifact_store, deps.catalog)


__all__ = ["RenderService", "create"]
