"""Reference transcription adapter boundary."""

from __future__ import annotations

from pathlib import Path

from app.ports import AppSettings, CancelToken, Segment
from app.tools.asr.faster_whisper.adapter import FasterWhisperTranscriber
from app.tools.asr.faster_whisper.adapter import create as create_faster_whisper

TranscriberAdapter = FasterWhisperTranscriber


def create(settings: AppSettings) -> TranscriberAdapter:
    return create_faster_whisper(settings)


class SkeletonTranscriberAdapter:
    """Fixture-profile placeholder: every call reports not implemented."""

    def transcribe(
        self, wav: Path, language: str | None, *, cancel: CancelToken
    ) -> list[Segment]:
        raise NotImplementedError("tools/asr skeleton")


def create_skeleton(settings: AppSettings) -> SkeletonTranscriberAdapter:
    return SkeletonTranscriberAdapter()
