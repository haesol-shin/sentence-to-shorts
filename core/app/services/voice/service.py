"""Engine-independent voice work: expected length, per-line synthesis and timing.

The pipeline publishes every TTS WAV before it asks for the timing, so the
timing call receives the pinned voice and the published TTS refs. The service
reads those files back through the artifact store and copies the refs into the
timing, so the preview and the mp4 read one timing artifact over one set of
WAVs.
"""

from __future__ import annotations

import math
import wave
from collections.abc import Mapping
from pathlib import Path

from app.ports import (
    AlignerPort,
    AppError,
    AppSettings,
    ArtifactStore,
    JobContext,
    PhraseSpan,
    ServiceDeps,
    TtsPort,
)
from app.schemas.artifact import (
    AlignFallback,
    CaptionPhrase,
    Timing,
    TimingCaption,
    TimingLine,
)
from app.schemas.common import ArtifactRef, CaptionMode, Language, PinnedRef
from app.schemas.scene import Scene
from app.schemas.script import Line
from app.schemas.text import clusters
from app.schemas.voice_manifest import VoiceManifest

LINE_GAP_MS = 200
"""Silence between two lines of one scene, in milliseconds."""

SCENE_TAIL_MS = 400
"""Silence after the last line of a scene, in milliseconds."""

MIN_ESTIMATE_MS = 300
"""Shortest expected or display time, so a one-word line stays readable."""

CHARS_PER_SECOND: dict[str, float] = {"ko": 5.5, "en": 13.0}
"""Technical start values for the expected speech rate, by language.

They are replaced after the listening test in SPEC criterion 28. Characters are
counted without whitespace; a pause after a Korean word or an English space is
not part of the table.
"""

TTS_DIR = "tts"

READ_FRAMES = 65536
"""Frames read per chunk while checking that a WAV holds its declared data."""


def wav_duration_ms(path: Path) -> int:
    """Measured PCM WAV duration in milliseconds. No engine value is trusted.

    The header alone cannot prove the data: a truncated file keeps its declared
    frame count, so the data chunk must still hold those frames.
    """
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            frame_size = handle.getsampwidth() * handle.getnchannels()
            if frames <= 0 or rate <= 0 or frame_size <= 0:
                raise AppError("tts_failed", detail={"reason": "wav_empty"})
            remaining = frames
            while remaining:
                chunk = handle.readframes(min(remaining, READ_FRAMES))
                if not chunk:
                    break
                remaining -= len(chunk) // frame_size
    except (OSError, EOFError, wave.Error) as error:
        raise AppError("tts_failed", detail={"reason": "wav_unreadable"}) from error
    if remaining:
        raise AppError("tts_failed", detail={"reason": "wav_truncated"})
    return max(1, frames * 1000 // rate)


def _rate(language: str) -> float:
    try:
        return CHARS_PER_SECOND[language]
    except KeyError:
        raise ValueError(f"unsupported language: {language}") from None


def _estimate_text_ms(text: str, language: str) -> int:
    characters = sum(1 for character in text if not character.isspace())
    return max(MIN_ESTIMATE_MS, math.ceil(characters * 1000 / _rate(language)))


def _sentence(reason: AlignFallback | None = None) -> TimingCaption:
    return TimingCaption(mode_used=CaptionMode.sentence, fallback_reason=reason, phrases=[])


def typewriter_phrases(
    display_text: str, start_ms: int, shown_ms: int
) -> list[CaptionPhrase]:
    """One display span per grapheme cluster of ``display_text`` (CONTRACTS 11.2).

    The nth span starts at ``start_ms + floor(n * shown_ms / N)``. These spans are
    the display schedule, not an alignment result, so the render and the sound mix
    read the same character times.
    """
    spans = clusters(display_text)
    count = len(spans)
    if count == 0:
        return []
    return [
        CaptionPhrase(
            start_char=start,
            end_char=end,
            start_ms=start_ms + index * shown_ms // count,
            end_ms=start_ms + (index + 1) * shown_ms // count,
        )
        for index, (start, end) in enumerate(spans)
    ]


def _validated_phrases(
    phrases: list[PhraseSpan],
    display_text: str,
    speech_ms: int,
    offset_ms: int,
) -> list[CaptionPhrase] | None:
    """Return caption phrases, or None when the alignment does not map the line.

    A phrase must stay inside the display text and the line's speech, be ordered
    without overlap, and leave no non-space character of the display text
    unmapped. A broken mapping turns the line into a sentence caption instead of
    a guessed one. Returned times are on the scene clock, shifted by ``offset_ms``.
    """
    if not phrases:
        return None
    previous_end = 0
    covered = [False] * len(display_text)
    validated: list[CaptionPhrase] = []
    for span in phrases:
        if not 0 <= span.start_char < span.end_char <= len(display_text):
            return None
        if span.start_char < previous_end:
            return None
        if not 0 <= span.start_ms < span.end_ms <= speech_ms:
            return None
        for index in range(span.start_char, span.end_char):
            covered[index] = True
        previous_end = span.end_char
        validated.append(
            CaptionPhrase(
                start_char=span.start_char,
                end_char=span.end_char,
                start_ms=offset_ms + span.start_ms,
                end_ms=offset_ms + span.end_ms,
            )
        )
    for index, is_covered in enumerate(covered):
        if not is_covered and not display_text[index].isspace():
            return None
    return validated


class VoiceService:
    def __init__(self, tts: TtsPort, aligner: AlignerPort, artifacts: ArtifactStore) -> None:
        self.tts = tts
        self.aligner = aligner
        self.artifacts = artifacts

    def estimate_ms(self, line: Line, language: str) -> int:
        """Expected speech length before synthesis; never a measured value."""
        return _estimate_text_ms(line.speech_text, language)

    def synthesize(
        self,
        voice: VoiceManifest,
        language: str,
        line: Line,
        *,
        ctx: JobContext,
    ) -> Path:
        """Synthesize the spoken text and return the WAV in the job folder.

        ``display_text`` is not an input, so a screen-text-only edit keeps the
        same synthesized WAV and the pipeline computes the same cache key. A
        provider failure keeps its ``tts_failed`` or ``tts_timeout`` code.
        """
        ctx.cancel.raise_if_set()
        result = self.tts.synthesize(
            line.speech_text,
            language,
            voice,
            out_dir=ctx.job_dir / TTS_DIR,
            cancel=ctx.cancel,
        )
        wav_duration_ms(result.wav_path)
        ctx.cancel.raise_if_set()
        return result.wav_path

    def timing(
        self,
        scene: Scene,
        voice: PinnedRef,
        tts: Mapping[str, ArtifactRef],
        caption_mode: str,
        language: Language,
        *,
        ctx: JobContext,
    ) -> Timing:
        """Measure line times from the published TTS WAVs and pick each caption.

        ``voice`` and ``tts`` are copied into the timing, so preview and mp4 read
        the same artifact. ``language`` is the video language every caller passes:
        the aligner needs it for phrase captions, and typewriter lines use it for
        their display length and character spans.
        """
        mode = CaptionMode(caption_mode)
        lines: list[TimingLine] = []
        cursor = 0
        for index, line in enumerate(scene.lines):
            ctx.cancel.raise_if_set()
            ref = tts.get(line.id)
            if ref is None:
                raise AppError(
                    "tts_failed",
                    detail={"reason": "tts_missing", "line_id": line.id},
                )
            wav = self._wav(ref)
            speech_ms = wav_duration_ms(wav)
            start_ms = 0 if index == 0 else cursor + LINE_GAP_MS
            shown_ms = speech_ms
            if mode is CaptionMode.typewriter:
                shown_ms = max(
                    speech_ms, _estimate_text_ms(line.display_text, language)
                )
            caption = self._caption(
                line, wav, mode, language, speech_ms, start_ms, shown_ms, ctx
            )
            end_ms = start_ms + shown_ms
            lines.append(
                TimingLine(
                    line_id=line.id,
                    tts=ref,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    speech_ms=speech_ms,
                    caption=caption,
                )
            )
            cursor = end_ms
        ctx.cancel.raise_if_set()
        return Timing(
            schema_version=2,
            scene_id=scene.id,
            voice=voice,
            duration_ms=cursor + SCENE_TAIL_MS,
            lines=lines,
        )

    def _wav(self, ref: ArtifactRef) -> Path:
        """Resolve a published TTS ref to its file; a lost file is a TTS failure."""
        try:
            return self.artifacts.path(ref.id)
        except (KeyError, OSError) as error:
            raise AppError(
                "tts_failed",
                detail={"reason": "tts_missing", "artifact_id": ref.id},
            ) from error

    def _caption(
        self,
        line: Line,
        wav: Path,
        mode: CaptionMode,
        language: Language,
        speech_ms: int,
        start_ms: int,
        shown_ms: int,
        ctx: JobContext,
    ) -> TimingCaption:
        if mode is CaptionMode.sentence:
            return _sentence()
        if mode is CaptionMode.typewriter:
            return TimingCaption(
                mode_used=CaptionMode.typewriter,
                fallback_reason=None,
                phrases=typewriter_phrases(line.display_text, start_ms, shown_ms),
            )
        result = self.aligner.align(
            wav,
            line.speech_text,
            line.display_text,
            language,
            cancel=ctx.cancel,
        )
        if result.failure is not None:
            return _sentence(AlignFallback(result.failure))
        phrases = _validated_phrases(
            result.phrases or [], line.display_text, speech_ms, start_ms
        )
        if phrases is None:
            return _sentence(AlignFallback.align_failed)
        return TimingCaption(mode_used=CaptionMode.phrase, fallback_reason=None, phrases=phrases)


def create(settings: AppSettings, deps: ServiceDeps) -> VoiceService:
    return VoiceService(deps.tts, deps.aligner, deps.artifact_store)


__all__ = [
    "CHARS_PER_SECOND",
    "LINE_GAP_MS",
    "MIN_ESTIMATE_MS",
    "SCENE_TAIL_MS",
    "VoiceService",
    "create",
    "typewriter_phrases",
    "wav_duration_ms",
]
