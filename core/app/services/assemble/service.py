"""Final assembly, the subtitle file and attribution text.

Scene clips of one spec join by stream copy, so no frame is encoded twice, and
the mix joins as AAC: the only place sound enters the video. Subtitle times sit
on the clip frame clock, the same clock the mix uses.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app.ports import (
    FPS,
    AppError,
    AppSettings,
    JobContext,
    MediaPort,
    ServiceDeps,
    scene_starts_ms,
)
from app.schemas.artifact import Timing
from app.schemas.bgm_entry import BgmEntry, BuiltinBgm, SfxEntry, TypingSoundEntry
from app.schemas.common import Language
from app.schemas.video import Video

CLIP_SPEC = (1080, 1920, FPS)
"""Width, height and frame rate every clip must share (CONTRACTS 12)."""

FINAL_DIR = "final"


def _srt_time(ms: int) -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _srt_text(text: str) -> str:
    """One cue body: line breaks kept, blank lines removed so the cue does not end early."""
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


class AssembleService:
    def __init__(self, media: MediaPort) -> None:
        self.media = media

    def final(self, clips: list[Path], mix: Path, *, ctx: JobContext) -> Path:
        """Join silent clips of one spec by stream copy and add the mix as AAC."""
        ctx.cancel.raise_if_set()
        if not clips:
            raise AppError("media_invalid_input", detail={"reason": "no_clips"})
        for index, clip in enumerate(clips):
            info = self.media.probe(clip)
            if (info.width, info.height, info.fps) != CLIP_SPEC:
                raise AppError(
                    "media_invalid_input", detail={"reason": "clip_spec", "index": index}
                )
            if info.sample_rate is not None:
                raise AppError(
                    "media_invalid_input", detail={"reason": "clip_has_audio", "index": index}
                )
        if self.media.probe(mix).sample_rate is None:
            raise AppError("media_invalid_input", detail={"reason": "mix_without_audio"})
        out = ctx.job_dir / FINAL_DIR / "final.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        self.media.mux_concat(clips, mix, out=out, cancel=ctx.cancel)
        return out

    def srt(self, video: Video, timings: list[Timing]) -> str:
        """Every line as one cue with its display text, timed like the video."""
        if [timing.scene_id for timing in timings] != list(video.scene_order):
            raise AppError("timing_mismatch", detail={"reason": "scene_order"})
        cues: list[str] = []
        starts, _ = scene_starts_ms(timings)
        for start, timing in zip(starts, timings, strict=True):
            scene = video.scenes[timing.scene_id]
            texts = {line.id: line.display_text for line in scene.lines}
            if [line.line_id for line in timing.lines] != list(texts):
                raise AppError("timing_mismatch", detail={"scene_id": scene.id})
            for line in timing.lines:
                cues.append(
                    f"{len(cues) + 1}\n"
                    f"{_srt_time(start + line.start_ms)} --> {_srt_time(start + line.end_ms)}\n"
                    f"{_srt_text(texts[line.line_id])}\n"
                )
        return "\n".join(cues)

    def attributions(
        self, entries: Sequence[BgmEntry | SfxEntry | TypingSoundEntry], language: Language
    ) -> list[str]:
        """Attribution lines for the CC BY tracks and effects a video uses, in order.

        A license's own attribution text in ``language`` wins; otherwise the line
        names the title, author, license and source. Other licenses need no line.
        """
        lines: list[str] = []
        for entry in entries:
            if not isinstance(entry, (BuiltinBgm, SfxEntry, TypingSoundEntry)):
                continue
            license_ = entry.license
            if not license_.spdx.upper().startswith("CC-BY"):
                continue
            if license_.attribution is not None:
                line = getattr(license_.attribution, language.value)
            else:
                title = getattr(entry.label, language.value)
                line = f"\"{title}\" - {license_.author}, {license_.spdx}, {license_.source_url}"
            if line not in lines:
                lines.append(line)
        return lines


def create(settings: AppSettings, deps: ServiceDeps) -> AssembleService:
    return AssembleService(deps.media)


__all__ = ["AssembleService", "create"]
