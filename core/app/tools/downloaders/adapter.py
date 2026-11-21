"""Link download adapter: the bundled yt-dlp behind ``DownloaderPort``.

The executable path comes from the runtime lock under the runtime folder; PATH is
never searched. A hosted deployment gets an adapter that refuses every link.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from app.ports import AppSettings, CancelToken
from app.tools.downloaders.ytdlp.downloader import YtDlpDownloader

RUNTIME_ITEM = "yt-dlp"
JS_RUNTIME_ITEM = "deno"

DownloaderAdapter = YtDlpDownloader


def _platform() -> tuple[str, str]:
    system = "windows" if sys.platform == "win32" else "linux"
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    return system, arch


def runtime_executable(settings: AppSettings) -> Path | None:
    """Absolute yt-dlp path from the runtime lock entry, or None when not locked."""
    lock = getattr(settings, "runtime", None)
    items = getattr(lock, "items", None) or []
    system, arch = _platform()
    for item in items:
        if item.id != RUNTIME_ITEM:
            continue
        for entry in item.files:
            if entry.os == system and entry.arch == arch:
                return (settings.runtime_dir / item.install_path / entry.file).resolve()
    return None


def runtime_deno(settings: AppSettings) -> Path | None:
    """Absolute path of the locked Deno that solves YouTube challenges, or None when not locked."""
    lock = getattr(settings, "runtime", None)
    system, _arch = _platform()
    for item in getattr(lock, "items", None) or []:
        if item.id == JS_RUNTIME_ITEM:
            name = "deno.exe" if system == "windows" else "deno"
            return (settings.runtime_dir / item.install_path / name).resolve()
    return None


def create(settings: AppSettings) -> DownloaderAdapter:
    """Without a locked yt-dlp and Deno for this platform every fetch fails with download_failed."""
    return YtDlpDownloader(
        runtime_executable(settings),
        deno=runtime_deno(settings),
        link_enabled=settings.deployment != "hosted",
    )


class SkeletonDownloaderAdapter:
    """Fixture-profile placeholder: every call reports not implemented."""

    def fetch(
        self,
        url: str,
        *,
        out_dir: Path,
        max_bytes: int,
        max_ms: int,
        cancel: CancelToken,
    ) -> Path:
        raise NotImplementedError("tools/downloaders skeleton")


def create_skeleton(settings: AppSettings) -> SkeletonDownloaderAdapter:
    return SkeletonDownloaderAdapter()
