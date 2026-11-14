"""Fixed deterministic tone engine for the fixture profile and tests."""

from __future__ import annotations

import hashlib
import math
import struct
import wave
from pathlib import Path

from app.ports import AppSettings, CancelToken, SynthResult, TtsEngineInfo, TtsPort
from app.schemas.voice_manifest import VoiceManifest

SAMPLE_RATE = 22050
BASE_FREQUENCY = 220.0
AMPLITUDE = 0.15
MS_PER_CHARACTER = 90
MIN_MS = 300


def tone_duration_ms(text: str) -> int:
    return max(MIN_MS, len(text) * MS_PER_CHARACTER)


def _frequency(text: str) -> float:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return BASE_FREQUENCY + digest[0] % 8 * 27.5


def write_tone(path: Path, text: str, duration_ms: int) -> int:
    frames = SAMPLE_RATE * duration_ms // 1000
    frequency = _frequency(text)
    step = 2.0 * math.pi * frequency / SAMPLE_RATE
    samples = bytearray()
    for index in range(frames):
        value = int(AMPLITUDE * 32767 * math.sin(step * index))
        samples += struct.pack("<h", value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(samples))
    return frames


class FixedWavTts(TtsPort):
    """Deterministic tone WAV proportional to the text length. Test profile only."""

    def info(self) -> TtsEngineInfo:
        digest = hashlib.sha256(b"fixed_wav-1").hexdigest()
        return TtsEngineInfo(
            engine_id="fixed_wav",
            runtime_digest=digest,
            sample_rate=SAMPLE_RATE,
            languages=("ko", "en"),
        )

    def ready(self) -> list[str]:
        return []

    def synthesize(
        self,
        text: str,
        language: str,
        voice: VoiceManifest,
        *,
        out_dir: Path,
        cancel: CancelToken,
    ) -> SynthResult:
        cancel.raise_if_set()
        out_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(f"{language}|{voice.id}|{text}".encode("utf-8")).hexdigest()[:16]
        path = out_dir / f"{key}.wav"
        duration_ms = tone_duration_ms(text)
        frames = write_tone(path, text, duration_ms)
        cancel.raise_if_set()
        return SynthResult(wav_path=path, duration_ms=frames * 1000 // SAMPLE_RATE)

    def close(self) -> None:
        return None


def create(settings: AppSettings) -> FixedWavTts:
    return FixedWavTts()
