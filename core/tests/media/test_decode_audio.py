"""decode_audio: the fixed demuxer list and the decoded length cap."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.ports import AppError
from tests.fixtures.media import tone_wav
from tests.media import ffmpeg
from tests.media.scenes import Token


def _sun_au(path: Path, frames: int = 22050) -> Path:
    """A valid Sun AU file: plain PCM in a container outside the decode list."""
    header = struct.pack(">4sIIIII", b".snd", 24, frames * 2, 3, 44100, 1)
    path.write_bytes(header + b"\x10\x00" * frames)
    return path


@ffmpeg.requires_ffmpeg
def test_14_decode_refuses_a_demuxer_outside_the_list(tmp_path: Path) -> None:
    upload = _sun_au(tmp_path / "upload.wav")
    assert ffmpeg.streams(upload)
    with pytest.raises(AppError) as caught:
        ffmpeg.adapter().decode_audio(
            upload, out=tmp_path / "out.wav", sample_rate=44100, channels=1,
            max_ms=10_000, cancel=Token(),
        )
    assert caught.value.code in {"media_failed", "media_unreadable"}
    assert not (tmp_path / "out.wav").exists()


@ffmpeg.requires_ffmpeg
def test_14_decode_converts_rate_and_channels(tmp_path: Path) -> None:
    src = tone_wav(tmp_path / "in.wav", duration_ms=800, sample_rate=22050, channels=2)
    info = ffmpeg.adapter().decode_audio(
        src, out=tmp_path / "out.wav", sample_rate=44100, channels=1, max_ms=10_000,
        cancel=Token(),
    )
    assert (info.sample_rate, info.channels) == (44100, 1)
    assert info.duration_ms is not None and abs(info.duration_ms - 800) <= 2
