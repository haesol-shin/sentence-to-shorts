"""Runtime preparation: download, verify and record Deno, Pyodide and models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from app.ports import AppSettings, CancelToken, DownloaderPort, JobStore
from app.schemas.job import Job


def prepare(
    settings: AppSettings,
    items: Sequence[Mapping[str, object]],
    downloader: DownloaderPort,
    *,
    cancel: CancelToken,
) -> list[str]:
    """Download missing runtime items, verify hashes and return prepared ids."""
    raise NotImplementedError


def installed_path(settings: AppSettings, item: Mapping[str, object]) -> Path:
    raise NotImplementedError


class RuntimeSetup:
    """Creates the background job that prepares missing runtime files."""

    def __init__(
        self, settings: AppSettings, downloader: DownloaderPort, jobs: JobStore
    ) -> None:
        self.settings = settings
        self.downloader = downloader
        self.jobs = jobs

    def submit_prepare(self, *, idempotency_key: str | None) -> Job:
        raise NotImplementedError


def create(
    settings: AppSettings, downloader: DownloaderPort, jobs: JobStore
) -> RuntimeSetup:
    return RuntimeSetup(settings, downloader, jobs)
