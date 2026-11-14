"""Reference transcription adapter boundary."""

from __future__ import annotations

from pathlib import Path

from app.ports import AppSettings, CancelToken, Segment


class TranscriberAdapter:
    def transcribe(
        self, wav: Path, language: str | None, *, cancel: CancelToken
    ) -> list[Segment]:
        raise NotImplementedError


def create(settings: AppSettings) -> TranscriberAdapter:
    raise NotImplementedError("tools/asr")


def create_skeleton(settings: AppSettings) -> TranscriberAdapter:
    """Fixture-profile placeholder; every call still reports not implemented."""
    return TranscriberAdapter()
