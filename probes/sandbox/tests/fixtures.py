"""Fixtures shared by the probe unit tests."""

from __future__ import annotations

import io
import struct
import wave
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (
        struct.pack(">I", len(body))
        + kind
        + body
        + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    )


def make_png(width: int = 4, height: int = 4, color=(32, 64, 128)) -> bytes:
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def make_png_without_data(width: int = 4, height: int = 4) -> bytes:
    """A valid header and IEND with no IDAT, the shape a lying runner can send."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IEND", b"")


def make_png_with_corrupt_data(width: int = 4, height: int = 4) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", b"\x00\x01\x02\x03")
        + _chunk(b"IEND", b"")
    )


def _wav_bytes(chunks: list[tuple[bytes, bytes]]) -> bytes:
    body = b"WAVE"
    for chunk_id, payload in chunks:
        body += chunk_id + struct.pack("<I", len(payload)) + payload
        if len(payload) & 1:
            body += b"\x00"
    return b"RIFF" + struct.pack("<I", len(body)) + body


def make_wav(seconds: float = 1.0, rate: int = 44100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack("<h", 100) * int(rate * seconds))
    return buffer.getvalue()


def make_wav_without_frames() -> bytes:
    fmt = struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    return _wav_bytes([(b"fmt ", fmt), (b"data", b"")])


def make_wav_odd_data() -> bytes:
    fmt = struct.pack("<HHIIHH", 1, 1, 44100, 88200, 2, 16)
    return _wav_bytes([(b"fmt ", fmt), (b"data", b"\x01\x02\x03")])
