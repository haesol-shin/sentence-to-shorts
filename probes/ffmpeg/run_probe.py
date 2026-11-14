#!/usr/bin/env python3
"""Measure the ffmpeg executable bundled in the imageio-ffmpeg wheel.

Run it on the architecture that will run the product. The workflow runs one job per OS and
uploads `result.json` and `summary.md`; `RESULT.md` records only numbers copied from those
artifacts.

Exit codes:
    0  the probe finished, whether or not a check passed
    2  harness error (missing or non-bundled binary, unreadable output, broken parser)

The unit tests in `tests/` cover the parsers and the result writer without the wheel:
    python -m unittest discover -s probes/ffmpeg/tests
"""

from __future__ import annotations

import argparse
import base64
import importlib.metadata
import os
import platform
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from probe_harness import (
    DEFAULT_TIMEOUT,
    FPS,
    HEIGHT,
    LOUDNESS_TARGET_LUFS,
    LOUDNESS_TOLERANCE_LU,
    TRUE_PEAK_TARGET_DBTP,
    WIDTH,
    HarnessError,
    Probe,
    ProbeError,
    detect_license,
    parse_astats_rms,
    parse_duration,
    parse_loudnorm,
    parse_version,
    raw_rgb24,
    require,
    sha256_file,
    write_failure,
    write_result,
    write_tone_wav,
)

HERE = Path(__file__).resolve().parent
LOUDNORM_FILTER = (
    f"loudnorm=I={LOUDNESS_TARGET_LUFS:g}:TP={TRUE_PEAK_TARGET_DBTP:g}:LRA=11"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(HERE / ".local" / "probe"),
        help="folder for result.json and summary.md (default: probes/ffmpeg/.local/probe)",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="parent folder for a per-run media folder (default: <output>/work)",
    )
    parser.add_argument(
        "--ffmpeg",
        default=None,
        help="use this executable for a harness self-test instead of the bundled one",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="per-command timeout in seconds"
    )
    parser.add_argument("--keep-work", action="store_true", help="keep the synthetic media")
    return parser.parse_args(argv)


def resolve_ffmpeg(explicit: str | None) -> tuple[Path, str, str]:
    """Return (path, source, imageio-ffmpeg version) and refuse a non-bundled fallback."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ProbeError(f"--ffmpeg is not a file: {explicit}")
        return path.resolve(), "override (self-test only)", "override"
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise ProbeError(
            "imageio-ffmpeg is not installed; install it in an isolated environment"
        ) from exc
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    path = Path(exe)
    binaries = Path(imageio_ffmpeg.__file__).resolve().parent / "binaries"
    if not path.is_absolute() or not path.is_file():
        raise ProbeError(f"imageio-ffmpeg fell back to a non-bundled executable: {exe!r}")
    resolved = path.resolve()
    if binaries.resolve() not in resolved.parents:
        raise ProbeError(f"executable is outside the imageio-ffmpeg wheel: {resolved}")
    try:
        version = importlib.metadata.version("imageio-ffmpeg")
    except importlib.metadata.PackageNotFoundError:
        version = getattr(imageio_ffmpeg, "__version__", "unknown")
    return resolved, "imageio-ffmpeg wheel", version


def inspect_binary(probe: Probe) -> dict:
    """Step 1: absolute path, bytes, SHA-256, version line, build configuration, license."""
    path = probe.ffmpeg
    version = parse_version(probe.command(["-version"]).stdout)
    if not version["configuration"]:
        raise ProbeError("ffmpeg -version printed no configuration line")
    license_info = detect_license(version["configuration"])
    bundled_probe = [path.with_name(name) for name in ("ffprobe", "ffprobe.exe")]
    ffprobe = {
        "bundled": any(candidate.is_file() for candidate in bundled_probe),
        "system": shutil.which("ffprobe") is not None,
        "metadata_method": "ffmpeg -i stream lines and null-decode frame counts",
    }
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "version": version,
        "license": license_info,
        "ffprobe": ffprobe,
    }


def encode_frames(probe: Probe, path: Path, frames: bytes, *, fps: int = FPS) -> None:
    probe.command(
        [
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ],
        stdin=frames,
    )


def video_stream(info: dict) -> dict:
    for stream in info["streams"]:
        if stream["type"] == "video":
            return stream
    raise ProbeError("no video stream in the decoded input")


def audio_stream(info: dict) -> dict:
    for stream in info["streams"]:
        if stream["type"] == "audio":
            return stream
    raise ProbeError("no audio stream in the decoded input")


def measurement(info: dict, key: str, source: str):
    """A required value the harness reads from its own output; absence is a harness error."""
    value = info.get(key)
    if value is None:
        raise HarnessError(f"cannot read {key} from {source}")
    return value


def stream_measurement(stream: dict, key: str, kind: str):
    """A required stream field; absence is a harness error, a wrong value a probe failure."""
    value = stream.get(key)
    if value is None:
        raise HarnessError(f"cannot read {key} from the {kind} stream")
    return value


def check_rgb24_stdin(probe: Probe, work: Path) -> dict:
    output = work / "rgb24.mp4"
    encode_frames(probe, output, raw_rgb24(FPS))
    info = probe.probe_media(output)
    stream = video_stream(info)
    frames = measurement(info, "frames", output.name)
    codec = stream_measurement(stream, "codec", "video")
    pix_fmt = stream_measurement(stream, "pix_fmt", "video")
    width = stream_measurement(stream, "width", "video")
    height = stream_measurement(stream, "height", "video")
    fps = stream_measurement(stream, "fps", "video")
    require(frames == FPS, f"decoded {frames} frames, expected {FPS}")
    require(codec == "h264", f"video codec is {codec}, expected h264")
    require(pix_fmt == "yuv420p", f"pixel format is {pix_fmt}")
    require((width, height) == (WIDTH, HEIGHT), f"frame size is {width}x{height}")
    require(float(fps) == FPS, f"frame rate is {fps}")
    return {
        "frames": frames,
        "duration_s": info["duration_s"],
        "width": width,
        "height": height,
        "pix_fmt": pix_fmt,
        "fps": fps,
        "bytes": output.stat().st_size,
    }


def check_concat_copy(probe: Probe, work: Path) -> dict:
    clips = []
    for index in range(3):
        clip = work / f"clip-{index}.mp4"
        encode_frames(probe, clip, raw_rgb24(FPS // 3, seed=index))
        clips.append(clip)
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{clip.name}'\n" for clip in clips), encoding="utf-8")
    output = work / "concat.mp4"
    probe.command(
        ["-f", "concat", "-safe", "0", "-i", listing.name, "-c", "copy", str(output)],
        cwd=work,
    )
    info = probe.probe_media(output)
    stream = video_stream(info)
    expected = (FPS // 3) * 3
    frames = measurement(info, "frames", output.name)
    codec = stream_measurement(stream, "codec", "video")
    require(frames == expected, f"decoded {frames} frames, expected {expected}")
    require(codec == "h264", f"video codec is {codec}, expected h264")
    return {
        "clips": len(clips),
        "frames": frames,
        "duration_s": info["duration_s"],
        "codec": codec,
        "container": "mp4",
        "reencoded": False,
    }


def check_aac_mux(probe: Probe, work: Path) -> dict:
    video = work / "silent.mp4"
    encode_frames(probe, video, raw_rgb24(FPS))
    audio = work / "tone.wav"
    write_tone_wav(audio, 1.0)
    output = work / "mux.mp4"
    probe.command(
        [
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(output),
        ]
    )
    info = probe.probe_media(output)
    stream = audio_stream(info)
    codec = stream_measurement(stream, "codec", "audio")
    rate = stream_measurement(stream, "sample_rate", "audio")
    duration = measurement(info, "duration_s", output.name)
    video_codec = stream_measurement(video_stream(info), "codec", "video")
    require(codec == "aac", f"audio codec is {codec}, expected aac")
    require(rate == 44100, f"sample rate is {rate}")
    require(0.9 <= duration <= 1.1, f"duration is {duration}")
    return {
        "video": video_codec,
        "audio": codec,
        "sample_rate": rate,
        "duration_s": duration,
        "bytes": output.stat().st_size,
    }


def check_loudnorm_two_pass(probe: Probe, work: Path) -> dict:
    source = work / "speech.wav"
    write_tone_wav(source, 3.0)
    first = probe.command(
        ["-i", str(source), "-af", f"{LOUDNORM_FILTER}:print_format=json", "-f", "null", "-"]
    )
    measured = parse_loudnorm(first.stderr)
    checked = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        value = measured.get(key)
        if value is None:
            raise HarnessError(f"loudnorm pass 1 is missing {key}")
        if not isinstance(value, (int, float)):
            raise HarnessError(f"loudnorm pass 1 has a non-numeric {key}: {value!r}")
        checked[key] = value
    second_filter = (
        f"{LOUDNORM_FILTER}"
        f":measured_I={checked['input_i']:.2f}"
        f":measured_TP={checked['input_tp']:.2f}"
        f":measured_LRA={checked['input_lra']:.2f}"
        f":measured_thresh={checked['input_thresh']:.2f}"
        f":offset={checked['target_offset']:.2f}"
        ":linear=true:print_format=json"
    )
    normalized = work / "loudnorm.wav"
    probe.command(
        [
            "-i",
            str(source),
            "-af",
            second_filter,
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(normalized),
        ]
    )
    final = probe.command(
        [
            "-i",
            str(normalized),
            "-af",
            f"{LOUDNORM_FILTER}:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    result = parse_loudnorm(final.stderr)
    try:
        integrated = float(result["input_i"])
        peak = float(result["input_tp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HarnessError(f"loudnorm measurement is incomplete: {exc}") from exc
    require(
        abs(integrated - LOUDNESS_TARGET_LUFS) <= LOUDNESS_TOLERANCE_LU,
        f"integrated loudness is {integrated:.2f} LUFS, target {LOUDNESS_TARGET_LUFS:g} +-{LOUDNESS_TOLERANCE_LU:g}",
    )
    require(
        peak <= TRUE_PEAK_TARGET_DBTP,
        f"true peak is {peak:.2f} dBTP, limit {TRUE_PEAK_TARGET_DBTP:g}",
    )
    return {
        "pass1_integrated_lufs": checked["input_i"],
        "pass1_true_peak_dbtp": checked["input_tp"],
        "output_integrated_lufs": integrated,
        "output_true_peak_dbtp": peak,
        "target_integrated_lufs": LOUDNESS_TARGET_LUFS,
        "target_true_peak_dbtp": TRUE_PEAK_TARGET_DBTP,
    }


def rms_in_window(probe: Probe, path: Path, start: float, end: float) -> float:
    completed = probe.command(
        [
            "-i",
            str(path),
            "-af",
            f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
            "astats=measure_perchannel=none:measure_overall=RMS_level",
            "-f",
            "null",
            "-",
        ]
    )
    level = parse_astats_rms(completed.stderr)
    if level is None:
        raise HarnessError(f"astats did not report an RMS level for {path.name}")
    if level == float("-inf"):
        raise ProbeError(f"astats measured silence for {path.name}")
    return level


def check_sidechain_ducking(probe: Probe, work: Path) -> dict:
    music = work / "music.wav"
    write_tone_wav(music, 3.0, ((110.0, 0.12), (165.0, 0.08)))
    speech = work / "sidechain.wav"
    write_tone_wav(speech, 3.0, ((440.0, 0.5),), gate=(0.75, 2.25))
    ducked = work / "ducked.wav"
    probe.command(
        [
            "-i",
            str(music),
            "-i",
            str(speech),
            "-filter_complex",
            "[0:a][1:a]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[duck]",
            "-map",
            "[duck]",
            "-c:a",
            "pcm_s16le",
            str(ducked),
        ]
    )
    plain_rms = rms_in_window(probe, music, 0.9, 2.1)
    ducked_rms = rms_in_window(probe, ducked, 0.9, 2.1)
    reduction = plain_rms - ducked_rms
    require(reduction >= 2.0, f"ducking reduced the music by only {reduction:.2f} dB")
    return {
        "music_rms_db": round(plain_rms, 3),
        "ducked_rms_db": round(ducked_rms, 3),
        "reduction_db": round(reduction, 3),
        "threshold_db_reduction": 2.0,
    }


def check_bgm_loop_crossfade(probe: Probe, work: Path) -> dict:
    bgm = work / "bgm.wav"
    write_tone_wav(bgm, 1.0, ((220.0, 0.1), (330.0, 0.06)))
    looped = work / "looped.wav"
    probe.command(["-stream_loop", "-1", "-i", str(bgm), "-t", "2", "-c:a", "pcm_s16le", str(looped)])
    loop_info = probe.command(["-i", str(looped), "-f", "null", "-"])
    loop_duration = parse_duration(loop_info.stderr)
    if loop_duration is None:
        raise HarnessError("cannot read the looped BGM duration")
    require(abs(loop_duration - 2.0) <= 0.05, f"looped duration is {loop_duration}")
    crossfaded = work / "crossfaded.wav"
    probe.command(
        [
            "-stream_loop",
            "-1",
            "-i",
            str(bgm),
            "-stream_loop",
            "-1",
            "-i",
            str(bgm),
            "-filter_complex",
            "[0:a]atrim=0:2,asetpts=PTS-STARTPTS[a];"
            "[1:a]atrim=0:2,asetpts=PTS-STARTPTS[b];"
            "[a][b]acrossfade=d=0.5:c1=tri:c2=tri[out]",
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            str(crossfaded),
        ]
    )
    cross_info = probe.command(["-i", str(crossfaded), "-f", "null", "-"])
    cross_duration = parse_duration(cross_info.stderr)
    if cross_duration is None:
        raise HarnessError("cannot read the crossfaded BGM duration")
    require(abs(cross_duration - 3.5) <= 0.05, f"crossfaded duration is {cross_duration}")
    return {
        "loop_duration_s": loop_duration,
        "crossfade_duration_s": cross_duration,
        "crossfade_seconds": 0.5,
    }


def check_protocol_whitelist(probe: Probe, work: Path) -> dict:
    video = work / "whitelisted.mp4"
    frames = 5
    probe.command(
        [
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            str(FPS),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        stdin=raw_rgb24(frames),
    )
    info = probe.probe_media(video)
    pipe_frames = measurement(info, "frames", video.name)
    require(pipe_frames == frames, f"decoded {pipe_frames} frames, expected {frames}")

    tiny = work / "inline.wav"
    write_tone_wav(tiny, 0.1, sample_rate=8000)
    url = "data:audio/wav;base64," + base64.b64encode(tiny.read_bytes()).decode("ascii")
    control = probe.raw(["-f", "wav", "-i", url, "-f", "null", "-"])
    require(control.ok, f"the control read of the data protocol failed: {control.tail(400)}")
    blocked = probe.raw(
        ["-protocol_whitelist", "file,pipe", "-f", "wav", "-i", url, "-f", "null", "-"]
    )
    require(not blocked.ok, "the data protocol was accepted although the whitelist forbids it")
    require(
        "not on whitelist" in blocked.stderr or "not on the whitelist" in blocked.stderr,
        f"the rejection did not name the whitelist: {blocked.tail(400)}",
    )
    return {
        "pipe_frames": pipe_frames,
        "disallowed_protocol": "data",
        "disallowed_protocol_rejected": True,
    }


def decode_upload(
    probe: Probe,
    work: Path,
    *,
    extension: str,
    encoder_args: list[str],
    expected_codec: str,
) -> dict:
    source = work / "decode-source.wav"
    if not source.is_file():
        write_tone_wav(source, 1.0)
    fixture = work / f"upload.{extension}"
    probe.command(["-i", str(source), *encoder_args, str(fixture)])
    info = probe.probe_media(fixture)
    stream = audio_stream(info)
    codec = stream_measurement(stream, "codec", "audio")
    duration = measurement(info, "duration_s", fixture.name)
    require(codec == expected_codec, f"decoded codec is {codec}, expected {expected_codec}")
    require(0.85 <= duration <= 1.25, f"duration is {duration}")
    return {
        "codec": codec,
        "duration_s": duration,
        "bytes": fixture.stat().st_size,
        "encoder": encoder_args[1] if len(encoder_args) > 1 else "",
    }


CHECKS = (
    ("rgb24_stdin_h264", check_rgb24_stdin, "raw RGB24 on stdin to H.264 yuv420p 1080x1920 30fps"),
    ("concat_copy", check_concat_copy, "three clips of one format concatenated without re-encoding"),
    ("aac_mux", check_aac_mux, "AAC audio muxed into the clip container"),
    ("loudnorm_two_pass", check_loudnorm_two_pass, "two-pass loudnorm to -16 LUFS and -1 dBTP"),
    ("sidechaincompress_ducking", check_sidechain_ducking, "BGM ducked by a sidechain input"),
    ("bgm_loop_crossfade", check_bgm_loop_crossfade, "BGM looped and crossfaded"),
    ("protocol_whitelist_file_pipe", check_protocol_whitelist, "file,pipe whitelist accepts pipe and rejects data"),
    (
        "decode_mp3",
        partial(decode_upload, extension="mp3", encoder_args=["-c:a", "libmp3lame", "-b:a", "128k"], expected_codec="mp3"),
        "uploaded mp3 decoded",
    ),
    (
        "decode_m4a",
        partial(decode_upload, extension="m4a", encoder_args=["-c:a", "aac", "-b:a", "128k"], expected_codec="aac"),
        "uploaded m4a decoded",
    ),
    (
        "decode_ogg",
        partial(decode_upload, extension="ogg", encoder_args=["-c:a", "libvorbis", "-q:a", "4"], expected_codec="vorbis"),
        "uploaded ogg decoded",
    ),
    (
        "decode_wav",
        partial(decode_upload, extension="wav", encoder_args=["-c:a", "pcm_s16le"], expected_codec="pcm_s16le"),
        "uploaded wav decoded",
    ),
)


def run_checks(probe: Probe) -> None:
    for check_id, function, detail in CHECKS:
        probe.check(check_id, lambda function=function: function(probe, probe.workdir), detail=detail)


def runner_facts() -> dict:
    return {
        "os": os.environ.get("RUNNER_OS") or platform.system(),
        "arch": os.environ.get("RUNNER_ARCH") or platform.machine(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def build_payload(probe: Probe, imageio_version: str, source: str) -> dict:
    binary = inspect_binary(probe)
    run_checks(probe)
    checks = [check.as_dict() for check in probe.checks]
    failed = [check for check in checks if check["status"] != "pass"]
    broken = [check for check in checks if check.get("harness_error")]
    return {
        "probe": "bundled-ffmpeg",
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "runner": runner_facts(),
        "imageio_ffmpeg": {"distribution": "imageio-ffmpeg", "version": imageio_version, "source": source},
        "binary": binary,
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "harness_errors": len(broken),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = Path(args.output).resolve()
    work_parent = Path(args.work_dir).resolve() if args.work_dir else output / "work"
    run_dir: Path | None = None
    try:
        work_parent.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=work_parent))
        ffmpeg, source, imageio_version = resolve_ffmpeg(args.ffmpeg)
        probe = Probe(ffmpeg, run_dir, timeout=args.timeout)
        payload = build_payload(probe, imageio_version, source)
        result_path, summary_path = write_result(output, payload)
        summary = payload["summary"]
        print(
            f"probe finished: {summary['passed']}/{summary['total']} passed, "
            f"{summary['failed']} failed, {summary['harness_errors']} harness errors",
            flush=True,
        )
        print(f"result: {result_path}", flush=True)
        print(f"summary: {summary_path}", flush=True)
        return 2 if summary["harness_errors"] else 0
    except Exception:  # noqa: BLE001 - a harness error is the only non-result failure
        message = traceback.format_exc()
        print(message, file=sys.stderr, flush=True)
        write_failure(output, message)
        return 2
    finally:
        if run_dir is not None and not args.keep_work:
            shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
