"""faster-whisper adapter: prepared model folders and a real transcript when one exists."""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

from app.ports import AppError, Cancelled
from app.tools.asr.adapter import create, create_skeleton
from app.tools.asr.faster_whisper.adapter import (
    MODEL_FILES,
    RUNTIME_ITEM,
    FasterWhisperTranscriber,
    find_model,
)
from tests.reference.support import Cancel

PROBE_AUDIO = Path(__file__).resolve().parents[3] / "probes" / "transcribe" / "audio"
HF_SNAPSHOTS = (
    Path.home() / ".cache" / "huggingface" / "hub"
    / "models--Systran--faster-whisper-small" / "snapshots"
)


def _prepare(model_dir: Path, revision: str = "rev1", *, complete: bool = True) -> Path:
    folder = model_dir / RUNTIME_ITEM / revision
    folder.mkdir(parents=True)
    for name in MODEL_FILES if complete else MODEL_FILES[:1]:
        (folder / name).write_bytes(b"x")
    return folder


def test_20_transcriber_without_a_prepared_model_is_model_missing(tmp_path: Path) -> None:
    adapter = FasterWhisperTranscriber(tmp_path / "models")
    with pytest.raises(AppError) as caught:
        adapter.transcribe(tmp_path / "a.wav", None, cancel=Cancel())
    assert caught.value.code == "model_missing"


def test_20_transcriber_ignores_an_incomplete_model_folder(tmp_path: Path) -> None:
    _prepare(tmp_path, complete=False)
    assert find_model(tmp_path) is None
    with pytest.raises(AppError) as caught:
        FasterWhisperTranscriber(tmp_path).transcribe(tmp_path / "a.wav", "en", cancel=Cancel())
    assert caught.value.code == "model_missing"


def test_20_transcriber_reads_the_newest_complete_revision(tmp_path: Path) -> None:
    _prepare(tmp_path, "aaa")
    newest = _prepare(tmp_path, "bbb")
    (tmp_path / RUNTIME_ITEM / "ccc").mkdir()
    assert find_model(tmp_path) == newest


@pytest.mark.skipif(
    importlib.util.find_spec("faster_whisper") is not None, reason="the package is installed"
)
def test_20_transcriber_without_the_package_is_model_missing(tmp_path: Path) -> None:
    _prepare(tmp_path)
    with pytest.raises(AppError) as caught:
        FasterWhisperTranscriber(tmp_path).transcribe(tmp_path / "a.wav", None, cancel=Cancel())
    assert caught.value.code == "model_missing"
    assert caught.value.detail["reason"] == "package"


def test_20_transcriber_checks_cancel_before_it_loads_anything(tmp_path: Path) -> None:
    cancel = Cancel()
    cancel.event.set()
    with pytest.raises(Cancelled):
        FasterWhisperTranscriber(tmp_path).transcribe(tmp_path / "a.wav", None, cancel=cancel)


@pytest.mark.parametrize("language", ["KO", "korean", "e", "ko;rm", "../x"])
def test_20_transcriber_takes_a_short_language_code_only(tmp_path: Path, language: str) -> None:
    with pytest.raises(ValueError):
        FasterWhisperTranscriber(tmp_path).transcribe(tmp_path / "a.wav", language, cancel=Cancel())


def test_20_asr_adapter_reads_the_model_folder_from_settings(app_settings) -> None:  # type: ignore[no-untyped-def]
    assert create(app_settings).model_dir == app_settings.model_dir
    with pytest.raises(NotImplementedError):
        create_skeleton(app_settings).transcribe(Path("a.wav"), None, cancel=Cancel())


def _model_root(tmp_path: Path) -> Path | None:
    named = os.environ.get("APP_TEST_WHISPER_MODEL")
    source = Path(named) if named else None
    if source is None and HF_SNAPSHOTS.is_dir():
        source = next((path for path in sorted(HF_SNAPSHOTS.iterdir()) if path.is_dir()), None)
    if source is None or not all((source / name).is_file() for name in MODEL_FILES):
        return None
    root = tmp_path / "models"
    link = root / RUNTIME_ITEM / "prepared"
    link.parent.mkdir(parents=True)
    link.symlink_to(source.resolve(), target_is_directory=True)
    return root


def _words(text: str) -> list[str]:
    return [word for word in re.split(r"[^\w']+", text.lower()) if word]


@pytest.mark.models
@pytest.mark.skipif(
    importlib.util.find_spec("faster_whisper") is None, reason="faster-whisper is not installed"
)
@pytest.mark.parametrize(("language", "floor"), [("en", 0.85), ("ko", 0.5)])
def test_20_transcriber_reads_speech_in_korean_and_english(
    tmp_path: Path, language: str, floor: float
) -> None:
    root = _model_root(tmp_path)
    if root is None:
        pytest.skip("no prepared faster-whisper model on this device")
    adapter = FasterWhisperTranscriber(root)

    segments = adapter.transcribe(PROBE_AUDIO / f"{language}.wav", language, cancel=Cancel())

    heard = _words(" ".join(item.text for item in segments))
    expected = _words((PROBE_AUDIO / f"{language}.txt").read_text(encoding="utf-8"))
    kept = sum(1 for word in expected if word in set(heard))
    assert kept / len(expected) >= floor
    assert segments and all(0 <= item.start_ms < item.end_ms for item in segments)
    assert segments == sorted(segments, key=lambda item: item.start_ms)
