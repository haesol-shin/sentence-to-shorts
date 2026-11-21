"""Prepare the pinned runtime files: download, verify, extract, install, journal.

Every step is safe to repeat. Files are fetched into `.tmp/<item>-<sha12>/` below the
runtime root (the same volume as the install, so the final move is one rename), checked
against the locked bytes and SHA-256, extracted into a staging tree and moved into place.
The journal record is written last, so a crash at any point leaves the item "not ready"
and the next run continues from what is already on disk. A second run with everything
ready touches no network. A cancel removes the staging folder of the running item.

Before the install folder changes, a rollback record names the previous journal entry,
the entry being written and the files kept aside under `staging/old`. The record is
removed only after the journal commits or the previous installation is restored. A run
starts by recovering any record left by an earlier failure, before downloading or
activating anything. Recovery never discards a backup that it cannot replace with a
committed install, and stops when the journal and the backup disagree.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
import sys
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.ports import AppError, AppSettings, Cancelled, CancelToken
from app.runtime import archive, download, fsutil, journal
from app.runtime.lock import (
    MODEL_PREFIX,
    Item,
    Target,
    all_lock_items,
    archive_member,
    download_name,
    host_files,
    host_platform,
    install_dir,
    installed_path,
    lock_items,
    relative_install_path,
    require_file,
    runtime_owned,
    select_file,
    shares_install_path,
    wheel_binary,
)
from app.schemas.api import RuntimeItem, RuntimeItemState

STAGING_DIR = ".tmp"
ROLLBACK_NAME = ".rollback.json"
ROLLBACK_VERSION = 1
PACKAGE_JOURNAL_NAME = "packages.installed.json"
# `python` of a package record that an installer build wrote; see `_package_state`.
BUNDLE_PYTHON = "bundle"
# Archives that fail these checks are bad input for the lock, so their staging is dropped.
DISCARD_CODES = frozenset({"download_blocked", "download_too_large", "model_hash_mismatch"})

_active: set[tuple[str, str]] = set()
_active_lock = threading.Lock()


@dataclass(frozen=True)
class Hooks:
    """Optional callbacks: bytes progress over the whole plan and named stage scopes."""

    progress: Callable[[int, int], None] | None = None
    stage: Callable[[str], AbstractContextManager[None]] | None = None

    def scope(self, name: str) -> AbstractContextManager[None]:
        return self.stage(name) if self.stage is not None else contextlib.nullcontext()


def _legacy_ready(base: Path, item: Item, record: Mapping[str, Any]) -> bool:
    """Readiness of a record that lists no files, as `scripts/dev_setup.py` writes it."""
    identifier = item["id"]
    if identifier == "deno":
        return (base / "deno").is_file() or (base / "deno.exe").is_file()
    if identifier == "pyodide-core":
        return all((base / name).is_file() for name in ("pyodide.asm.wasm", "python_stdlib.zip"))
    if identifier == "pyodide-pillow":
        return isinstance(record.get("file"), str) and (base / record["file"]).is_file()
    return base.is_dir() and any(path.is_file() for path in base.rglob("*"))


def _record_ready(root: Path, item: Item, entry: Mapping[str, Any], record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("install_path") != item["install_path"]:
        return False
    if (record.get("file"), record.get("sha256")) != (entry["file"], entry["sha256"]):
        return False
    files = record.get("files")
    if not isinstance(files, dict):
        return _legacy_ready(install_dir(root, item), item, record)
    if not files:
        return False
    for relative, size in files.items():
        path = root.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file() or path.stat().st_size != size:
            return False
    return True


def is_ready(settings: AppSettings, item: Item, target: Target | None = None) -> bool:
    """True when the journal and the files on disk match the lock for this host."""
    entry = select_file(item, target or host_platform())
    if entry is None:
        return False
    root = settings.runtime_dir
    return _record_ready(root, item, entry, journal.read(root).get(str(item["id"])))


def model_state(
    model_dir: Path, item: Item, entries: Sequence[Mapping[str, Any]], record: Any
) -> RuntimeItemState:
    """Readiness of a `model-` item from the model journal and the files on disk."""
    if not isinstance(record, dict) or record.get("revision") != item["revision"]:
        return RuntimeItemState.missing
    base = model_dir.joinpath(*relative_install_path(item).parts)
    for entry in entries:
        path = base.joinpath(*PurePosixPath(str(entry["file"])).parts)
        # Size only: a locked model file can be gigabytes, so this request never hashes it.
        try:
            matches = path.is_file() and path.stat().st_size == int(entry["bytes"])
        except OSError:
            matches = False
        if not matches:
            return RuntimeItemState.corrupt
    return RuntimeItemState.ready


def _package_state(item: Item, entry: Mapping[str, Any], record: Any) -> RuntimeItemState:
    """Readiness of a `package-` item from the wheel journal.

    A record made by `scripts/dev_setup.py` names the interpreter it installed into. An
    installer build writes `bundle` instead, because the folder can move after the build,
    so the installed distribution is compared by version through its metadata.
    """
    if not isinstance(record, dict):
        return RuntimeItemState.missing
    if record.get("sha256") != entry["sha256"]:
        return RuntimeItemState.corrupt
    python = record.get("python")
    if python == sys.executable:
        return RuntimeItemState.ready
    if python == BUNDLE_PYTHON and _installed_version(item) == item["version"]:
        return RuntimeItemState.ready
    return RuntimeItemState.corrupt


def _installed_version(item: Item) -> str | None:
    """The version of the distribution a `package-<name>` item installs, if present."""
    try:
        return importlib.metadata.version(str(item["id"]).removeprefix("package-"))
    except importlib.metadata.PackageNotFoundError:
        return None


def write_package_record(
    runtime_root: Path, item: Item, entry: Mapping[str, Any], *, python: str = sys.executable
) -> None:
    """Record that a `package-` wheel is installed, next to the runtime journal.

    `python` is the interpreter that holds it, or `BUNDLE_PYTHON` for an installer build.
    The record is written after the install, so a missing record means "not installed".
    """
    path = runtime_root / PACKAGE_JOURNAL_NAME
    records = journal.read_path(path)
    records[str(item["id"])] = {
        "version": item["version"],
        "revision": item["revision"],
        "file": entry["file"],
        "sha256": entry["sha256"],
        "bytes": entry["bytes"],
        "install_path": item["install_path"],
        "python": python,
    }
    runtime_root.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    try:
        with scratch.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(records, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(scratch, path)
    except OSError as error:
        scratch.unlink(missing_ok=True)
        fsutil.raise_disk_full(error)
        raise
    fsutil.fsync_dir(runtime_root)


@contextlib.contextmanager
def active(root: Path, identifier: str) -> Iterator[None]:
    """Mark one item of the folder `root` as being downloaded while the block runs."""
    key = (str(root), identifier)
    with _active_lock:
        _active.add(key)
    try:
        yield
    finally:
        with _active_lock:
            _active.discard(key)


def status(settings: AppSettings, target: Target | None = None) -> list[RuntimeItem]:
    """One `RuntimeItem` per lock item, for `GET /runtime` and the prepare job.

    Items this preparer installs are read from the runtime journal. `model-` items come
    from the model journal that `app.runtime.models` writes (and `scripts/dev_setup.py`
    through it), and `package-` items from the wheel journal. Only an item being
    downloaded right now reports `downloading`.
    """
    target = target or host_platform()
    root = settings.runtime_dir
    records = journal.read(root)
    with _active_lock:
        running = {name for base, name in _active if base == str(root)}
        loading = {name for base, name in _active if base == str(settings.model_dir)}
    model_records: dict[str, dict[str, Any]] | None = None
    package_records: dict[str, dict[str, Any]] | None = None
    result = []
    for item in all_lock_items(settings):
        identifier = str(item["id"])
        entries = host_files(item, target)
        size = sum(int(entry["bytes"]) for entry in entries)
        if not entries:
            state = RuntimeItemState.missing
        elif identifier.startswith(MODEL_PREFIX):
            if identifier in loading:
                state = RuntimeItemState.downloading
            else:
                if model_records is None:
                    model_records = journal.read(settings.model_dir)
                state = model_state(
                    settings.model_dir, item, entries, model_records.get(identifier)
                )
        elif not runtime_owned(item):
            if package_records is None:
                package_records = journal.read_path(root / PACKAGE_JOURNAL_NAME)
            state = _package_state(item, entries[0], package_records.get(identifier))
        elif identifier in running:
            state = RuntimeItemState.downloading
        elif _record_ready(root, item, entries[0], records.get(identifier)):
            state = RuntimeItemState.ready
        elif isinstance(records.get(identifier, {}).get("files"), dict):
            state = RuntimeItemState.corrupt
        else:
            state = RuntimeItemState.missing
        result.append(RuntimeItem(id=identifier, state=state, bytes=size))
    return result


def _staging(root: Path, item: Item, entry: Mapping[str, Any]) -> Path:
    return root / STAGING_DIR / f"{item['id']}-{str(entry['sha256'])[:12]}"


def _staging_paths(root: Path, identifier: str) -> list[Path]:
    """Staging folders of one item, matching the exact `<id>-<sha12>` name."""
    base = root / STAGING_DIR
    if not base.is_dir():
        return []
    prefix = f"{identifier}-"
    paths = []
    for path in sorted(base.iterdir()):
        suffix = path.name.removeprefix(prefix)
        if (
            path.name.startswith(prefix)
            and len(suffix) == 12
            and all(character in "0123456789abcdef" for character in suffix)
            and path.is_dir()
            and not path.is_symlink()
        ):
            paths.append(path)
    return paths


def _metadata_parts(value: Any) -> tuple[str, ...]:
    """Path parts from the rollback record, refused unless they stay below the root."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise AppError("internal", detail={"reason": "rollback_metadata"})
    path = PurePosixPath(value)
    if path.is_absolute() or any(
        part in ("", ".", "..") or ":" in part for part in path.parts
    ):
        raise AppError("internal", detail={"reason": "rollback_metadata"})
    return path.parts


def _files_ready(root: Path, files: Any) -> bool:
    """True when every file the record lists is on disk with the recorded size."""
    if not isinstance(files, dict) or not files:
        return False
    for relative, size in files.items():
        if type(size) is not int:
            return False
        try:
            path = root.joinpath(*_metadata_parts(relative))
        except AppError:
            return False
        try:
            if not path.is_file() or path.stat().st_size != size:
                return False
        except OSError:
            return False
    return True


def _record_value(
    item: Item, entry: Mapping[str, Any], files: Mapping[str, int]
) -> dict[str, Any]:
    return {
        "version": item["version"],
        "revision": item["revision"],
        "file": entry["file"],
        "sha256": entry["sha256"],
        "bytes": entry["bytes"],
        "install_path": item["install_path"],
        "files": dict(files),
    }


def _rollback_payload(
    root: Path,
    item: Item,
    entry: Mapping[str, Any],
    files: Mapping[str, int],
    all_items: Sequence[Item],
) -> dict[str, Any]:
    """The durable record that lets a later run undo an unfinished activation."""
    payload: dict[str, Any] = {
        "version": ROLLBACK_VERSION,
        "item": str(item["id"]),
        "previous": journal.read(root).get(str(item["id"])),
        "next": _record_value(item, entry, files),
    }
    if shares_install_path(item, all_items):
        payload["kind"] = "merge"
        payload["files"] = [
            {
                "path": relative,
                "existed": root.joinpath(*_metadata_parts(relative)).exists(),
            }
            for relative in files
        ]
    else:
        payload["kind"] = "swap"
        payload["had_old"] = install_dir(root, item).exists()
    return payload


def _write_rollback(staging: Path, payload: Mapping[str, Any]) -> None:
    path = staging / ROLLBACK_NAME
    scratch = path.with_name(path.name + ".tmp")
    try:
        with scratch.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(scratch, path)
    except OSError as error:
        scratch.unlink(missing_ok=True)
        fsutil.raise_disk_full(error)
        raise
    fsutil.fsync_dir(staging)


def _drop_rollback(staging: Path) -> None:
    (staging / ROLLBACK_NAME).unlink(missing_ok=True)


def _read_rollback(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AppError("internal", detail={"reason": "rollback_metadata"}) from error
    if (
        not isinstance(payload, dict)
        or payload.get("version") != ROLLBACK_VERSION
        or payload.get("kind") not in ("merge", "swap")
    ):
        raise AppError("internal", detail={"reason": "rollback_metadata"})
    return payload


def _restore_swap(dest: Path, old: Path, had_old: bool) -> None:
    """Put the folder saved under `old` back at `dest`, unless it was never moved."""
    if old.exists():
        fsutil.remove_tree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(old, dest)
    elif had_old:
        if not dest.exists():
            raise AppError("internal", detail={"reason": "rollback_missing"})
    else:
        fsutil.remove_tree(dest)
    if dest.parent.is_dir():
        fsutil.fsync_dir(dest.parent)


def _restore_merge(root: Path, old: Path, files: Any) -> None:
    """Put the files saved under `old` back and remove the ones the item only added."""
    if not isinstance(files, list):
        raise AppError("internal", detail={"reason": "rollback_metadata"})
    parents: set[Path] = set()
    for entry in reversed(files):
        if not isinstance(entry, dict):
            raise AppError("internal", detail={"reason": "rollback_metadata"})
        parts = _metadata_parts(entry.get("path"))
        target = root.joinpath(*parts)
        existed = entry.get("existed")
        if not isinstance(existed, bool):
            raise AppError("internal", detail={"reason": "rollback_metadata"})
        backup = old.joinpath(*parts)
        parents.add(target.parent)
        if backup.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, target)
        elif not existed:
            target.unlink(missing_ok=True)
    for parent in sorted(parents):
        if parent.is_dir():
            fsutil.fsync_dir(parent)


def _restore_journal(root: Path, identifier: str, previous: Any) -> None:
    """Put the previous record back when an activation wrote a record it could not keep."""
    records = journal.read(root)
    if records.get(identifier) == previous:
        return
    if previous is None:
        records.pop(identifier, None)
    else:
        records[identifier] = previous
    journal.write(root, records)


def _restore_backup(root: Path, staging: Path, payload: Mapping[str, Any]) -> None:
    kind = payload.get("kind")
    if kind == "swap":
        next_record = payload.get("next")
        if not isinstance(next_record, dict):
            raise AppError("internal", detail={"reason": "rollback_metadata"})
        dest = root.joinpath(*_metadata_parts(next_record.get("install_path")))
        had_old = payload.get("had_old")
        if not isinstance(had_old, bool):
            raise AppError("internal", detail={"reason": "rollback_metadata"})
        _restore_swap(dest, staging / "old", had_old)
    elif kind == "merge":
        _restore_merge(root, staging / "old", payload.get("files"))
    else:
        raise AppError("internal", detail={"reason": "rollback_metadata"})


def _recover_pending(root: Path, staging: Path, payload: Mapping[str, Any]) -> None:
    """Finish or discard one outstanding rollback record without losing a good install."""
    identifier = payload.get("item")
    previous = payload.get("previous")
    next_record = payload.get("next")
    if (
        not isinstance(identifier, str)
        or (previous is not None and not isinstance(previous, dict))
        or not isinstance(next_record, dict)
        or not isinstance(next_record.get("files"), dict)
    ):
        raise AppError("internal", detail={"reason": "rollback_metadata"})
    current = journal.read(root).get(identifier)
    # A journal record whose files are intact wins over the leftover backup. A record
    # that is still the old one, the interrupted new one, or missing is rolled back;
    # anything else stops the run rather than guessing.
    if current == next_record and _files_ready(root, next_record["files"]):
        fsutil.remove_tree(staging)
        return
    if current == previous or current == next_record or current is None:
        # The journal goes back first so a failed file restore is retried on the next
        # run instead of looking like a committed new install.
        _restore_journal(root, identifier, previous)
        _restore_backup(root, staging, payload)
        fsutil.remove_tree(staging)
        return
    if isinstance(current, dict) and _files_ready(root, current.get("files")):
        fsutil.remove_tree(staging)
        return
    raise AppError("internal", detail={"reason": "rollback_conflict"})


def _recover_staging(root: Path, item: Item) -> None:
    """Recover every outstanding backup of an item before a new download or activation."""
    identifier = str(item["id"])
    for path in _staging_paths(root, identifier):
        metadata = path / ROLLBACK_NAME
        if not metadata.is_file():
            continue
        payload = _read_rollback(metadata)
        if payload.get("item") != identifier:
            raise AppError("internal", detail={"reason": "rollback_metadata"})
        _recover_pending(root, path, payload)


def _drop_stale_staging(root: Path, item: Item, keep: Path) -> None:
    for path in _staging_paths(root, str(item["id"])):
        if path == keep:
            continue
        if (path / ROLLBACK_NAME).is_file() or (path / "old").exists():
            continue
        fsutil.remove_tree(path)


def _staged_files(staged: Path) -> dict[str, int]:
    """Regular files below `staged`, keyed by their path relative to the runtime root."""
    files = {}
    for path in sorted(staged.rglob("*")):
        if path.is_file():
            files[path.relative_to(staged).as_posix()] = path.stat().st_size
    return files


def _require_member(staged: Path, install: PurePosixPath, member: str) -> None:
    """The locked executable must be in the archive; the host may need to run it."""
    try:
        parts = archive.safe_parts(member)
    except AppError:
        raise AppError("download_blocked", detail={"reason": "bad_member"}) from None
    path = staged.joinpath(*install.parts, *parts)
    if path.is_symlink() or not path.is_file():
        raise AppError("download_blocked", detail={"reason": "member_missing"})
    if os.name != "nt":
        path.chmod(path.stat().st_mode | 0o111)


def _build_tree(staging: Path, item: Item, entry: Mapping[str, Any], cancel: CancelToken) -> Path:
    """Lay the downloaded file out as it will appear below the runtime root."""
    install = relative_install_path(item)
    tree = staging / "tree"
    fsutil.remove_tree(tree)
    tree.mkdir(parents=True)
    source = staging / download_name(entry)
    binary = wheel_binary(entry)
    if binary is not None:
        wrapped = staging / "wrapped"
        fsutil.remove_tree(wrapped)
        target = wrapped.joinpath(*install.parts, str(entry["file"]))
        target.parent.mkdir(parents=True)
        archive.extract_member(
            source, binary, target, archive_bytes=int(entry["bytes"]), cancel=cancel
        )
        if os.name != "nt":
            target.chmod(target.stat().st_mode | 0o111)
        return wrapped
    member = archive_member(entry)
    if member or archive.is_archive(source.name):
        archive.extract(source, tree, archive_bytes=int(entry["bytes"]), cancel=cancel)
        tops = {path.name for path in tree.iterdir()}
        if tops == {install.parts[0]} and (tree / install.parts[0]).is_dir():
            staged = tree
        else:
            wrapped = staging / "wrapped"
            fsutil.remove_tree(wrapped)
            target = wrapped.joinpath(*install.parts)
            target.parent.mkdir(parents=True)
            os.replace(tree, target)
            staged = wrapped
        if member:
            _require_member(staged, install, str(entry["file"]))
        return staged
    wrapped = staging / "wrapped"
    fsutil.remove_tree(wrapped)
    target = wrapped.joinpath(*install.parts, str(entry["file"]))
    target.parent.mkdir(parents=True)
    os.replace(source, target)
    if os.name != "nt" and target.suffix == "":
        # A bare file without an extension is a program (yt-dlp); wheels and data keep their mode.
        target.chmod(target.stat().st_mode | 0o111)
    return wrapped


def _swap_in(
    root: Path, item: Item, staged: Path, staging: Path, had_old: bool
) -> Callable[[], None]:
    """Replace the whole install folder; return the function that puts the old one back.

    The old folder moves to `staging/old` after the rollback record is durable and stays
    there until the journal names the new files, so a failed activation never leaves the
    item without its executable.
    """
    dest = install_dir(root, item)
    new = install_dir(staged, item)
    old = staging / "old"
    if old.exists():
        raise AppError("internal", detail={"reason": "rollback_conflict"})
    dest.parent.mkdir(parents=True, exist_ok=True)

    def undo() -> None:
        _restore_swap(dest, old, had_old)

    if had_old:
        os.replace(dest, old)

    try:
        os.replace(new, dest)
        fsutil.fsync_dir(dest.parent)
    except BaseException:
        try:
            undo()
        except BaseException:
            raise
        _drop_rollback(staging)
        raise
    return undo


def _merge_in(
    root: Path,
    staged: Path,
    staging: Path,
    files: Sequence[Mapping[str, Any]],
) -> Callable[[], None]:
    """Move the files into a folder that another item also installs into.

    Replaced files are kept under `staging/old`; the returned function restores them.
    """
    old = staging / "old"
    if old.exists():
        raise AppError("internal", detail={"reason": "rollback_conflict"})

    def undo() -> None:
        _restore_merge(root, old, list(files))

    parents: set[Path] = set()
    try:
        for entry in files:
            parts = _metadata_parts(entry.get("path"))
            target = root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            parents.add(target.parent)
            if entry["existed"]:
                backup = old.joinpath(*parts)
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            os.replace(staged.joinpath(*parts), target)
        for parent in sorted(parents):
            fsutil.fsync_dir(parent)
    except BaseException:
        try:
            undo()
        except BaseException:
            raise
        _drop_rollback(staging)
        raise
    return undo


def _install_item(
    settings: AppSettings,
    item: Item,
    entry: Mapping[str, Any],
    all_items: Sequence[Item],
    transport: download.Transport,
    cancel: CancelToken,
    hooks: Hooks,
    base: int,
    total: int,
) -> None:
    root = settings.runtime_dir
    staging = _staging(root, item, entry)
    _drop_stale_staging(root, item, staging)
    final = staging / download_name(entry)
    size = int(entry["bytes"])
    part = download.partial_path(final)
    have = part.stat().st_size if part.is_file() else 0
    if not final.is_file():
        needed = max(0, size - have) + archive.FREE_MARGIN
        staging.mkdir(parents=True, exist_ok=True)
        free = fsutil.disk_free(staging)
        if free < needed:
            raise AppError("disk_full", detail={"needed": needed, "free": free})

    def on_progress(done: int) -> None:
        if hooks.progress is not None:
            hooks.progress(base + done, total)

    with hooks.scope("download"):
        download.fetch(
            str(entry["url"]),
            final,
            size=size,
            sha256=str(entry["sha256"]),
            transport=transport,
            cancel=cancel,
            on_progress=on_progress,
        )
    with hooks.scope("verify"):
        try:
            _activate(root, item, entry, all_items, staging, cancel)
        except OSError as error:
            fsutil.raise_disk_full(error)
            raise
    fsutil.remove_tree(staging)


def _activate(
    root: Path,
    item: Item,
    entry: Mapping[str, Any],
    all_items: Sequence[Item],
    staging: Path,
    cancel: CancelToken,
) -> None:
    """Extract, move into place and journal, keeping a durable way back until it commits."""
    staged = _build_tree(staging, item, entry, cancel)
    files = _staged_files(staged)
    identifier = str(item["id"])
    payload = _rollback_payload(root, item, entry, files, all_items)
    previous = payload["previous"]
    _write_rollback(staging, payload)
    if payload["kind"] == "merge":
        undo = _merge_in(root, staged, staging, payload["files"])
    else:
        undo = _swap_in(root, item, staged, staging, bool(payload["had_old"]))
    try:
        _record(root, item, entry, files)
    except BaseException:
        # The journal goes back first so a failed file restore is retried on the next
        # run instead of looking like a committed new install.
        _restore_journal(root, identifier, previous)
        try:
            undo()
        except BaseException:
            raise
        _drop_rollback(staging)
        raise


def _record(root: Path, item: Item, entry: Mapping[str, Any], files: Mapping[str, int]) -> None:
    records = journal.read(root)
    previous = records.get(str(item["id"]), {}).get("files")
    records[str(item["id"])] = _record_value(item, entry, files)
    journal.write(root, records)
    if isinstance(previous, dict):
        for relative in previous.keys() - files.keys():
            with contextlib.suppress(OSError):
                root.joinpath(*PurePosixPath(relative).parts).unlink(missing_ok=True)


def _cleanup_after(error: BaseException, staging: Path) -> None:
    """Keep what a retry can reuse; drop everything after a cancel or a bad archive.

    `old` and the rollback record are never dropped here: together they hold the
    previous install when a rollback failed.
    """
    code = error.code if isinstance(error, AppError) else ""
    if isinstance(error, Cancelled) or code in DISCARD_CODES:
        names = [path.name for path in staging.iterdir()] if staging.is_dir() else []
    else:
        names = ["tree", "wrapped"]
    for name in names:
        if name not in ("old", ROLLBACK_NAME):
            fsutil.remove_tree(staging / name)
    if staging.is_dir() and not any(staging.iterdir()):
        staging.rmdir()


def prepare(
    settings: AppSettings,
    items: Sequence[Item] | None = None,
    *,
    cancel: CancelToken,
    transport: download.Transport | None = None,
    hooks: Hooks | None = None,
    target: Target | None = None,
) -> list[str]:
    """Download and install every item that is not ready; return the ids that are ready.

    Raises `AppError` with a job error code (`download_failed`, `model_hash_mismatch`,
    `disk_full`, `download_blocked`, `download_too_large`, `model_missing`) or `Cancelled`.
    """
    target = target or host_platform()
    transport = transport or download.HttpsTransport()
    hooks = hooks or Hooks()
    all_items = list(items) if items is not None else lock_items(settings)
    root = settings.runtime_dir
    # Finish interrupted rollbacks before choosing what to download: a restored install
    # may already be ready, and a pending backup must not be replaced by a new attempt.
    try:
        for item in all_items:
            _recover_staging(root, item)
    except OSError as error:
        fsutil.raise_disk_full(error)
        raise
    plan = []
    for item in all_items:
        entry = require_file(item, target)
        relative_install_path(item)
        if not _record_ready(root, item, entry, journal.read(root).get(str(item["id"]))):
            plan.append((item, entry))
    total = sum(int(entry["bytes"]) for _item, entry in plan)
    root.mkdir(parents=True, exist_ok=True)
    base = 0
    try:
        for item, entry in plan:
            cancel.raise_if_set()
            try:
                with active(root, str(item["id"])):
                    _install_item(
                        settings, item, entry, all_items, transport, cancel, hooks, base, total
                    )
            except BaseException as error:
                _cleanup_after(error, _staging(root, item, entry))
                raise
            base += int(entry["bytes"])
    finally:
        staging_root = root / STAGING_DIR
        if staging_root.is_dir() and not any(staging_root.iterdir()):
            with contextlib.suppress(OSError):
                staging_root.rmdir()
    return [str(item["id"]) for item in all_items]


__all__ = [
    "BUNDLE_PYTHON",
    "Hooks",
    "active",
    "installed_path",
    "is_ready",
    "lock_items",
    "model_state",
    "prepare",
    "status",
    "write_package_record",
]
