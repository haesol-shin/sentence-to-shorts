"""The runtime preparer leaves speech models and wheels to the development setup script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.runtime import journal
from app.runtime.lock import select_file
from app.runtime.prepare import prepare, status
from tests.runtime.support import (
    FakeTransport,
    Flag,
    lock_item,
    make_settings,
    make_zip,
    noise,
    url_of,
)

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "core" / "config" / "runtime.lock.json"
HOSTS = [("linux", "x86_64"), ("linux", "aarch64"), ("windows", "x86_64")]
DENO_BLOB = make_zip({"deno": noise(2_000, "deno")}, modes={"deno": 0o755})
MODEL_BLOB = noise(3_000, "model")
WHEEL_BLOB = noise(1_000, "wheel")


def speech_lock() -> list[dict]:
    return [
        lock_item("model-tts-synthetic", "Synthetic-TTS", "weights.bin", MODEL_BLOB),
        lock_item("package-synthetic", "python-wheels/synthetic", "synthetic-1.0.whl", WHEEL_BLOB),
        lock_item("deno", "deno", "deno-linux.zip", DENO_BLOB, os_name="linux", arch="x86_64"),
    ]


def test_speech_items_prepare_downloads_only_runtime_files(tmp_path: Path) -> None:
    items = speech_lock()
    settings = make_settings(tmp_path, items)
    urls = [url_of(item) for item in items]
    blobs = dict(zip(urls, [MODEL_BLOB, WHEEL_BLOB, DENO_BLOB], strict=True))
    transport = FakeTransport(blobs)
    ready = prepare(settings, cancel=Flag(), transport=transport, target=("linux", "x86_64"))
    assert ready == ["deno"]
    assert [url for url, _start in transport.opens] == [url_of(items[2])]
    root = settings.runtime_dir
    assert set(journal.read(root)) == {"deno"}
    assert not (root / "Synthetic-TTS").exists()
    assert not (root / "python-wheels").exists()


def test_speech_items_prepare_does_not_fail_on_a_host_without_a_file(tmp_path: Path) -> None:
    items = [
        lock_item("model-tts-synthetic", "Synthetic-TTS", "weights.bin", MODEL_BLOB,
                  os_name="windows", arch="x86_64"),
    ]
    settings = make_settings(tmp_path, items)
    transport = FakeTransport({})
    assert prepare(settings, cancel=Flag(), transport=transport, target=("linux", "aarch64")) == []
    assert transport.count == 0


def test_speech_items_status_lists_only_runtime_files(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, speech_lock())
    rows = status(settings, ("linux", "aarch64"))
    assert [row.id for row in rows] == ["deno"]


@pytest.mark.parametrize("host", HOSTS)
def test_speech_items_shipped_lock_entries_fit_every_host(host: tuple[str, str]) -> None:
    spec = importlib.util.spec_from_file_location("dev_setup", ROOT / "scripts" / "dev_setup.py")
    assert spec is not None and spec.loader is not None
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    items = [
        item
        for item in json.loads(LOCK.read_text(encoding="utf-8"))["items"]
        if item["id"].startswith(("model-", "package-"))
    ]
    assert {item["id"] for item in items} == {
        "package-qwen-tts",
        "model-tts-qwen3-0.6b",
        "model-align-ko",
        "model-align-en",
        "model-asr-small",
    }
    for item in items:
        assert select_file(item, host) is not None, item["id"]
        assert setup.select_file(item, *host) == item["files"][0]
