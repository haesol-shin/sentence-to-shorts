"""Shared helpers for the TTS tests: a voice, an adapter over a stand-in worker, probes."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from app.jobs import CancelFlag
from app.schemas.voice_manifest import VoiceManifest
from app.tools.tts.qwen3_tts_0_6b.adapter import ENGINE_ID, MODEL_ITEM, Qwen3TtsAdapter
from tests.conftest import load_json

FAKE_WORKER = Path(__file__).with_name("fake_worker.py")
REVISION = "a" * 40


def make_voice(**changes: object) -> VoiceManifest:
    raw = load_json("contracts/valid/voice_fixed_wav.json")
    raw.update(
        id="engine_voice",
        engine_id=ENGINE_ID,
        speaker="Sohee",
        languages=["ko"],
        model={"runtime_item": MODEL_ITEM, "repo": "Qwen/Synthetic", "revision": REVISION},
        output={"sample_rate": 24000, "channels": 1},
    )
    raw.update(changes)
    return VoiceManifest.model_validate(raw)


def make_adapter(
    tmp_path: Path,
    mode: str = "ok",
    *,
    command: Sequence[str] | None = None,
    package: bool = True,
    **options: object,
) -> Qwen3TtsAdapter:
    """An adapter over `fake_worker.py`, or over `command` when a test brings its own."""
    model_dir = tmp_path / "model"
    model_dir.mkdir(exist_ok=True)
    (model_dir / "weights.bin").write_bytes(b"x" * 8)
    if command is None:
        command = [
            sys.executable,
            str(FAKE_WORKER),
            "--mode",
            mode,
            "--pid-file",
            str(tmp_path / "pids"),
            "--log",
            str(tmp_path / "log.jsonl"),
        ]
    settings: dict[str, object] = {
        "model_dir": model_dir,
        "model_files": {"weights.bin": 8},
        "model_revision": REVISION,
        "runtime_digest": "d" * 64,
        "threads": 2,
        "package_ready": lambda: package,
        "worker_command": command,
        "load_timeout_s": 20.0,
    }
    settings.update(options)
    return Qwen3TtsAdapter(**settings)  # type: ignore[arg-type]


def events(tmp_path: Path) -> list[dict]:
    path = tmp_path / "log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone(*pids: int, within_s: float = 5.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        if not any(alive(pid) for pid in pids):
            return True
        time.sleep(0.05)
    return False


def synth(
    adapter: Qwen3TtsAdapter,
    tmp_path: Path,
    text: str = "안녕하세요",
    *,
    cancel: CancelFlag | None = None,
    voice: VoiceManifest | None = None,
):
    return adapter.synthesize(
        text,
        "ko",
        voice or make_voice(),
        out_dir=tmp_path / "out",
        cancel=cancel or CancelFlag(),
    )
