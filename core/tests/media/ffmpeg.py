"""An ffmpeg for media tests, and measurements read back from real files.

``APP_TEST_FFMPEG`` names the executable; without it the ffmpeg on PATH is used
so the acceptance checks of clips, mix and assembly run wherever one exists.
Tests that need it are skipped when neither is present. Product code never
searches PATH: the adapter takes the runtime lock path only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.tools.media.adapter import MediaAdapter


def find_ffmpeg() -> Path | None:
    named = os.environ.get("APP_TEST_FFMPEG")
    if named:
        return Path(named)
    found = shutil.which("ffmpeg")
    return Path(found).resolve() if found else None


requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="no ffmpeg for media tests")


def adapter() -> MediaAdapter:
    executable = find_ffmpeg()
    assert executable is not None
    return MediaAdapter(executable)


def _run(*args: str) -> tuple[str, str]:
    executable = find_ffmpeg()
    assert executable is not None
    result = subprocess.run(
        [str(executable), "-nostdin", "-hide_banner", *args],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace")


def loudness(path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP) measured by loudnorm."""
    _, log = _run("-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-")
    block = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", log)[-1]
    measured = json.loads(block)
    return float(measured["input_i"]), float(measured["input_tp"])


def video_packets(path: Path) -> list[str]:
    """MD5 of every video packet, read by stream copy: equal lists mean equal bytes."""
    out, _ = _run("-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "framemd5", "-")
    return [line.rsplit(",", 1)[1].strip() for line in out.splitlines()
            if line and not line.startswith("#")]


def decoded_frames(path: Path) -> list[str]:
    """MD5 of every decoded video frame."""
    out, _ = _run("-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-")
    return [line.rsplit(",", 1)[1].strip() for line in out.splitlines()
            if line and not line.startswith("#")]


def streams(path: Path) -> str:
    """The input stream lines of ``ffmpeg -i``."""
    _, log = _run("-i", str(path), "-f", "null", "-")
    head = log.split("Output #0", 1)[0]
    return "\n".join(line.strip() for line in head.splitlines() if "Stream #" in line)
