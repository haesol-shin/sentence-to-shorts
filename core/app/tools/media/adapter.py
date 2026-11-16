"""ffmpeg ``MediaPort``: argument arrays, ``-nostdin`` and a file,pipe protocol whitelist.

The executable path comes from the runtime lock under the runtime folder; PATH
is never searched. Filtergraphs are built from integers of the request only,
and every input and output path is passed with the ``file:`` protocol so a
path never selects another protocol.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from app.ports import (
    AppError,
    AppSettings,
    Cancelled,
    CancelToken,
    MediaInfo,
    MixPlan,
)
from app.tools.process import ProcessResult, run

RUNTIME_ITEM = "ffmpeg"
TIMEOUT_S = 900.0
STDERR_BYTES = 256 * 1024
PROTOCOLS = "file,pipe"
VIDEO_CODEC = ("-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p")
AUDIO_RATE = 44100
AUDIO_BITRATE = "192k"
ANALYSIS_RATE = 16000
DUCK_FILTER = "sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300"
LOUDNORM_LRA = 11
AUDIO_FORMATS = "wav,mp3,ogg,mov"
"""Demuxers an audio upload or a builtin BGM may open: the formats the bundled-binary
probe decoded (WAV, MP3, Ogg, and M4A through the mov demuxer)."""


def _file(path: Path) -> str:
    return f"file:{path.resolve()}"


def _input(source: str, *options: str) -> list[str]:
    return ["-protocol_whitelist", PROTOCOLS, *options, "-i", source]


def _db(value_x10: int) -> str:
    return f"{value_x10 // 10}.{abs(value_x10) % 10}" if value_x10 >= 0 else (
        f"-{abs(value_x10) // 10}.{abs(value_x10) % 10}"
    )


def _seconds(ms: int) -> str:
    return f"{ms // 1000}.{ms % 1000:03d}"


def parse_streams(text: str) -> dict[str, Any]:
    """Stream facts from the input section of ``ffmpeg -i`` output (no ffprobe ships)."""
    head = re.split(r"\nOutput #\d+", text, maxsplit=1)[0]
    found: dict[str, Any] = {}
    duration = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", head)
    if duration:
        hours, minutes, seconds, fraction = duration.groups()
        found["duration_ms"] = (
            (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000
            + int(fraction.ljust(3, "0")[:3])
        )
    for line in head.splitlines():
        match = re.search(r"Stream #\d+:\d+.*?: (Video|Audio): (.+)$", line)
        if not match:
            continue
        rest = match.group(2)
        if match.group(1) == "Video" and "width" not in found:
            size = re.search(r"\b(\d{2,5})x(\d{2,5})\b", rest)
            if size:
                found["width"], found["height"] = int(size.group(1)), int(size.group(2))
            fps = re.search(r"([\d.]+) fps", rest)
            if fps:
                found["fps"] = round(float(fps.group(1)))
        if match.group(1) == "Audio" and "sample_rate" not in found:
            rate = re.search(r"(\d+) Hz", rest)
            if rate:
                found["sample_rate"] = int(rate.group(1))
            if re.search(r"\bmono\b", rest):
                found["channels"] = 1
            elif re.search(r"\bstereo\b", rest):
                found["channels"] = 2
    return found


def _loudnorm_block(text: str) -> dict[str, str]:
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", text)
    if not blocks:
        raise AppError("media_failed", detail={"step": "loudnorm_measure"})
    measured = json.loads(blocks[-1])
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        value = measured.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"-?\d+(\.\d+)?|-inf|inf", value):
            raise AppError("media_failed", detail={"step": "loudnorm_measure", "field": key})
    return measured


class MediaAdapter:
    def __init__(self, ffmpeg: Path | None, *, timeout_s: float = TIMEOUT_S) -> None:
        if ffmpeg is not None and not ffmpeg.is_absolute():
            raise ValueError("the ffmpeg path must be absolute")
        self.ffmpeg = ffmpeg
        self.timeout_s = timeout_s

    def _run(
        self,
        step: str,
        args: list[str],
        *,
        cancel: CancelToken | None,
        stdin: Iterable[bytes] | None = None,
    ) -> ProcessResult:
        if self.ffmpeg is None or not self.ffmpeg.is_file():
            raise AppError("media_unavailable", detail={"step": step})
        if cancel is not None:
            cancel.raise_if_set()
        argv = [str(self.ffmpeg), "-nostdin", "-hide_banner", "-nostats", "-y", *args]
        result = run(
            argv,
            timeout_s=self.timeout_s,
            max_stdout_bytes=64 * 1024,
            max_stderr_bytes=STDERR_BYTES,
            cancel=cancel,
            stdin_data=stdin,
        )
        if result.cancelled:
            raise Cancelled(step)
        if result.timed_out:
            raise AppError("media_timeout", detail={"step": step})
        if result.returncode != 0:
            raise AppError("media_failed", detail={"step": step, "exit": result.returncode})
        return result

    def encode_frames(
        self,
        frames: Iterable[bytes],
        *,
        width: int,
        height: int,
        fps: int,
        out: Path,
        cancel: CancelToken,
    ) -> MediaInfo:
        if width <= 0 or height <= 0 or width % 2 or height % 2 or not 1 <= fps <= 120:
            raise ValueError("frames need an even positive size and 1..120 fps")
        frame_bytes = width * height * 3

        def checked() -> Iterator[bytes]:
            for frame in frames:
                if len(frame) != frame_bytes:
                    raise ValueError(f"a raw RGB24 frame must be {frame_bytes} bytes")
                yield frame

        self._run(
            "encode_frames",
            [
                *_input(
                    "pipe:0",
                    "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{width}x{height}", "-r", str(fps),
                ),
                "-an", *VIDEO_CODEC, "-r", str(fps), "-movflags", "+faststart",
                _file(out),
            ],
            cancel=cancel,
            stdin=checked(),
        )
        return self.probe(out)

    def mix(self, plan: MixPlan, *, out: Path, cancel: CancelToken) -> MediaInfo:
        """Mix mono stems, duck items with a negative ``ducking_db_x10`` under the rest.

        Ducking is a sidechain compressor keyed by the other items, with the
        settings the bundled-binary probe measured; the value only turns it on.
        """
        if not plan.items:
            raise ValueError("a mix needs at least one item")
        if plan.duration_ms <= 0:
            raise ValueError("a mix needs a positive duration_ms")
        inputs: list[str] = []
        chains: list[str] = []
        voices: list[str] = []
        ducked: list[str] = []
        for index, item in enumerate(plan.items):
            inputs += _input(_file(item.path))
            label = f"a{index}"
            chains.append(
                f"[{index}:a]aresample={plan.sample_rate},aformat=channel_layouts=mono,"
                f"adelay={item.start_ms}:all=1,volume={_db(item.gain_db_x10)}dB[{label}]"
            )
            (ducked if item.ducking_db_x10 < 0 else voices).append(label)
        if ducked and voices:
            keys = "".join(f"[key{index}]" for index in range(len(ducked)))
            chains.append(
                "".join(f"[{label}]" for label in voices)
                + f"amix=inputs={len(voices)}:normalize=0,asplit={len(ducked) + 1}[voice]{keys}"
            )
            mixed = ["[voice]"]
            for index, label in enumerate(ducked):
                chains.append(f"[key{index}]apad[pad{index}]")
                chains.append(f"[{label}][pad{index}]{DUCK_FILTER}[d{index}]")
                mixed.append(f"[d{index}]")
        else:
            mixed = [f"[{label}]" for label in voices + ducked]
        chains.append(f"{''.join(mixed)}amix=inputs={len(mixed)}:normalize=0[mix]")
        # Float premix: the sum may pass full scale before the loudness step brings
        # it under the peak target, so nothing is clipped on the way.
        staged = out.with_name(out.stem + ".premix.wav")
        self._run(
            "mix",
            [*inputs, "-filter_complex", ";".join(chains), "-map", "[mix]",
             "-c:a", "pcm_f32le", "-ar", str(plan.sample_rate), _file(staged)],
            cancel=cancel,
        )
        try:
            target = (
                f"loudnorm=I={_db(plan.loudness_lufs_x10)}:TP={_db(plan.true_peak_dbtp_x10)}"
                f":LRA={LOUDNORM_LRA}"
            )
            first = self._run(
                "loudnorm_measure",
                [
                    *_input(_file(staged)),
                    "-af",
                    f"{target}:print_format=json",
                    "-t",
                    _seconds(plan.duration_ms),
                    "-f",
                    "null",
                    "-",
                ],
                cancel=cancel,
            )
            m = _loudnorm_block(first.stderr.decode("utf-8", "replace"))
            second = (
                f"{target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                f":offset={m['target_offset']}:linear=true"
            )
            self._run(
                "loudnorm_apply",
                [
                    *_input(_file(staged)),
                    "-af",
                    second,
                    "-ar",
                    str(plan.sample_rate),
                    "-t",
                    _seconds(plan.duration_ms),
                    "-c:a",
                    "pcm_s16le",
                    _file(out),
                ],
                cancel=cancel,
            )
        finally:
            staged.unlink(missing_ok=True)
        return self.probe(out)

    def mux_concat(
        self, clips: list[Path], audio: Path, *, out: Path, cancel: CancelToken
    ) -> MediaInfo:
        if not clips:
            raise ValueError("concat needs at least one clip")
        listing = out.with_name(out.stem + ".concat.txt")
        lines = []
        for clip in clips:
            path = str(clip.resolve()).replace("'", "'\\''")
            lines.append(f"file 'file:{path}'")
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            self._run(
                "mux_concat",
                [
                    *_input(_file(listing), "-f", "concat", "-safe", "0"),
                    *_input(_file(audio)),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_RATE),
                    "-movflags", "+faststart", _file(out),
                ],
                cancel=cancel,
            )
        finally:
            listing.unlink(missing_ok=True)
        return self.probe(out)

    def decode_audio(
        self,
        src: Path,
        *,
        out: Path,
        sample_rate: int,
        channels: int,
        max_ms: int,
        cancel: CancelToken,
    ) -> MediaInfo:
        """Decode an audio file with a fixed demuxer list to PCM16 WAV.

        Only ``AUDIO_FORMATS`` open, so a file never reaches a demuxer outside
        the measured list. The decode stops just past ``max_ms``, so a header
        that understates the length cannot pass a long file.
        """
        source = self._probe(src, "-format_whitelist", AUDIO_FORMATS)
        if source.sample_rate is None:
            raise AppError("media_unreadable", detail={"reason": "no_audio"})
        if source.duration_ms is None:
            raise AppError("media_unreadable", detail={"reason": "no_duration"})
        if source.duration_ms > max_ms:
            raise AppError("media_too_long", detail={"max_ms": max_ms})
        self._run(
            "decode_audio",
            [*_input(_file(src), "-format_whitelist", AUDIO_FORMATS), "-vn",
             "-t", _seconds(max_ms + 1), "-ac", str(channels), "-ar", str(sample_rate),
             "-c:a", "pcm_s16le", _file(out)],
            cancel=cancel,
        )
        decoded = self.probe(out)
        if decoded.duration_ms is None or decoded.duration_ms > max_ms:
            out.unlink(missing_ok=True)
            raise AppError("media_too_long", detail={"max_ms": max_ms})
        return decoded

    def extract_frames(
        self,
        src: Path,
        *,
        every_ms: int,
        max_frames: int,
        max_side: int,
        out_dir: Path,
        cancel: CancelToken,
    ) -> list[Path]:
        if every_ms <= 0 or max_frames <= 0 or max_side <= 0:
            raise ValueError("every_ms, max_frames and max_side must be positive")
        out_dir.mkdir(parents=True, exist_ok=True)
        # A fresh folder per call: frames left by an earlier run never join this result.
        run_dir = Path(tempfile.mkdtemp(prefix="frames_", dir=out_dir))
        scale = (
            f"scale=w='min({max_side},iw)':h='min({max_side},ih)'"
            ":force_original_aspect_ratio=decrease"
        )
        self._run(
            "extract_frames",
            [*_input(_file(src)), "-an", "-vf", f"fps=1000/{every_ms},{scale}",
             "-frames:v", str(max_frames), _file(run_dir / "frame_%04d.png")],
            cancel=cancel,
        )
        return sorted(run_dir.glob("frame_*.png"))

    def extract_audio(
        self, src: Path, *, out: Path, max_ms: int, cancel: CancelToken
    ) -> MediaInfo:
        """Mono 16 kHz PCM for transcription, cut at ``max_ms``."""
        self._run(
            "extract_audio",
            [*_input(_file(src)), "-vn", "-t", _seconds(max_ms), "-ac", "1",
             "-ar", str(ANALYSIS_RATE), "-c:a", "pcm_s16le", _file(out)],
            cancel=cancel,
        )
        return self.probe(out)

    def probe(self, src: Path) -> MediaInfo:
        return self._probe(src)

    def _probe(self, src: Path, *options: str) -> MediaInfo:
        result = self._run(
            "probe", [*_input(_file(src), *options), "-f", "null", "-"], cancel=None
        )
        found = parse_streams(result.stderr.decode("utf-8", "replace"))
        if not found:
            raise AppError("media_unreadable", detail={"reason": "no_stream"})
        return MediaInfo(path=src, **found)


def _platform() -> tuple[str, str]:
    system = "windows" if sys.platform == "win32" else "linux"
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    return system, arch


def runtime_executable(settings: AppSettings) -> Path | None:
    """Absolute ffmpeg path from the runtime lock entry, or None when not locked."""
    lock = getattr(settings, "runtime", None)
    items = getattr(lock, "items", None) or []
    system, arch = _platform()
    for item in items:
        if item.id != RUNTIME_ITEM:
            continue
        for entry in item.files:
            if entry.os == system and entry.arch == arch:
                return (settings.runtime_dir / item.install_path / entry.file).resolve()
    return None


def create(settings: AppSettings) -> MediaAdapter:
    """Without a locked ffmpeg for this platform every call fails with media_unavailable."""
    return MediaAdapter(runtime_executable(settings))


class SkeletonMediaAdapter(MediaAdapter):
    """Fixture-profile placeholder: every call reports not implemented."""

    def __init__(self) -> None:
        super().__init__(None)

    def _run(
        self,
        step: str,
        args: list[str],
        *,
        cancel: CancelToken | None,
        stdin: Iterable[bytes] | None = None,
    ) -> ProcessResult:
        raise NotImplementedError("tools/media skeleton")


def create_skeleton(settings: AppSettings) -> MediaAdapter:
    return SkeletonMediaAdapter()
