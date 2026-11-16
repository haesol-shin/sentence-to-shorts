"""The adapter built from the runtime lock: identity, readiness and thread setting."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest

from app.settings import Settings
from app.tools.tts.qwen3_tts_0_6b import adapter as engine
from app.tools.tts.qwen3_tts_0_6b.adapter import (
    ENGINE_ID,
    MODEL_ITEM,
    PACKAGE_ITEM,
    SAMPLE_RATE,
    create,
    default_threads,
)


def lock_item(settings: Settings, item_id: str):  # type: ignore[no-untyped-def]
    return next(item for item in settings.runtime.items if item.id == item_id)


def test_11_runtime_digest_follows_the_pinned_model_and_package(app_settings: Settings) -> None:
    first = create(app_settings).info()
    assert (first.engine_id, first.sample_rate, first.languages) == (
        ENGINE_ID,
        SAMPLE_RATE,
        ("ko", "en"),
    )
    assert len(first.runtime_digest) == 64
    assert create(app_settings).info().runtime_digest == first.runtime_digest
    lock_item(app_settings, MODEL_ITEM).files[0].sha256 = "0" * 64
    changed_model = create(app_settings).info().runtime_digest
    assert changed_model != first.runtime_digest
    lock_item(app_settings, PACKAGE_ITEM).files[0].sha256 = "1" * 64
    assert create(app_settings).info().runtime_digest not in (first.runtime_digest, changed_model)


def test_27_fresh_model_folder_and_missing_package_are_not_ready(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def absent(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(engine.metadata, "version", absent)
    assert create(app_settings).ready() == [MODEL_ITEM, PACKAGE_ITEM]


def test_27_installed_package_of_another_version_is_not_ready(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine.metadata, "version", lambda name: "0.0.0")
    assert PACKAGE_ITEM in create(app_settings).ready()


def _sparse(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)


def test_27_prepared_files_of_the_pinned_size_make_the_model_ready(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = lock_item(app_settings, MODEL_ITEM)
    package = lock_item(app_settings, PACKAGE_ITEM)
    for entry in item.files:
        _sparse(app_settings.model_dir / item.install_path / entry.file, entry.bytes)
    monkeypatch.setattr(engine.metadata, "version", lambda name: package.version)
    adapter = create(app_settings)
    assert adapter.ready() == []
    _sparse(app_settings.model_dir / item.install_path / item.files[0].file, 1)
    assert adapter.ready() == [MODEL_ITEM]


def test_27_a_lock_without_the_model_item_stops_the_start(app_settings: Settings) -> None:
    app_settings.runtime.items = [
        item for item in app_settings.runtime.items if item.id != MODEL_ITEM
    ]
    with pytest.raises(RuntimeError, match=MODEL_ITEM):
        create(app_settings)


def test_28_threads_come_from_the_setting_or_the_capped_cpu_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(engine.THREADS_ENV, raising=False)
    monkeypatch.setattr(engine.os, "cpu_count", lambda: 64)
    assert default_threads() == engine.MAX_DEFAULT_THREADS
    monkeypatch.setattr(engine.os, "cpu_count", lambda: 2)
    assert default_threads() == 2
    monkeypatch.setattr(engine.os, "cpu_count", lambda: None)
    assert default_threads() == 1
    monkeypatch.setenv(engine.THREADS_ENV, "6")
    assert default_threads() == 6


@pytest.mark.parametrize("value", ["0", "-1", "two", "", "1.5"])
def test_28_an_invalid_thread_setting_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(engine.THREADS_ENV, value)
    with pytest.raises(RuntimeError, match=engine.THREADS_ENV):
        default_threads()


def test_11_inference_wheel_content_changes_invalidate_cached_audio(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Wheel:
        metadata = {"Name": "synthetic-inference"}
        version = "1.0"

        def __init__(self, record: str) -> None:
            self.record = record

        def read_text(self, name: str) -> str:
            assert name == "RECORD"
            return self.record

    monkeypatch.setattr(engine.metadata, "distributions", lambda: [Wheel("one")])
    first = create(app_settings).info().runtime_digest
    monkeypatch.setattr(engine.metadata, "distributions", lambda: [Wheel("two")])
    assert create(app_settings).info().runtime_digest != first


def test_11_thread_and_worker_changes_invalidate_cached_audio(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text("# initial implementation", encoding="utf-8")
    monkeypatch.setattr(engine, "WORKER_PATH", worker)
    monkeypatch.setenv(engine.THREADS_ENV, "1")
    first = create(app_settings).info().runtime_digest
    monkeypatch.setenv(engine.THREADS_ENV, "2")
    threaded = create(app_settings).info().runtime_digest
    assert threaded != first
    worker.write_text("# updated implementation", encoding="utf-8")
    assert create(app_settings).info().runtime_digest not in (first, threaded)
