"""Forced alignment adapter boundary."""

from __future__ import annotations

from pathlib import Path

from app.ports import AlignResult, AppSettings, CancelToken


class AlignerAdapter:
    def align(
        self,
        wav: Path,
        speech_text: str,
        display_text: str,
        language: str,
        *,
        cancel: CancelToken,
    ) -> AlignResult:
        raise NotImplementedError


def create(settings: AppSettings) -> AlignerAdapter:
    raise NotImplementedError("tools/align")


def create_skeleton(settings: AppSettings) -> AlignerAdapter:
    """Fixture-profile placeholder; every call still reports not implemented."""
    return AlignerAdapter()
