"""Deterministic media builders shared by the media, sandbox and sound tests."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def tone_wav(
    path: Path,
    *,
    duration_ms: int = 500,
    sample_rate: int = 44100,
    channels: int = 1,
    frequency: float = 440.0,
) -> Path:
    frames = sample_rate * duration_ms // 1000
    payload = bytearray()
    for index in range(frames):
        sample = int(0.2 * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate))
        for _ in range(channels):
            payload += struct.pack("<h", sample)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    return path


def corrupt_wav(path: Path) -> Path:
    path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 16)
    return path


def bad_png(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"not-a-real-png")
    return path
