"""Shared plumbing for the bundled-ffmpeg probe.

The probe measures the executable that ships inside the imageio-ffmpeg wheel. A check of the
thing under test may fail without failing the workflow: the failure is written to `result.json`
and the probe still exits 0. Only a harness error (a missing binary, an unreadable result, a
broken parser) exits nonzero.

This module deliberately has no third-party import so the unit tests run without the wheel.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

WIDTH = 1080
HEIGHT = 1920
FPS = 30
LOUDNESS_TARGET_LUFS = -16.0
TRUE_PEAK_TARGET_DBTP = -1.0
LOUDNESS_TOLERANCE_LU = 1.0

DEFAULT_TIMEOUT = 180.0
ERROR_TAIL = 1200


class ProbeError(RuntimeError):
    """The harness cannot run a command or a parser cannot read its output."""


@dataclass(frozen=True)
class Completed:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def tail(self, limit: int = ERROR_TAIL) -> str:
        text = self.stderr.strip() or self.stdout.strip()
        return text[-limit:]


@dataclass
class CheckResult:
    id: str
    status: str
    detail: str = ""
    measurements: dict = field(default_factory=dict)
    error: str = ""
    seconds: float = 0.0
    harness_error: bool = False

    def as_dict(self) -> dict:
        record = {
            "id": self.id,
            "status": self.status,
            "detail": self.detail,
            "seconds": round(self.seconds, 3),
            "measurements": self.measurements,
        }
        if self.error:
            record["error"] = self.error
        if self.harness_error:
            record["harness_error"] = True
        return record


def require(condition: object, message: str) -> None:
    """Raise a probe failure when a measured expectation does not hold."""
    if not condition:
        raise ProbeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- parsing -------------------------------------------------------------------------


def parse_version(text: str) -> dict:
    """Read the version line, build line and configuration line of `ffmpeg -version`."""
    first = text.splitlines()[0] if text.splitlines() else ""
    match = re.search(r"ffmpeg version ([^\s]+)", first)
    if not match:
        raise ProbeError(f"cannot read the ffmpeg version line: {first[:120]!r}")
    build = re.search(r"^built with (.+)$", text, re.MULTILINE)
    configuration = re.search(r"^configuration: (.+)$", text, re.MULTILINE)
    return {
        "version": match.group(1),
        "version_line": first.strip(),
        "build": build.group(1).strip() if build else "",
        "configuration": configuration.group(1).strip() if configuration else "",
    }


def detect_license(configuration: str) -> dict:
    """Derive the GPL/LGPL split that the build configuration enables."""
    gpl = "--enable-gpl" in configuration
    version3 = "--enable-version3" in configuration
    if gpl:
        spdx = "GPL-3.0-or-later" if version3 else "GPL-2.0-or-later"
    else:
        spdx = "LGPL-3.0-or-later" if version3 else "LGPL-2.1-or-later"
    return {
        "family": "GPL" if gpl else "LGPL",
        "spdx": spdx,
        "enable_gpl": gpl,
        "enable_version3": version3,
    }


def parse_loudnorm(text: str) -> dict:
    """Return the last loudnorm JSON object in ffmpeg's stderr, with float values."""
    decoder = json.JSONDecoder()
    found = []
    for match in re.finditer(r"\{", text):
        try:
            value, _end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "input_i" in value:
            found.append(value)
    if not found:
        raise ProbeError("loudnorm did not print a JSON measurement block")
    block = found[-1]
    numbers = {}
    for key, value in block.items():
        try:
            numbers[key] = float(value)
        except (TypeError, ValueError):
            numbers[key] = value
    return numbers


def parse_input_streams(text: str) -> list[dict]:
    """Parse the stream lines of the input section printed by `ffmpeg -i`.

    Output stream lines repeat the same shape but describe the encoder side; cut them so a
    wrapper such as `wrapped_avframe` cannot hide a wrong input codec.
    """
    head = re.split(r"\nOutput #\d+", text, maxsplit=1)[0]
    streams = []
    for line in head.splitlines():
        match = re.search(r"Stream #\d+:\d+.*?: (Video|Audio|Data|Subtitle): (.+)$", line)
        if not match:
            continue
        kind, rest = match.group(1).lower(), match.group(2)
        stream = {"type": kind, "codec": rest.split(" ", 1)[0].split(",", 1)[0]}
        size = re.search(r"(\d{2,5})x(\d{2,5})", rest)
        if size:
            stream["width"] = int(size.group(1))
            stream["height"] = int(size.group(2))
        fps = re.search(r"([\d.]+) fps", rest)
        if fps:
            stream["fps"] = float(fps.group(1))
        rate = re.search(r"(\d+) Hz", rest)
        if rate:
            stream["sample_rate"] = int(rate.group(1))
        channels = re.search(r"\b(mono|stereo)\b", rest)
        if channels:
            stream["channels"] = channels.group(1)
        else:
            count = re.search(r"(\d+) channels", rest)
            if count:
                stream["channels"] = int(count.group(1))
        pix_fmt = re.search(r"\b(yuv\w+|rgb\w+|gbr\w+|gray\w*)\b", rest)
        if pix_fmt:
            stream["pix_fmt"] = pix_fmt.group(1)
        streams.append(stream)
    return streams


def parse_duration(text: str) -> float | None:
    """Read the input duration in seconds; `None` for a stream without a duration."""
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_frames(text: str) -> int | None:
    """Read the last decoded frame count from an ffmpeg progress line."""
    matches = re.findall(r"frame=\s*(\d+)", text)
    return int(matches[-1]) if matches else None


def parse_astats_rms(text: str) -> float | None:
    """Read the last overall RMS level in dB that the astats filter prints."""
    matches = re.findall(r"RMS level dB:\s*(-?\d+(?:\.\d+)?|-inf)", text)
    if not matches or matches[-1] == "-inf":
        return None
    return float(matches[-1])


# --- synthetic media ----------------------------------------------------------------


def raw_rgb24(count: int, width: int = WIDTH, height: int = HEIGHT, seed: int = 0) -> bytes:
    """A deterministic raw RGB24 frame sequence, built one frame and repeated."""
    rows = []
    for y in range(height):
        red = (y * 7 + seed * 5) % 256
        green = (y * 3 + 40) % 256
        blue = (y + 120) % 256
        rows.append(bytes((red, green, blue)) * width)
    frame = b"".join(rows)
    return frame * count


def write_tone_wav(
    path: Path,
    seconds: float,
    partials: tuple[tuple[float, float], ...] = ((220.0, 0.08), (440.0, 0.03)),
    gate: tuple[float, float] | None = None,
    sample_rate: int = 44100,
) -> None:
    """Write a mono 16-bit PCM WAV from summed sines, optionally gated in time."""
    total = int(sample_rate * seconds)
    frames = bytearray()
    for index in range(total):
        moment = index / sample_rate
        if gate is not None and not (gate[0] <= moment < gate[1]):
            value = 0.0
        else:
            value = sum(
                amplitude * math.sin(2.0 * math.pi * frequency * moment)
                for frequency, amplitude in partials
            )
        frames += struct.pack("<h", max(-32768, min(32767, int(value * 32767))))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))


# --- probe --------------------------------------------------------------------------


class Probe:
    """Runs ffmpeg commands, records each check, and never raises for a check failure."""

    def __init__(self, ffmpeg: Path, workdir: Path, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.ffmpeg = Path(ffmpeg)
        self.workdir = Path(workdir).resolve()
        self.timeout = timeout
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.checks: list[CheckResult] = []

    def raw(
        self,
        args: list[str],
        *,
        stdin: bytes | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> Completed:
        command = [str(self.ffmpeg), "-nostdin", "-hide_banner", "-y", *args]
        try:
            process = subprocess.run(
                command,
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                timeout=timeout or self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProbeError(f"ffmpeg timed out after {timeout or self.timeout:g}s") from exc
        except OSError as exc:
            raise ProbeError(f"cannot start ffmpeg: {exc}") from exc
        return Completed(
            command=command,
            returncode=process.returncode,
            stdout=process.stdout.decode("utf-8", "replace"),
            stderr=process.stderr.decode("utf-8", "replace"),
        )

    def command(
        self,
        args: list[str],
        *,
        stdin: bytes | None = None,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> Completed:
        completed = self.raw(args, stdin=stdin, cwd=cwd, timeout=timeout)
        if not completed.ok:
            raise ProbeError(
                f"ffmpeg exited {completed.returncode}: {completed.tail()}"
            )
        return completed

    def probe_media(self, path: Path) -> dict:
        """Read streams, duration and decoded frame count without ffprobe."""
        completed = self.raw(["-i", str(path), "-f", "null", "-"])
        streams = parse_input_streams(completed.stderr)
        if not streams:
            raise ProbeError(f"no input stream in {path.name}: {completed.tail(400)}")
        return {
            "duration_s": parse_duration(completed.stderr),
            "frames": parse_frames(completed.stderr),
            "streams": streams,
        }

    def check(
        self, check_id: str, func: Callable[[], dict | None], *, detail: str = ""
    ) -> CheckResult:
        started = time.monotonic()
        harness_error = False
        try:
            measurements = func() or {}
            result = CheckResult(
                id=check_id,
                status="pass",
                detail=detail or "ok",
                measurements=measurements,
            )
        except ProbeError as exc:
            # The thing under test failed; that is a probe result, not a crash.
            result = CheckResult(id=check_id, status="fail", detail=detail, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a bug in the harness, recorded and failed
            traceback.print_exc(file=sys.stderr)
            harness_error = True
            result = CheckResult(
                id=check_id,
                status="fail",
                detail=detail,
                error=f"{type(exc).__name__}: {exc}",
            )
        result.harness_error = harness_error
        result.seconds = time.monotonic() - started
        self.checks.append(result)
        evidence = result.detail if result.status == "pass" else result.error
        print(f"[{result.status}] {check_id}: {evidence} ({result.seconds:.2f}s)", flush=True)
        return result


# --- result files -------------------------------------------------------------------


def summary_markdown(payload: dict) -> str:
    """A short job-summary body; the full evidence lives in result.json."""
    binary = payload["binary"]
    runner = payload["runner"]
    checks = payload["checks"]
    failed = [check for check in checks if check["status"] != "pass"]
    broken = [check for check in checks if check.get("harness_error")]
    title = f"Bundled ffmpeg probe on {runner['os']} {runner['arch']}"
    lines = [
        f"## {title}",
        "",
        f"- imageio-ffmpeg `{payload['imageio_ffmpeg']['version']}`, ffmpeg `{binary['version']['version']}`",
        f"- SHA-256 `{binary['sha256']}`",
        f"- license `{binary['license']['spdx']}`",
        f"- ffprobe bundled: `{binary['ffprobe']['bundled']}`, method: {binary['ffprobe']['metadata_method']}",
        "",
        "| check | status | measured |",
        "|---|---|---|",
    ]
    for check in checks:
        measured = check.get("error") or check.get("detail", "")
        measured = measured.replace("|", "\\|").replace("\n", " ")[:160]
        lines.append(f"| {check['id']} | {check['status']} | {measured} |")
    lines += [
        "",
        f"**{len(checks) - len(failed)} of {len(checks)} checks passed.**"
        if not failed
        else f"**{len(failed)} of {len(checks)} checks failed; see result.json.**",
    ]
    if broken:
        lines.append(
            f"**{len(broken)} check(s) hit a harness error; the workflow fails.**"
        )
    return "\n".join(lines) + "\n"


def write_result(output_dir: Path, payload: dict) -> tuple[Path, Path]:
    """Write result.json and summary.md atomically and return their paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    summary_path = output_dir / "summary.md"
    for path, text in (
        (result_path, json.dumps(payload, indent=2, sort_keys=False) + "\n"),
        (summary_path, summary_markdown(payload)),
    ):
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=output_dir, delete=False, prefix=f".{path.name}."
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    return result_path, summary_path


def write_failure(output_dir: Path, message: str) -> None:
    """Best-effort record of a harness error so the workflow artifact shows the cause."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "failure.json").write_text(
            json.dumps({"harness_error": message}, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass
