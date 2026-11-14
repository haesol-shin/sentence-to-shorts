"""Voice estimation, synthesis and timing contract."""

from __future__ import annotations

from pathlib import Path

from app.ports import (
    AlignerPort,
    AppSettings,
    JobContext,
    ServiceDeps,
    TtsPort,
)
from app.schemas.artifact import Timing
from app.schemas.scene import Scene
from app.schemas.script import Line
from app.schemas.voice_manifest import VoiceManifest


class VoiceService:
    def __init__(self, tts: TtsPort, aligner: AlignerPort) -> None:
        self.tts = tts
        self.aligner = aligner

    def estimate_ms(self, line: Line, language: str) -> int:
        raise NotImplementedError

    def synthesize(
        self,
        voice: VoiceManifest,
        language: str,
        line: Line,
        *,
        ctx: JobContext,
    ) -> Path:
        raise NotImplementedError

    def timing(
        self,
        scene: Scene,
        caption_mode: str,
        wavs: dict[str, Path],
        *,
        ctx: JobContext,
    ) -> Timing:
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> VoiceService:
    return VoiceService(deps.tts, deps.aligner)


__all__ = ["VoiceService", "create"]
