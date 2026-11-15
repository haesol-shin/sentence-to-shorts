"""Measurements of a reference video that the model cannot see or hear.

Scene count comes from picture cuts between sampled frames, the silence ratio
and the music estimate from loudness windows of the mono analysis audio. Both
are plain heuristics with fixed thresholds, so the same file gives the same
numbers. Frames are only compared as 16 by 16 RGB thumbnails, never kept.
"""

from __future__ import annotations

import math
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.ports import AppError, Segment

THUMB = 16
CUT_THRESHOLD = 32.0
"""Mean channel difference (0..255) between consecutive sampled frames that counts as a cut."""

WINDOW_MS = 100
SILENCE_DBFS = -50.0
SPEECH_MARGIN_MS = 250
BGM_MIN_WINDOWS = 10
BGM_MIN_RATIO = 0.15
"""Loud windows without speech: at least a second and this share of the audio."""

_SILENCE_RMS = 32768 * 10 ** (SILENCE_DBFS / 20)


@dataclass(frozen=True)
class AudioFacts:
    silence_ratio: float
    has_bgm: bool


def _thumbnail(path: Path) -> bytes:
    try:
        with Image.open(path) as image:
            return image.convert("RGB").resize((THUMB, THUMB)).tobytes()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise AppError("media_failed", detail={"step": "frame_decode"}) from error


def scene_count(frames: list[Path]) -> int:
    """One scene plus one per cut between consecutive frames."""
    previous: bytes | None = None
    cuts = 0
    for path in frames:
        current = _thumbnail(path)
        if previous is not None:
            difference = sum(abs(a - b) for a, b in zip(previous, current, strict=True))
            if difference / len(current) > CUT_THRESHOLD:
                cuts += 1
        previous = current
    return 1 + cuts


def _samples(wav: Path) -> tuple[array, int]:
    try:
        with wave.open(str(wav), "rb") as handle:
            if handle.getsampwidth() != 2:
                raise AppError("media_failed", detail={"step": "audio_format"})
            channels = handle.getnchannels()
            rate = handle.getframerate()
            data = array("h")
            data.frombytes(handle.readframes(handle.getnframes()))
    except (wave.Error, EOFError) as error:
        raise AppError("media_failed", detail={"step": "audio_decode"}) from error
    if channels > 1:
        data = data[::channels]
    return data, rate


def _spoken(index: int, segments: list[Segment]) -> bool:
    start = index * WINDOW_MS
    end = start + WINDOW_MS
    return any(
        item.start_ms - SPEECH_MARGIN_MS < end and start < item.end_ms + SPEECH_MARGIN_MS
        for item in segments
    )


def audio_facts(wav: Path | None, segments: list[Segment]) -> AudioFacts:
    """Silence ratio of the whole audio and whether sound without speech carries it.

    A video without an audio stream is all silence and has no music.
    """
    if wav is None:
        return AudioFacts(1.0, False)
    samples, rate = _samples(wav)
    size = max(1, rate * WINDOW_MS // 1000)
    windows = len(samples) // size
    if windows == 0:
        return AudioFacts(1.0, False)
    silent = 0
    loud_without_speech = 0
    for index in range(windows):
        chunk = samples[index * size : (index + 1) * size]
        rms = math.sqrt(sum(value * value for value in chunk) / size)
        if rms < _SILENCE_RMS:
            silent += 1
        elif not _spoken(index, segments):
            loud_without_speech += 1
    has_bgm = (
        loud_without_speech >= BGM_MIN_WINDOWS
        and loud_without_speech / windows >= BGM_MIN_RATIO
    )
    return AudioFacts(round(silent / windows, 3), has_bgm)
