"""ffmpeg MediaPort: argument safety, executable resolution and a real encode.

The encode test needs the bundled ffmpeg of the runtime lock. Point
``APP_TEST_FFMPEG`` at an absolute executable path to run it; it is skipped
otherwise so local runs stay pure Python.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ports import AppError
from app.tools.media import adapter as media
from app.tools.process import ProcessResult

PROBE_OUTPUT = (
    b"Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'file:out.mp4':\n"
    b"  Duration: 00:00:01.00, start: 0.000000, bitrate: 34 kb/s\n"
    b"  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive),"
    b" 1080x1920, 30 fps, 30 tbr, 15360 tbn (default)\n"
)


class Token:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


def _frames(count: int, width: int, height: int) -> list[bytes]:
    return [bytes((index * 8 % 256, 90, 200)) * (width * height) for index in range(count)]


def test_1_arguments_are_arrays_with_nostdin_and_whitelist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "ffmpeg"
    executable.write_bytes(b"")
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        stdin = kwargs.get("stdin_data")
        if stdin is not None:
            assert sum(len(chunk) for chunk in stdin) == 3 * 4 * 4 * 3
        return ProcessResult(tuple(argv), 0, b"", PROBE_OUTPUT, False, False, False, False, 1)

    monkeypatch.setattr(media, "run", fake_run)
    adapter = media.MediaAdapter(executable)
    out = tmp_path / "odd name; -i data:x.mp4"
    info = adapter.encode_frames(
        _frames(3, 4, 4), width=4, height=4, fps=30, out=out, cancel=Token()
    )
    assert (info.width, info.height, info.fps, info.duration_ms) == (1080, 1920, 30, 1000)
    for argv in calls:
        assert argv[0] == str(executable)
        assert argv[1] == "-nostdin"
        inputs = [index for index, value in enumerate(argv) if value == "-i"]
        assert inputs
        for index in inputs:
            whitelist = argv.index("-protocol_whitelist", max(0, index - 12))
            assert whitelist < index and argv[whitelist + 1] == "file,pipe"
            assert argv[index + 1] == "pipe:0" or argv[index + 1].startswith("file:")
    assert f"file:{out.resolve()}" in calls[0]


def test_1_frame_of_wrong_size_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = tmp_path / "ffmpeg"
    executable.write_bytes(b"")

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        list(kwargs["stdin_data"])
        raise AssertionError("unreachable")

    monkeypatch.setattr(media, "run", fake_run)
    with pytest.raises(ValueError, match="raw RGB24 frame"):
        media.MediaAdapter(executable).encode_frames(
            [b"\x00" * 5], width=4, height=4, fps=30, out=tmp_path / "x.mp4", cancel=Token()
        )


def test_1_missing_runtime_ffmpeg_reports_media_unavailable(tmp_path: Path) -> None:
    settings = SimpleNamespace(runtime=SimpleNamespace(items=[]), runtime_dir=tmp_path)
    adapter = media.create(settings)  # type: ignore[arg-type]
    with pytest.raises(AppError) as error:
        adapter.probe(tmp_path / "clip.mp4")
    assert error.value.code == "media_unavailable"


def test_1_runtime_lock_entry_gives_an_absolute_path(tmp_path: Path) -> None:
    system, arch = media._platform()
    entry = SimpleNamespace(os=system, arch=arch, file="ffmpeg-bin")
    item = SimpleNamespace(id="ffmpeg", install_path="ffmpeg", files=[entry])
    settings = SimpleNamespace(
        runtime=SimpleNamespace(items=[item]), runtime_dir=Path(os.path.relpath(tmp_path))
    )
    path = media.runtime_executable(settings)  # type: ignore[arg-type]
    assert path == (tmp_path / "ffmpeg" / "ffmpeg-bin").resolve()
    assert path is not None and path.is_absolute()


def test_1_relative_executable_is_refused() -> None:
    with pytest.raises(ValueError, match="absolute"):
        media.MediaAdapter(Path("ffmpeg"))


@pytest.mark.skipif(
    not os.environ.get("APP_TEST_FFMPEG"), reason="APP_TEST_FFMPEG names no ffmpeg executable"
)
def test_1_ffmpeg_encodes_30_raw_frames(tmp_path: Path) -> None:
    adapter = media.MediaAdapter(Path(os.environ["APP_TEST_FFMPEG"]))
    out = tmp_path / "clip.mp4"
    info = adapter.encode_frames(
        iter(_frames(30, 1080, 1920)), width=1080, height=1920, fps=30, out=out, cancel=Token()
    )
    assert out.stat().st_size > 0
    assert (info.width, info.height, info.fps, info.duration_ms) == (1080, 1920, 30, 1000)


def test_1_extracted_frames_are_only_this_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "ffmpeg"
    executable.write_bytes(b"")
    out_dir = tmp_path / "frames"
    out_dir.mkdir()
    for index in range(1, 4):
        (out_dir / f"frame_{index:04d}.png").write_bytes(b"old")

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        pattern = Path(argv[-1].removeprefix("file:"))
        (pattern.parent / "frame_0001.png").write_bytes(b"new")
        return ProcessResult(tuple(argv), 0, b"", b"", False, False, False, False, 1)

    monkeypatch.setattr(media, "run", fake_run)
    frames = media.MediaAdapter(executable).extract_frames(
        tmp_path / "in.mp4", every_ms=500, max_frames=1, max_side=320, out_dir=out_dir,
        cancel=Token(),
    )
    assert [frame.read_bytes() for frame in frames] == [b"new"]
