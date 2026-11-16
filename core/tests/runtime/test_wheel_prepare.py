"""An executable in a wheel uses the downloaded wheel's lock and normal preparation."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ports import AppError
from app.runtime import journal, prepare, status
from app.schemas.api import RuntimeItemState
from app.settings import RuntimeFile
from app.tools.media import adapter as media
from tests.runtime.support import TARGET, FakeTransport, Flag, make_zip, noise
from tests.runtime.test_packaging import build

MEMBER = "imageio_ffmpeg/binaries/ffmpeg-test"
BINARY = noise(100_000, "ffmpeg")


def wheel_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    blob = make_zip(
        {MEMBER: BINARY, "imageio_ffmpeg-0.8.1.dist-info/licenses/LICENSE": b"synthetic license"},
        modes={MEMBER: 0o755},
    )
    pin = {
        "id": "ffmpeg", "version": "1.0.0", "revision": "0" * 40, "install_path": "ffmpeg",
        "license": {"spdx": "GPL-3.0-or-later", "source_url": "https://source.invalid/ffmpeg"},
    }
    wheel = {
        "os": TARGET[0], "arch": TARGET[1], "member": MEMBER,
        "url": "https://download.invalid/ffmpeg-test.whl",
        "bytes": len(BINARY), "sha256": hashlib.sha256(BINARY).hexdigest(),
        "archive_bytes": len(blob), "archive_sha256": hashlib.sha256(blob).hexdigest(),
    }
    monkeypatch.setattr(build, "ffmpeg_entry", lambda _label: (pin, wheel))
    shipped = build.lock_with_ffmpeg({"schema_version": 1, "items": []}, "linux-x86_64")
    settings = SimpleNamespace(
        runtime_dir=tmp_path / "rt", runtime=RuntimeFile.model_validate(shipped)
    )
    monkeypatch.setattr(media, "_platform", lambda: TARGET)
    return settings, wheel, blob


def test_wheel_prepare_repairs_a_deleted_executable_then_downloads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, wheel, blob = wheel_settings(tmp_path, monkeypatch)
    transport = FakeTransport({wheel["url"]: blob})
    entry = settings.runtime.items[0].files[0]
    assert entry.bytes == len(blob) and entry.sha256 == hashlib.sha256(blob).hexdigest()
    binary = media.runtime_executable(settings)
    assert binary == settings.runtime_dir.resolve() / "ffmpeg" / MEMBER
    for attempt in range(2):
        assert prepare(settings, cancel=Flag(), transport=transport, target=TARGET) == ["ffmpeg"]
        assert binary.read_bytes() == BINARY
        assert status(settings, TARGET)[0].state is RuntimeItemState.ready
        record = journal.read(settings.runtime_dir)["ffmpeg"]
        assert record["sha256"] == wheel["archive_sha256"]
        assert record["files"][f"ffmpeg/{MEMBER}"] == len(BINARY)
        if attempt == 0:
            binary.unlink()
    assert len(transport.opens) == 2
    prepare(settings, cancel=Flag(), transport=transport, target=TARGET)
    assert len(transport.opens) == 2


def test_wheel_prepare_rejects_a_changed_download_before_installing_its_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, wheel, blob = wheel_settings(tmp_path, monkeypatch)
    changed = bytes([blob[0] ^ 1]) + blob[1:]
    with pytest.raises(AppError) as caught:
        prepare(
            settings,
            cancel=Flag(),
            transport=FakeTransport({wheel["url"]: changed}),
            target=TARGET,
        )
    assert caught.value.code == "model_hash_mismatch"
    assert not (settings.runtime_dir / "ffmpeg").exists()
    assert journal.read(settings.runtime_dir) == {}


def test_wheel_prepare_refuses_a_wheel_without_its_locked_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, wheel, _blob = wheel_settings(tmp_path, monkeypatch)
    blob = make_zip({"other-file": b"not the executable"})
    entry = settings.runtime.items[0].files[0]
    entry.bytes = len(blob)
    entry.sha256 = hashlib.sha256(blob).hexdigest()
    with pytest.raises(AppError) as caught:
        prepare(
            settings,
            cancel=Flag(),
            transport=FakeTransport({wheel["url"]: blob}),
            target=TARGET,
        )
    assert caught.value.code == "download_blocked"
    assert not (settings.runtime_dir / "ffmpeg").exists()


def test_wheel_prepare_installs_an_executable_below_the_single_top_folder_of_a_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, wheel, _blob = wheel_settings(tmp_path, monkeypatch)
    member = "ffmpeg-build/bin/ffmpeg.exe"
    blob = make_zip({member: BINARY, "ffmpeg-build/LICENSE.txt": b"synthetic license"})
    url = "https://download.invalid/ffmpeg-build.zip"
    entry = settings.runtime.items[0].files[0]
    entry.file, entry.url = member, url
    entry.bytes, entry.sha256 = len(blob), hashlib.sha256(blob).hexdigest()
    transport = FakeTransport({url: blob})
    assert prepare(settings, cancel=Flag(), transport=transport, target=TARGET) == ["ffmpeg"]
    installed = settings.runtime_dir / "ffmpeg" / member
    assert installed.read_bytes() == BINARY
    assert media.runtime_executable(settings) == installed.resolve()
    assert status(settings, TARGET)[0].state is RuntimeItemState.ready
    assert wheel["url"] not in transport.opens


def test_wheel_prepare_installs_the_contract_ffmpeg_item_like_the_development_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "ffmpeg-linux-x86_64-test"
    blob = make_zip(
        {
            f"imageio_ffmpeg/binaries/{name}": BINARY,
            "imageio_ffmpeg/__init__.py": b"print('not installed')",
        },
        modes={f"imageio_ffmpeg/binaries/{name}": 0o644},
    )
    url = "https://download.invalid/imageio_ffmpeg-test.whl"
    lock = {
        "schema_version": 1,
        "items": [
            {
                "id": "ffmpeg", "version": "1.0.0", "revision": "0" * 40,
                "install_path": "ffmpeg",
                "license": {"spdx": "GPL-3.0-or-later", "source_url": "https://source.invalid/f"},
                "files": [
                    {
                        "os": TARGET[0], "arch": TARGET[1], "file": name, "url": url,
                        "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                    }
                ],
            }
        ],
    }
    settings = SimpleNamespace(
        runtime_dir=tmp_path / "rt", runtime=RuntimeFile.model_validate(lock)
    )
    monkeypatch.setattr(media, "_platform", lambda: TARGET)
    transport = FakeTransport({url: blob})
    assert prepare(settings, cancel=Flag(), transport=transport, target=TARGET) == ["ffmpeg"]
    binary = media.runtime_executable(settings)
    assert binary == settings.runtime_dir.resolve() / "ffmpeg" / name
    assert binary.read_bytes() == BINARY
    if os.name == "posix":
        assert binary.stat().st_mode & 0o111
    assert sorted(path.name for path in (settings.runtime_dir / "ffmpeg").iterdir()) == [name]
    assert status(settings, TARGET)[0].state is RuntimeItemState.ready
    prepare(settings, cancel=Flag(), transport=transport, target=TARGET)
    assert len(transport.opens) == 1
