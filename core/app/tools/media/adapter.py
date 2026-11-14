"""Media adapter boundary. The ffmpeg implementation lands with the media task."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.ports import (
    AppSettings,
    CancelToken,
    MediaInfo,
    MixPlan,
)


class MediaAdapter:
    def encode_frames(
        self,
        frames: Iterable[bytes],
        *,
        width: int,
        height: int,
        fps: int,
        out: Path,
        cancel: CancelToken,
    ) -> MediaInfo:
        raise NotImplementedError

    def mix(self, plan: MixPlan, *, out: Path, cancel: CancelToken) -> MediaInfo:
        raise NotImplementedError

    def mux_concat(
        self, clips: list[Path], audio: Path, *, out: Path, cancel: CancelToken
    ) -> MediaInfo:
        raise NotImplementedError

    def decode_audio(
        self,
        src: Path,
        *,
        out: Path,
        sample_rate: int,
        channels: int,
        max_ms: int,
        cancel: CancelToken,
    ) -> MediaInfo:
        raise NotImplementedError

    def extract_frames(
        self,
        src: Path,
        *,
        every_ms: int,
        max_frames: int,
        max_side: int,
        out_dir: Path,
        cancel: CancelToken,
    ) -> list[Path]:
        raise NotImplementedError

    def extract_audio(
        self, src: Path, *, out: Path, max_ms: int, cancel: CancelToken
    ) -> MediaInfo:
        raise NotImplementedError

    def probe(self, src: Path) -> MediaInfo:
        raise NotImplementedError


def create(settings: AppSettings) -> MediaAdapter:
    raise NotImplementedError("tools/media")


def create_skeleton(settings: AppSettings) -> MediaAdapter:
    """Fixture-profile placeholder; every call still reports not implemented."""
    return MediaAdapter()
