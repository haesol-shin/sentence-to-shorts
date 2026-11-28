"""Sandbox test helpers: runtime discovery, requests and synthetic PNG and WAV bytes."""

from __future__ import annotations

import base64
import io
import json
import math
import os
import struct
import wave
import zlib
from pathlib import Path

import pytest
import yaml

from app.schemas.sandbox_io import SandboxRequest

CORE = Path(__file__).resolve().parents[2]
REPO_ROOT = CORE.parent
PROGRAMS = Path(__file__).resolve().parent / "programs"
LIMITS = {"max_files": 64, "max_png_side": 1920, "max_wav_ms": 16000}


def caption_box_input(width: int, height: int) -> dict:
    return {
        "plate": {"w": width, "h": height},
        "spec": {
            "size_px": 48,
            "line_height": 60,
            "text_color": "#FFFFFF",
            "box_color": "#000000",
            "align": "center",
            "lines": [{"w": 160, "h": 60}],
        },
        "canvas": {"width": width, "height": height},
    }


DEFAULT_INPUT = {
    "style_parts": {"spec": {}, "character": {}, "canvas": {"width": 256, "height": 256}},
    "template_layer": {
        "scene": {"id": "s1"},
        "regions": {},
        "canvas": {"width": 256, "height": 256},
    },
    "caption_box": caption_box_input(320, 80),
    "bgm_loop": {"params": {"seconds": 2}},
}


def sandbox_config_values() -> dict:
    """The configured `sandbox` limits from core/config/app.yaml."""
    with (CORE / "config" / "app.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)["sandbox"]


def runtime_lock_items() -> list[dict]:
    lock = json.loads((CORE / "config" / "runtime.lock.json").read_text(encoding="utf-8"))
    return lock["items"]


def program(name: str) -> str:
    """Program source as text; the host never imports or executes it."""
    return (PROGRAMS / f"{name}.py").read_text(encoding="utf-8")


def make_request(
    kind: str,
    code: str,
    *,
    request_id: str = "0123456789abcdef",
    assets: list[dict] | None = None,
    seed: int = 7,
    input: dict | None = None,
) -> SandboxRequest:
    return SandboxRequest.model_validate(
        {
            "protocol": 1,
            "request_id": request_id,
            "kind": kind,
            "code": code,
            "input": input if input is not None else DEFAULT_INPUT[kind],
            "assets": assets or [],
            "seed": seed,
            "limits": LIMITS,
        }
    )


def _chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def rgba_png(
    width: int = 4,
    height: int = 3,
    *,
    color_type: int = 6,
    extra: list[tuple[bytes, bytes]] | None = None,
    raw: bytes | None = None,
) -> bytes:
    """A deterministic PNG built with zlib; `extra` chunks go before IDAT."""
    channels = {6: 4, 2: 3}[color_type]
    row = b"\x00" + bytes(index % 256 for index in range(width * channels))
    scanlines = raw if raw is not None else row * height
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    chunks = [_chunk(b"IHDR", header)]
    chunks += [_chunk(kind, body) for kind, body in extra or []]
    chunks += [_chunk(b"IDAT", zlib.compress(scanlines)), _chunk(b"IEND", b"")]
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def tone_wav_bytes(
    *,
    duration_ms: int = 1000,
    amplitude: float = 0.2,
    rate: int = 44100,
    channels: int = 1,
) -> bytes:
    frames = rate * duration_ms // 1000
    payload = bytearray()
    for index in range(frames):
        value = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * index / rate))
        payload += struct.pack("<h", value) * channels
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(payload))
    return buffer.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _runtime_candidates() -> list[Path]:
    candidates = []
    configured = os.environ.get("APP_RUNTIME_DIR")
    if configured:
        candidates.append(Path(configured).expanduser())
    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        # The CI job installs the runtime under the runner temp folder in an
        # earlier step whose environment does not reach the test step.
        candidates.append(Path(runner_temp) / "rt")
    candidates.append(REPO_ROOT / ".local" / "rt")
    return candidates


@pytest.fixture
def runtime_root() -> Path:
    for candidate in _runtime_candidates():
        if (candidate / "installed.json").is_file():
            return candidate
    message = "sandbox runtime is not installed; run scripts/dev_setup.py --runtime"
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail(message)
    pytest.skip(message)
