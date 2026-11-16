"""Wheel verification and the executable path used by the media adapter."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools.media import adapter as media

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("dev_setup", ROOT / "scripts" / "dev_setup.py")
assert SPEC is not None and SPEC.loader is not None
dev_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev_setup)
FFMPEG = next(
    item
    for item in json.loads((ROOT / "core/config/runtime.lock.json").read_text())["items"]
    if item["id"] == "ffmpeg"
)


def _settings(root: Path) -> SimpleNamespace:
    item = SimpleNamespace(
        **{key: value for key, value in FFMPEG.items() if key != "files"},
        files=[SimpleNamespace(**entry) for entry in FFMPEG["files"]],
    )
    return SimpleNamespace(runtime=SimpleNamespace(items=[item]), runtime_dir=root)


@pytest.mark.parametrize("entry", FFMPEG["files"], ids=lambda entry: entry["file"])
def test_21_ffmpeg_wheel_installs_at_media_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: dict
) -> None:
    archive = tmp_path / entry["file"]
    payload = b"synthetic executable payload"
    with zipfile.ZipFile(archive, "w") as wheel:
        wheel.writestr(f"imageio_ffmpeg/binaries/{entry['file']}", payload)
        wheel.writestr("imageio_ffmpeg/__init__.py", b"not an executable")
    root = tmp_path / "rt"
    dev_setup.extract_item(FFMPEG, entry, archive, root)
    monkeypatch.setattr(media, "_platform", lambda: (entry["os"], entry["arch"]))
    binary = media.runtime_executable(_settings(root))
    assert binary is not None
    assert binary.read_bytes() == payload
    assert not (root / "imageio_ffmpeg").exists()
    if entry["os"] != "windows" and sys.platform != "win32":
        assert binary.stat().st_mode & 0o111 == 0o111


@pytest.mark.skipif(
    not os.environ.get("APP_TEST_FFMPEG_WHEEL"),
    reason="APP_TEST_FFMPEG_WHEEL names no downloaded host wheel",
)
def test_21_downloaded_host_wheel_verifies_and_runs_from_media_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = Path(os.environ["APP_TEST_FFMPEG_WHEEL"])
    entry = dev_setup.select_file(FFMPEG, dev_setup.host_os(), dev_setup.host_arch())
    assert wheel.stat().st_size == entry["bytes"]
    assert dev_setup.sha256(wheel) == entry["sha256"]

    def use_downloaded_wheel(url: str, destination: Path) -> None:
        assert url == entry["url"]
        shutil.copyfile(wheel, destination)

    monkeypatch.setattr(dev_setup, "download", use_downloaded_wheel)
    root = tmp_path / "rt"
    assert dev_setup.install({"items": [FFMPEG]}, root, force=False) == ["ffmpeg"]
    binary = media.runtime_executable(_settings(root))
    assert binary is not None and binary.is_file()
    with zipfile.ZipFile(wheel) as bundle:
        assert binary.read_bytes() == bundle.read(f"imageio_ffmpeg/binaries/{entry['file']}")
    result = subprocess.run([str(binary), "-version"], capture_output=True, check=True, timeout=30)
    assert f"ffmpeg version {FFMPEG['version']}" in result.stdout.decode()
