"""Parent PNG and WAV validators on synthetic bytes (CONTRACTS 9.4)."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image

from app.tools.sandbox import validate_png
from app.tools.sandbox.validate_png import PngRejected, check_png
from app.tools.sandbox.validate_wav import WavRejected, check_wav
from tests.sandbox.conftest import rgba_png, tone_wav_bytes

PNG_LIMITS = {"max_side": 1920, "max_bytes": 8 * 1024 * 1024}
WAV_LIMITS = {"max_ms": 16000, "max_bytes": 1536 * 1024}


def _chunk_types(data: bytes) -> list[bytes]:
    types = []
    position = 8
    while position < len(data):
        length = int.from_bytes(data[position : position + 4], "big")
        types.append(data[position + 4 : position + 8])
        position += 12 + length
    return types


def _pixels(data: bytes) -> tuple[str, tuple[int, int], bytes]:
    with Image.open(io.BytesIO(data)) as image:
        return image.mode, image.size, image.tobytes()


def test_17_png_is_reencoded_without_extra_chunks() -> None:
    source = rgba_png(extra=[(b"tEXt", b"Comment\x00synthetic"), (b"iCCP", b"x\x00\x00")])
    checked = check_png(source, **PNG_LIMITS)
    assert (checked.width, checked.height) == (4, 3)
    assert _chunk_types(checked.data) == [b"IHDR", b"IDAT", b"IEND"]
    assert _pixels(checked.data) == _pixels(rgba_png())
    assert check_png(checked.data, **PNG_LIMITS).data == checked.data


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"GIF89a" + b"\x00" * 64, "signature"),
        (rgba_png()[:-4] + b"\x00\x00\x00\x00", "CRC"),
        (rgba_png() + b"\x00", "IEND"),
        (rgba_png(color_type=2), "RGBA"),
        (rgba_png(extra=[(b"ZZZZ", b"")]), "critical"),
        (rgba_png(raw=b"\x00" * 10), "decode"),
        (rgba_png(raw=(b"\x07" + b"\x00" * 16) * 3), "decode"),
    ],
)
def test_17_png_validator_rejects_malformed_files(data: bytes, reason: str) -> None:
    with pytest.raises(PngRejected, match=reason):
        check_png(data, **PNG_LIMITS)


def test_17_oversized_png_is_rejected_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    def never_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Pillow opened an image whose IHDR is over the limit")

    monkeypatch.setattr(validate_png.Image, "open", never_open)
    header = struct.pack(">IIBBBBB", 30000, 30000, 8, 6, 0, 0, 0)
    crc = zlib.crc32(b"IHDR" + header) & 0xFFFFFFFF
    data = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + header
        + struct.pack(">I", crc)
        + rgba_png()[33:]
    )
    with pytest.raises(PngRejected, match="side limit"):
        check_png(data, **PNG_LIMITS)


def test_17_png_decode_reads_only_the_declared_pixels() -> None:
    bomb = zlib.compress(b"\x00" * (64 * 1024 * 1024))
    data = rgba_png(width=4, height=3)
    start = data.index(b"IDAT") - 4
    end = data.index(b"IEND") - 4
    idat = struct.pack(">I", len(bomb)) + b"IDAT" + bomb
    idat += struct.pack(">I", zlib.crc32(b"IDAT" + bomb) & 0xFFFFFFFF)
    checked = check_png(data[:start] + idat + data[end:], **PNG_LIMITS)
    assert _pixels(checked.data) == ("RGBA", (4, 3), b"\x00" * 48)


def test_17_png_over_the_byte_limit_is_rejected() -> None:
    with pytest.raises(PngRejected, match="over"):
        check_png(rgba_png(), max_side=1920, max_bytes=16)


def test_17_wav_is_measured_in_tenths() -> None:
    checked = check_wav(tone_wav_bytes(duration_ms=1000, amplitude=0.2), **WAV_LIMITS)
    assert checked.duration_ms == 1000
    assert checked.frames == 44100
    assert checked.sample_peak_dbfs_x10 == -140
    assert checked.loudness_lufs_x10 is not None
    assert -185 <= checked.loudness_lufs_x10 <= -160


def test_17_silent_wav_has_no_peak_or_loudness() -> None:
    checked = check_wav(tone_wav_bytes(duration_ms=600, amplitude=0.0), **WAV_LIMITS)
    assert checked.sample_peak_dbfs_x10 is None
    assert checked.loudness_lufs_x10 is None


def _with_list_chunk(data: bytes) -> bytes:
    body = data[12:] + b"LIST" + (4).to_bytes(4, "little") + b"INFO"
    return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WAVE" + body


def _data_before_fmt(data: bytes) -> bytes:
    fmt_chunk = data[12:36]
    return data[:12] + data[36:] + fmt_chunk


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"RIFF" + (40).to_bytes(4, "little") + b"WAVX" + b"\x00" * 36, "WAVE"),
        (tone_wav_bytes(channels=2), "mono"),
        (tone_wav_bytes(rate=22050), "44100"),
        (_with_list_chunk(tone_wav_bytes()), "not allowed"),
        (tone_wav_bytes()[:-1], "RIFF size"),
        (_data_before_fmt(tone_wav_bytes()), "before the fmt"),
    ],
)
def test_17_wav_validator_rejects_malformed_files(data: bytes, reason: str) -> None:
    with pytest.raises(WavRejected, match=reason):
        check_wav(data, **WAV_LIMITS)


def test_17_wav_over_the_byte_limit_is_rejected() -> None:
    with pytest.raises(WavRejected, match="over 1000"):
        check_wav(tone_wav_bytes(), max_ms=16000, max_bytes=1000)


def test_17_wav_over_the_length_limit_is_rejected() -> None:
    with pytest.raises(WavRejected, match="over 16000 ms"):
        check_wav(tone_wav_bytes(duration_ms=17000), max_ms=16000, max_bytes=4 * 1024 * 1024)
