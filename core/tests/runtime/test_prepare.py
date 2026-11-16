"""Runtime preparation: verified download, resume, cancel, disk, archives, journal."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.ports import AppError, Cancelled
from app.runtime import fsutil, journal
from app.runtime.prepare import ROLLBACK_NAME, Hooks, is_ready, prepare, status
from app.schemas.api import RuntimeItemState
from tests.runtime.support import (
    TARGET,
    FakeTransport,
    Flag,
    lock_item,
    make_settings,
    make_tar_bz2,
    make_zip,
    noise,
    url_of,
)

DENO_BLOB = make_zip({"deno": noise(700_000, "deno")}, modes={"deno": 0o755})
PYODIDE_BLOB = make_tar_bz2(
    {
        "pyodide/pyodide.mjs": b"export {};",
        "pyodide/pyodide-lock.json": b"{}",
        "pyodide/pyodide.asm.wasm": noise(50_000, "wasm"),
        "pyodide/python_stdlib.zip": noise(20_000, "std"),
    }
)
WHEEL_BLOB = noise(30_000, "wheel")


def deno_item() -> dict:
    return lock_item(
        "deno", "deno", "deno-linux.zip", DENO_BLOB, os_name="linux", arch="x86_64"
    )


def pyodide_items() -> list[dict]:
    return [
        lock_item("pyodide-core", "pyodide", "pyodide-core.tar.bz2", PYODIDE_BLOB),
        lock_item("pyodide-pillow", "pyodide", "pillow.whl", WHEEL_BLOB),
    ]


def only(item: dict, blob: bytes) -> FakeTransport:
    return FakeTransport({url_of(item): blob})


def serve(blobs: dict[str, bytes] | None = None, **kwargs) -> FakeTransport:
    table = {
        url_of(deno_item()): DENO_BLOB,
        url_of(pyodide_items()[0]): PYODIDE_BLOB,
        url_of(pyodide_items()[1]): WHEEL_BLOB,
    }
    table.update(blobs or {})
    return FakeTransport(table, **kwargs)


def run_prepare(settings, items, transport, cancel=None, **kwargs):  # type: ignore[no-untyped-def]
    return prepare(
        settings,
        items,
        cancel=cancel or Flag(),
        transport=transport,
        target=TARGET,
        **kwargs,
    )


def test_prepare_installs_items_and_writes_the_journal(tmp_path: Path) -> None:
    items = [deno_item(), *pyodide_items()]
    settings = make_settings(tmp_path, items)
    ready = run_prepare(settings, items, serve())
    assert ready == ["deno", "pyodide-core", "pyodide-pillow"]
    root = settings.runtime_dir
    assert (root / "deno" / "deno").is_file()
    assert (root / "pyodide" / "pyodide.mjs").is_file()
    assert (root / "pyodide" / "pillow.whl").read_bytes() == WHEEL_BLOB
    records = journal.read(root)
    assert records["deno"]["sha256"] == items[0]["files"][0]["sha256"]
    assert "deno/deno" in records["deno"]["files"]
    assert not (root / ".tmp").exists()
    assert all(is_ready(settings, item, TARGET) for item in items)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_prepare_keeps_the_executable_bit_of_archive_members(tmp_path: Path) -> None:
    items = [deno_item()]
    settings = make_settings(tmp_path, items)
    run_prepare(settings, items, serve())
    assert os.access(settings.runtime_dir / "deno" / "deno", os.X_OK)


def test_prepare_rejects_a_hash_mismatch_and_installs_nothing(tmp_path: Path) -> None:
    item = lock_item("deno", "deno", "deno-linux.zip", DENO_BLOB, os_name="linux",
                     arch="x86_64", sha256="0" * 64)
    settings = make_settings(tmp_path, [item])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], serve())
    assert caught.value.code == "model_hash_mismatch"
    root = settings.runtime_dir
    assert not (root / "deno").exists()
    assert journal.read(root) == {}
    assert not (root / ".tmp").exists()


def test_prepare_rejects_a_server_that_sends_more_bytes_than_locked(tmp_path: Path) -> None:
    item = deno_item()
    longer = {url_of(item): DENO_BLOB + b"extra"}
    settings = make_settings(tmp_path, [item])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], serve(blobs=longer))
    assert caught.value.code == "model_hash_mismatch"
    assert not list(settings.runtime_dir.rglob("*.part"))
    assert journal.read(settings.runtime_dir) == {}


def test_prepare_resumes_an_interrupted_download_with_a_range_request(tmp_path: Path) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    transport = serve(fail_after=[300_000])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], transport)
    assert caught.value.code == "download_failed"
    assert journal.read(settings.runtime_dir) == {}
    parts = list((settings.runtime_dir / ".tmp").rglob("*.part"))
    assert len(parts) == 1 and parts[0].stat().st_size == 300_000

    assert run_prepare(settings, [item], transport) == ["deno"]
    assert transport.opens == [(url_of(item), 0), (url_of(item), 300_000)]
    assert (settings.runtime_dir / "deno" / "deno").is_file()


def test_prepare_starts_over_when_the_server_ignores_the_range(tmp_path: Path) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    transport = serve(fail_after=[300_000], ranges=False)
    with pytest.raises(AppError):
        run_prepare(settings, [item], transport)
    assert run_prepare(settings, [item], transport) == ["deno"]
    assert is_ready(settings, item, TARGET)


def test_prepare_reports_a_server_error_as_a_retryable_download_failure(tmp_path: Path) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], serve(status_override=503))
    assert caught.value.code == "download_failed"
    assert caught.value.detail["status"] == 503


def test_prepare_cancel_removes_the_staging_folder_and_keeps_installed_items(
    tmp_path: Path,
) -> None:
    deno, core, _pillow = deno_item(), *pyodide_items()
    settings = make_settings(tmp_path, [deno, core])
    run_prepare(settings, [deno], serve())
    flag = Flag()

    def progress(done: int, total: int) -> None:
        if done > 0:
            flag.cancelled = True

    with pytest.raises(Cancelled):
        run_prepare(settings, [deno, core], serve(), flag, hooks=Hooks(progress=progress))
    root = settings.runtime_dir
    assert not (root / ".tmp").exists()
    assert not (root / "pyodide").exists()
    assert set(journal.read(root)) == {"deno"}
    assert is_ready(settings, deno, TARGET)


def test_prepare_cancel_before_the_first_byte_changes_nothing(tmp_path: Path) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    flag = Flag()
    flag.cancelled = True
    transport = serve()
    with pytest.raises(Cancelled):
        run_prepare(settings, [item], transport, flag)
    assert transport.count == 0
    assert not (settings.runtime_dir / "deno").exists()


def test_prepare_fails_with_disk_full_when_the_volume_has_no_room(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    monkeypatch.setattr(fsutil, "disk_free", lambda _path: 1_000)
    transport = serve()
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], transport)
    assert caught.value.code == "disk_full"
    assert transport.count == 0
    assert journal.read(settings.runtime_dir) == {}


def test_prepare_maps_a_full_disk_while_writing_to_disk_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    real = Path.open

    def failing(self, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name.endswith(".part") and mode in ("wb", "ab"):
            raise OSError(errno.ENOSPC, "no space")
        return real(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing)
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], serve())
    assert caught.value.code == "disk_full"


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "/absolute.txt",
        "a/../../escape.txt",
        "C:/drive.txt",
        pytest.param(
            "back\\slash.txt",
            marks=pytest.mark.skipif(
                sys.platform == "win32",
                reason="zipfile rewrites a backslash member name to a separator on Windows",
            ),
        ),
    ],
)
def test_prepare_rejects_zip_members_that_leave_the_install_folder(
    tmp_path: Path, name: str
) -> None:
    blob = make_zip({"deno": b"ok", name: b"evil"})
    item = lock_item("deno", "deno", "deno-linux.zip", blob, os_name="linux", arch="x86_64")
    settings = make_settings(tmp_path, [item])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], only(item, blob))
    assert caught.value.code == "download_blocked"
    assert not (tmp_path / "escape.txt").exists()
    assert not (settings.runtime_dir / "deno").exists()
    assert not (settings.runtime_dir / ".tmp").exists()
    assert journal.read(settings.runtime_dir) == {}


def test_prepare_rejects_a_tar_member_name_with_a_backslash(tmp_path: Path) -> None:
    blob = make_tar_bz2({"pyodide/pyodide.mjs": b"x", "back\\slash.txt": b"evil"})
    item = lock_item("pyodide-core", "pyodide", "core.tar.bz2", blob)
    settings = make_settings(tmp_path, [item])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], only(item, blob))
    assert caught.value.code == "download_blocked"
    assert caught.value.detail["reason"] == "bad_name"
    assert not (settings.runtime_dir / "pyodide").exists()
    assert not (settings.runtime_dir / ".tmp").exists()


def test_prepare_accepts_a_tar_whose_members_start_with_dot_slash(tmp_path: Path) -> None:
    root = tarfile.TarInfo("./")
    root.type = tarfile.DIRTYPE
    blob = make_tar_bz2({"./pyodide/pyodide.mjs": b"export {};"}, extra=[root])
    item = lock_item("pyodide-core", "pyodide", "core.tar.bz2", blob)
    settings = make_settings(tmp_path, [item])
    assert run_prepare(settings, [item], only(item, blob)) == ["pyodide-core"]
    assert (settings.runtime_dir / "pyodide" / "pyodide.mjs").read_bytes() == b"export {};"


def test_prepare_rejects_tar_links_and_special_members(tmp_path: Path) -> None:
    link = tarfile.TarInfo("pyodide/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    blob = make_tar_bz2({"pyodide/pyodide.mjs": b"x"}, extra=[link])
    item = lock_item("pyodide-core", "pyodide", "core.tar.bz2", blob)
    settings = make_settings(tmp_path, [item])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], only(item, blob))
    assert caught.value.code == "download_blocked"
    assert not (settings.runtime_dir / "pyodide").exists()


def test_prepare_rejects_an_archive_that_expands_far_beyond_its_size(tmp_path: Path) -> None:
    blob = _deflated_zip("deno", b"\0" * 60_000_000)
    assert len(blob) < 100_000
    item = lock_item("deno", "deno", "deno-linux.zip", blob, os_name="linux", arch="x86_64")
    settings = make_settings(tmp_path, [item])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], only(item, blob))
    assert caught.value.code == "download_too_large"
    assert not (settings.runtime_dir / "deno").exists()
    assert not (settings.runtime_dir / ".tmp").exists()


def _deflated_zip(name: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, data)
    return buffer.getvalue()


def test_prepare_second_run_downloads_nothing(tmp_path: Path) -> None:
    items = [deno_item(), *pyodide_items()]
    settings = make_settings(tmp_path, items)
    first = serve()
    run_prepare(settings, items, first)
    assert first.count == 3

    second = serve()
    assert run_prepare(settings, items, second) == ["deno", "pyodide-core", "pyodide-pillow"]
    assert second.count == 0


def test_prepare_installing_one_item_keeps_files_of_the_item_sharing_its_folder(
    tmp_path: Path,
) -> None:
    core, pillow = pyodide_items()
    settings = make_settings(tmp_path, [core, pillow])
    run_prepare(settings, [core, pillow], serve())
    (settings.runtime_dir / "pyodide" / "pyodide.mjs").unlink()
    assert not is_ready(settings, core, TARGET)
    assert is_ready(settings, pillow, TARGET)

    run_prepare(settings, [core, pillow], serve())
    assert (settings.runtime_dir / "pyodide" / "pyodide.mjs").is_file()
    assert (settings.runtime_dir / "pyodide" / "pillow.whl").is_file()


def test_status_reports_missing_ready_corrupt_and_downloading(tmp_path: Path) -> None:
    items = [deno_item(), *pyodide_items()]
    settings = make_settings(tmp_path, items)

    def states() -> dict[str, RuntimeItemState]:
        return {item.id: item.state for item in status(settings, TARGET)}

    assert set(states().values()) == {RuntimeItemState.missing}
    run_prepare(settings, items, serve())
    assert set(states().values()) == {RuntimeItemState.ready}
    (settings.runtime_dir / "deno" / "deno").write_bytes(b"short")
    assert states()["deno"] is RuntimeItemState.corrupt
    assert states()["pyodide-core"] is RuntimeItemState.ready

    seen: list[RuntimeItemState] = []

    def watch(done: int, total: int) -> None:
        seen.append(states()["deno"])

    run_prepare(settings, items, serve(), hooks=Hooks(progress=watch))
    assert RuntimeItemState.downloading in seen
    assert states()["deno"] is RuntimeItemState.ready
    assert {item.bytes for item in status(settings, TARGET) if item.id == "deno"} == {
        len(DENO_BLOB)
    }


def test_prepare_rejects_an_install_path_outside_the_runtime_folder(tmp_path: Path) -> None:
    item = lock_item("deno", "../outside", "deno-linux.zip", DENO_BLOB, os_name="linux",
                     arch="x86_64")
    settings = make_settings(tmp_path, [item])
    transport = serve()
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], transport)
    assert caught.value.code == "model_missing"
    assert transport.count == 0


def test_prepare_reports_an_item_without_a_file_for_this_host(tmp_path: Path) -> None:
    item = lock_item("deno", "deno", "deno-win.zip", DENO_BLOB, os_name="windows",
                     arch="x86_64")
    settings = make_settings(tmp_path, [item])
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [item], serve())
    assert caught.value.code == "model_missing"


def test_prepare_journal_is_readable_by_the_sandbox_runtime(tmp_path: Path) -> None:
    from app.tools.sandbox.runtime import SandboxRuntime

    items = [deno_item(), *pyodide_items()]
    settings = make_settings(tmp_path, items)
    run_prepare(settings, items, serve())
    runtime = SandboxRuntime(settings.runtime_dir, items)
    runtime._os, runtime._arch = TARGET
    runtime.verify()
    records = json.loads((settings.runtime_dir / "installed.json").read_text())
    assert records["pyodide-pillow"]["sha256"] == hashlib.sha256(WHEEL_BLOB).hexdigest()


def _fail_second_install_rename(monkeypatch: pytest.MonkeyPatch, marker: str) -> None:
    real = os.replace

    def failing(src, dst):  # type: ignore[no-untyped-def]
        if marker in str(src).replace("\\", "/") and ".tmp" in str(src):
            raise OSError(errno.ENOSPC, "no space")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", failing)


def test_prepare_failed_activation_restores_the_previous_install_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    run_prepare(settings, [item], serve())
    binary = settings.runtime_dir / "deno" / "deno"
    before = binary.read_bytes()
    newer = make_zip({"deno": noise(2_000, "newer")}, modes={"deno": 0o755})
    changed = lock_item("deno", "deno", "deno-linux.zip", newer, os_name="linux", arch="x86_64")
    _fail_second_install_rename(monkeypatch, "/wrapped/deno")
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [changed], only(changed, newer))
    assert caught.value.code == "disk_full"
    assert binary.read_bytes() == before
    assert journal.read(settings.runtime_dir)["deno"]["sha256"] == item["files"][0]["sha256"]
    assert is_ready(settings, item, TARGET)


def test_prepare_failed_journal_write_restores_the_previous_install_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    run_prepare(settings, [item], serve())
    binary = settings.runtime_dir / "deno" / "deno"
    before = binary.read_bytes()
    newer = make_zip({"deno": noise(2_000, "newer")}, modes={"deno": 0o755})
    changed = lock_item("deno", "deno", "deno-linux.zip", newer, os_name="linux", arch="x86_64")

    def failing(_root, _records):  # type: ignore[no-untyped-def]
        raise AppError("disk_full")

    monkeypatch.setattr(journal, "write", failing)
    with pytest.raises(AppError):
        run_prepare(settings, [changed], only(changed, newer))
    assert binary.read_bytes() == before
    assert is_ready(settings, item, TARGET)


def test_prepare_failed_merge_restores_the_replaced_files_of_a_shared_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core, pillow = pyodide_items()
    settings = make_settings(tmp_path, [core, pillow])
    run_prepare(settings, [core, pillow], serve())
    folder = settings.runtime_dir / "pyodide"
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    newer = make_tar_bz2({"pyodide/pyodide.mjs": b"new", "pyodide/pyodide-lock.json": b"{}"})
    changed = lock_item("pyodide-core", "pyodide", "pyodide-core.tar.bz2", newer)
    _fail_second_install_rename(monkeypatch, "/tree/pyodide/pyodide-lock.json")
    with pytest.raises(AppError):
        run_prepare(settings, [changed, pillow], only(changed, newer))
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before
    assert is_ready(settings, core, TARGET)


def _rename_faults(monkeypatch: pytest.MonkeyPatch) -> list:
    real = os.replace
    faults: list = []

    def failing(src, dst):  # type: ignore[no-untyped-def]
        source = str(src).replace("\\", "/")
        target = str(dst).replace("\\", "/")
        if any(fault(source, target) for fault in faults):
            raise OSError(errno.ENOSPC, "no space")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", failing)
    return faults


def _staging_of(settings, item):  # type: ignore[no-untyped-def]
    entry = item["files"][0]
    return settings.runtime_dir / ".tmp" / f"{item['id']}-{entry['sha256'][:12]}"


def _newer_deno() -> tuple[dict, bytes]:
    blob = make_zip({"deno": noise(2_000, "newer")}, modes={"deno": 0o755})
    return lock_item(
        "deno", "deno", "deno-linux.zip", blob, os_name="linux", arch="x86_64"
    ), blob


def _deno_activation(source: str, _target: str) -> bool:
    return "/wrapped/deno" in source and ".tmp" in source


def _deno_restore(source: str, _target: str) -> bool:
    return source.endswith("/old") and ".tmp" in source


def _merge_activation(source: str, _target: str) -> bool:
    return source.endswith("/tree/pyodide/pyodide.mjs")


def _merge_restore(source: str, _target: str) -> bool:
    return source.endswith("/old/pyodide/pyodide.mjs")


def test_prepare_recovers_a_backup_from_a_failed_rollback_after_the_digest_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    run_prepare(settings, [item], serve())
    root = settings.runtime_dir
    binary = root / "deno" / "deno"
    before = binary.read_bytes()
    changed, newer = _newer_deno()
    staging = _staging_of(settings, changed)
    faults = _rename_faults(monkeypatch)
    faults.extend([_deno_activation, _deno_restore])

    with pytest.raises(AppError) as caught:
        run_prepare(settings, [changed], only(changed, newer))
    assert caught.value.code == "disk_full"
    assert journal.read(root)["deno"]["sha256"] == item["files"][0]["sha256"]
    assert (staging / ROLLBACK_NAME).is_file()
    assert (staging / "old" / "deno").read_bytes() == before
    assert not binary.exists()

    faults.remove(_deno_activation)
    transport = only(changed, newer)
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [changed], transport)
    assert caught.value.code == "disk_full"
    assert transport.count == 0
    assert journal.read(root)["deno"]["sha256"] == item["files"][0]["sha256"]
    assert (staging / "old" / "deno").read_bytes() == before

    faults.clear()
    transport = serve()
    assert run_prepare(settings, [item], transport) == ["deno"]
    assert transport.count == 0
    assert binary.read_bytes() == before
    assert is_ready(settings, item, TARGET)
    assert not (root / ".tmp").exists()


def test_prepare_restores_a_backup_then_keeps_the_install_when_a_later_move_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    run_prepare(settings, [item], serve())
    root = settings.runtime_dir
    binary = root / "deno" / "deno"
    before = binary.read_bytes()
    changed, newer = _newer_deno()
    faults = _rename_faults(monkeypatch)
    faults.extend([_deno_activation, _deno_restore])

    with pytest.raises(AppError):
        run_prepare(settings, [changed], only(changed, newer))

    faults.remove(_deno_restore)
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [changed], only(changed, newer))
    assert caught.value.code == "disk_full"
    assert binary.read_bytes() == before
    assert journal.read(root)["deno"]["sha256"] == item["files"][0]["sha256"]
    assert is_ready(settings, item, TARGET)

    faults.clear()
    assert run_prepare(settings, [changed], only(changed, newer)) == ["deno"]
    assert binary.read_bytes() == noise(2_000, "newer")
    assert is_ready(settings, changed, TARGET)
    assert not (root / ".tmp").exists()


def test_prepare_recovers_a_failed_rollback_of_a_shared_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core, pillow = pyodide_items()
    settings = make_settings(tmp_path, [core, pillow])
    run_prepare(settings, [core, pillow], serve())
    root = settings.runtime_dir
    folder = root / "pyodide"
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    newer = make_tar_bz2(
        {"pyodide/pyodide.mjs": b"new", "pyodide/pyodide-lock.json": b'{"v":2}'}
    )
    changed = lock_item("pyodide-core", "pyodide", "pyodide-core.tar.bz2", newer)
    staging = _staging_of(settings, changed)
    faults = _rename_faults(monkeypatch)
    faults.extend([_merge_activation, _merge_restore])

    with pytest.raises(AppError) as caught:
        run_prepare(settings, [changed, pillow], only(changed, newer))
    assert caught.value.code == "disk_full"
    records = journal.read(root)
    assert records["pyodide-core"]["sha256"] == core["files"][0]["sha256"]
    assert records["pyodide-pillow"]["sha256"] == pillow["files"][0]["sha256"]
    assert (staging / ROLLBACK_NAME).is_file()
    assert (staging / "old" / "pyodide" / "pyodide.mjs").read_bytes() == before["pyodide.mjs"]
    assert (folder / "pyodide-lock.json").read_bytes() == b'{"v":2}'
    assert not is_ready(settings, core, TARGET)
    assert is_ready(settings, pillow, TARGET)

    faults.remove(_merge_activation)
    transport = only(changed, newer)
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [changed, pillow], transport)
    assert caught.value.code == "disk_full"
    assert transport.count == 0
    assert journal.read(root)["pyodide-core"]["sha256"] == core["files"][0]["sha256"]
    assert (staging / "old" / "pyodide" / "pyodide.mjs").read_bytes() == before["pyodide.mjs"]

    faults.clear()
    transport = serve()
    assert run_prepare(settings, [core, pillow], transport) == ["pyodide-core", "pyodide-pillow"]
    assert transport.count == 0
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before
    assert all(is_ready(settings, item, TARGET) for item in (core, pillow))
    assert not (root / ".tmp").exists()


def test_prepare_discards_a_committed_backup_without_rolling_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    run_prepare(settings, [item], serve())
    root = settings.runtime_dir
    binary = root / "deno" / "deno"
    changed, newer = _newer_deno()
    staging = _staging_of(settings, changed)

    real = fsutil.remove_tree
    hold = {"on": True}

    def keeping(path):  # type: ignore[no-untyped-def]
        if hold["on"] and Path(path) == staging and (staging / ROLLBACK_NAME).is_file():
            return
        real(path)

    monkeypatch.setattr(fsutil, "remove_tree", keeping)
    assert run_prepare(settings, [changed], only(changed, newer)) == ["deno"]
    assert binary.read_bytes() == noise(2_000, "newer")
    assert journal.read(root)["deno"]["sha256"] == changed["files"][0]["sha256"]
    assert (staging / "old" / "deno").is_file()

    hold["on"] = False
    transport = serve()
    assert run_prepare(settings, [changed], transport) == ["deno"]
    assert transport.count == 0
    assert binary.read_bytes() == noise(2_000, "newer")
    assert journal.read(root)["deno"]["sha256"] == changed["files"][0]["sha256"]
    assert not (root / ".tmp").exists()


def test_prepare_keeps_a_newer_committed_install_when_discarding_an_old_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    run_prepare(settings, [item], serve())
    root = settings.runtime_dir
    binary = root / "deno" / "deno"
    middle, middle_blob = _newer_deno()
    middle_staging = _staging_of(settings, middle)

    real = fsutil.remove_tree
    hold = {"on": True}

    def keeping(path):  # type: ignore[no-untyped-def]
        if hold["on"] and Path(path) == middle_staging:
            return
        real(path)

    monkeypatch.setattr(fsutil, "remove_tree", keeping)
    assert run_prepare(settings, [middle], only(middle, middle_blob)) == ["deno"]
    assert (middle_staging / "old" / "deno").is_file()

    newest = make_zip({"deno": noise(3_000, "newest")}, modes={"deno": 0o755})
    latest = lock_item(
        "deno", "deno", "deno-linux.zip", newest, os_name="linux", arch="x86_64"
    )
    assert run_prepare(settings, [latest], only(latest, newest)) == ["deno"]
    assert binary.read_bytes() == noise(3_000, "newest")
    assert journal.read(root)["deno"]["sha256"] == latest["files"][0]["sha256"]
    assert (middle_staging / ROLLBACK_NAME).is_file()

    hold["on"] = False
    transport = serve()
    assert run_prepare(settings, [latest], transport) == ["deno"]
    assert transport.count == 0
    assert binary.read_bytes() == noise(3_000, "newest")
    assert journal.read(root)["deno"]["sha256"] == latest["files"][0]["sha256"]
    assert not (root / ".tmp").exists()


def test_prepare_restores_the_previous_journal_when_a_commit_cannot_be_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = deno_item()
    settings = make_settings(tmp_path, [item])
    run_prepare(settings, [item], serve())
    binary = settings.runtime_dir / "deno" / "deno"
    before = binary.read_bytes()
    changed, newer = _newer_deno()
    real = journal.write
    calls = {"count": 0}

    def failing(root, records):  # type: ignore[no-untyped-def]
        real(root, records)
        calls["count"] += 1
        if calls["count"] == 1:
            raise AppError("disk_full")

    monkeypatch.setattr(journal, "write", failing)
    with pytest.raises(AppError) as caught:
        run_prepare(settings, [changed], only(changed, newer))
    assert caught.value.code == "disk_full"
    assert binary.read_bytes() == before
    record = journal.read(settings.runtime_dir)["deno"]
    assert record["sha256"] == item["files"][0]["sha256"]
    assert is_ready(settings, item, TARGET)
