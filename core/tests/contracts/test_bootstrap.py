"""The composition root selects adapters, builds the dev runtime, and stops workers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.bootstrap import ADAPTER_FACTORIES, build_runtime
from app.settings import Settings
from app.tools.align.adapter import WhisperXAligner
from app.tools.asr.faster_whisper.adapter import FasterWhisperTranscriber
from tests.align.support import align, alive, events, gone, make_adapter


def test_unknown_adapter_fails_at_startup(app_settings: Settings) -> None:
    app_settings.providers.fixture_adapters["llm"] = "no_such_adapter"
    with pytest.raises(RuntimeError, match="unknown llm adapter"):
        build_runtime(app_settings)


def test_unimplemented_adapter_fails_at_startup(app_settings: Settings) -> None:
    app_settings.profile = "dev"
    app_settings.providers.adapters["llm"] = "anthropic_api"
    app_settings.providers.adapters["tts"] = "fixed_wav"
    app_settings.providers.adapters["aligner"] = "default"
    with pytest.raises(RuntimeError, match="not implemented"):
        build_runtime(app_settings)


def test_unimplemented_default_adapter_fails_in_dev(app_settings: Settings) -> None:
    app_settings.profile = "dev"
    app_settings.providers.adapters["llm"] = "fixture"
    app_settings.providers.adapters["tts"] = "fixed_wav"
    app_settings.providers.adapters["aligner"] = "default"
    with pytest.raises(RuntimeError, match="adapter 'default' is not implemented"):
        build_runtime(app_settings)


def test_skeleton_adapter_is_fixture_only(app_settings: Settings) -> None:
    app_settings.profile = "dev"
    app_settings.providers.adapters["llm"] = "fixture"
    app_settings.providers.adapters["aligner"] = "skeleton"
    app_settings.providers.adapters["tts"] = "fixed_wav"
    with pytest.raises(RuntimeError, match="only available in the fixture profile"):
        build_runtime(app_settings)


def test_fixture_profile_uses_the_declared_skeleton(app_settings: Settings) -> None:
    runtime = build_runtime(app_settings)
    try:
        with pytest.raises(NotImplementedError):
            runtime.aligner.align(
                app_settings.data_dir / "missing.wav", "a", "a", "ko", cancel=None
            )
    finally:
        runtime.close()


def test_missing_selection_fails_at_startup(app_settings: Settings) -> None:
    del app_settings.providers.adapters["llm"]
    del app_settings.providers.fixture_adapters["llm"]
    with pytest.raises(RuntimeError, match="does not select a llm adapter"):
        build_runtime(app_settings)


def _isolate_dev_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PROFILE", "dev")
    monkeypatch.setenv("APP_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("APP_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("APP_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("APP_LAN", "0")
    monkeypatch.delenv("APP_PORT", raising=False)
    # The second environment is optional and its probe must not run in this test.
    monkeypatch.delenv("APP_ALIGN_PYTHON", raising=False)
    monkeypatch.delenv("APP_ALIGN_THREADS", raising=False)
    monkeypatch.delenv("APP_TTS_THREADS", raising=False)
    # Startup moves a legacy key out of the OS store; keep the test off the host.
    monkeypatch.setattr("app.llm.credentials._os_backend", lambda: None)


def test_dev_profile_builds_the_selected_tts_and_aligner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_dev_startup(tmp_path, monkeypatch)

    runtime = build_runtime()
    try:
        assert runtime.settings.profile == "dev"
        assert runtime.tts.info().engine_id == "qwen3-tts-0.6b"
        assert isinstance(runtime.aligner, WhisperXAligner)
    finally:
        runtime.close()


@pytest.mark.skipif(
    sys.platform == "win32", reason="process liveness is probed with POSIX signal 0"
)
def test_close_stops_the_started_aligner_worker(
    tmp_path: Path, app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = make_adapter(tmp_path)
    monkeypatch.setitem(ADAPTER_FACTORIES["aligner"], "whisperx", lambda settings: worker)
    app_settings.providers.fixture_adapters["aligner"] = "whisperx"
    runtime = build_runtime(app_settings)
    try:
        align(worker, tmp_path, "가격은 12,500원입니다.", "가격은 만 이천오백 원입니다.")
        pid = events(tmp_path)[0]["pid"]
        assert alive(pid)
        runtime.close()
        assert gone(pid)
    finally:
        # The verdict above must not leave a worker behind when it fails.
        worker.close()


def test_default_auto_dev_start_builds_the_transcriber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_dev_startup(tmp_path, monkeypatch)
    monkeypatch.delenv("APP_DEVICE", raising=False)

    runtime = build_runtime()
    try:
        assert runtime.settings.device == "auto"
        assert isinstance(runtime.transcriber, FasterWhisperTranscriber)
    finally:
        runtime.close()
