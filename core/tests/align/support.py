"""Shared helpers for the aligner tests: prepared files, a WAV and an adapter."""

from __future__ import annotations

import json
import math
import os
import struct
import sys
import time
import wave
from collections.abc import Sequence
from pathlib import Path

from app.jobs import CancelFlag
from app.ports import AlignResult
from app.settings import Settings
from app.tools.align.adapter import MODEL_EN_ITEM, MODEL_KO_ITEM, WhisperXAligner

FAKE_WORKER = Path(__file__).with_name("fake_worker.py")
WAV_MS = 3000
SAMPLE_RATE = 24000


def write_wav(path: Path, ms: int = WAV_MS, rate: int = SAMPLE_RATE) -> Path:
    frames = rate * ms // 1000
    data = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * index / rate)))
        for index in range(frames)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data)
    return path


def prepare_model_files(settings: Settings) -> None:
    """Create every recorded model file at its locked size as a sparse file."""
    for item in settings.runtime.items:
        if not item.id.startswith("model-align") and item.id != "model-nltk-punkt-tab":
            continue
        root = settings.model_dir / item.install_path
        for entry in item.files:
            path = root / entry.file
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                handle.truncate(entry.bytes)
    splitter = settings.model_dir / "nltk_data" / "tokenizers" / "punkt_tab" / "english"
    splitter.mkdir(parents=True, exist_ok=True)


def make_adapter(
    tmp_path: Path,
    mode: str = "ok",
    *,
    command: Sequence[str] | None = None,
    models: bool = True,
    nltk: bool = True,
    **options: object,
) -> WhisperXAligner:
    """An adapter over `fake_worker.py`, or over `command` when a test brings its own."""
    ko = tmp_path / "ko"
    en = tmp_path / "en"
    ko.mkdir(exist_ok=True)
    en.mkdir(exist_ok=True)
    (ko / "weights.bin").write_bytes(b"x" * 8)
    (en / "model.pth").write_bytes(b"x" * 8)
    nltk_data = tmp_path / "nltk_data"
    (nltk_data / "tokenizers" / "punkt_tab" / "english").mkdir(parents=True, exist_ok=True)
    files = [
        (MODEL_KO_ITEM, ko, {"weights.bin": 8}),
        (MODEL_EN_ITEM, en, {"model.pth": 8}),
    ]
    if not models:
        files = [(MODEL_KO_ITEM, tmp_path / "missing-ko", {"weights.bin": 8}),
                 (MODEL_EN_ITEM, tmp_path / "missing-en", {"model.pth": 8})]
    if not nltk:
        nltk_data = tmp_path / "missing-nltk"
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
        "python": Path(sys.executable),
        "model_files": files,
        "nltk_data": nltk_data,
        "threads": 2,
        "runtime_digest": "d" * 64,
        "worker_command": command,
        "ready_timeout_s": 20.0,
    }
    settings.update(options)
    return WhisperXAligner(**settings)  # type: ignore[arg-type]


def align(
    adapter: WhisperXAligner,
    tmp_path: Path,
    display: str,
    speech: str,
    language: str = "ko",
    *,
    cancel: CancelFlag | None = None,
    ms: int = WAV_MS,
) -> AlignResult:
    wav = write_wav(tmp_path / f"line-{language}-{abs(hash(display))}.wav", ms)
    return adapter.align(
        wav, speech, display, language, cancel=cancel or CancelFlag()
    )


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
