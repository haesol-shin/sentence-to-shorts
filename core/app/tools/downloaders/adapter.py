"""Link download adapter boundary."""

from __future__ import annotations

from pathlib import Path

from app.ports import AppSettings, CancelToken


class DownloaderAdapter:
    def fetch(
        self,
        url: str,
        *,
        out_dir: Path,
        max_bytes: int,
        max_ms: int,
        cancel: CancelToken,
    ) -> Path:
        raise NotImplementedError


def create(settings: AppSettings) -> DownloaderAdapter:
    raise NotImplementedError("tools/downloaders")


def create_skeleton(settings: AppSettings) -> DownloaderAdapter:
    """Fixture-profile placeholder; every call still reports not implemented."""
    return DownloaderAdapter()
