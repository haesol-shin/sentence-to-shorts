"""Forced alignment adapter boundary.

app.yaml selects the aligner through `providers.adapters.aligner`. The selected
value `none` means that no aligner is wired for this build, so every call reports
`align_unavailable` and the voice service turns the line into a sentence caption.
Any other value is not implemented here and stays a startup failure.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.ports import AlignResult, AppSettings, CancelToken

NONE = "none"
"""The `providers.adapters.aligner` value that selects the unavailable aligner."""


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


class UnavailableAligner(AlignerAdapter):
    """Reports `align_unavailable` for every line. It never invents a time."""

    def runtime_digest(self) -> str:
        return hashlib.sha256(b"align-unavailable-1").hexdigest()

    def align(
        self,
        wav: Path,
        speech_text: str,
        display_text: str,
        language: str,
        *,
        cancel: CancelToken,
    ) -> AlignResult:
        cancel.raise_if_set()
        return AlignResult(phrases=None, failure="align_unavailable")


def selected_aligner(settings: AppSettings) -> str | None:
    providers = getattr(settings, "providers", None)
    return getattr(providers, "adapters", {}).get("aligner")


def create(settings: AppSettings) -> AlignerAdapter:
    if selected_aligner(settings) == NONE:
        return UnavailableAligner()
    raise NotImplementedError("tools/align")


def create_skeleton(settings: AppSettings) -> AlignerAdapter:
    """Fixture-profile placeholder; every call still reports not implemented."""
    return AlignerAdapter()
