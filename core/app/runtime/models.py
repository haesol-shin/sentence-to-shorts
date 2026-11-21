"""Prepare the pinned model files, and say which models a job needs first.

The models of the runtime lock (`model-` items) are too big for the installer, so the app
downloads them in the background once the server is up. They are prepared in groups, in
the order a user needs them: `voice` (speech synthesis, Korean alignment and the sentence
splitter) when the app starts, `transcribe` when the first reference video arrives and
`align_en` when the first English project is made. `scripts/dev_setup.py` calls the same
`prepare_models`, so an item has exactly one way to be installed.

A file whose URL is a Hugging Face `resolve` URL goes through the official client, which
downloads in parallel with `hf_xet` and resumes by itself. Every other file goes through
`download.fetch`, which resumes from its `.part` file. Both end in the same check: the
locked size and SHA-256 must match before the file replaces the one in place, so a bad
download never damages a good file. A model item is ready once its journal record names
the locked revision and every file has the locked size; the hash is only computed while
downloading.
"""

from __future__ import annotations

import contextlib
import errno
import os
import re
import threading
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from app.ports import AppError, CancelToken
from app.runtime import archive, download, fsutil, journal
from app.runtime.lock import (
    Item,
    Target,
    host_files,
    host_platform,
    relative_install_path,
)
from app.runtime.prepare import DISCARD_CODES, STAGING_DIR, Hooks, active, model_state
from app.schemas.api import RuntimeItemState

VOICE = "voice"
TRANSCRIBE = "transcribe"
ALIGN_EN = "align_en"
GROUP_MODELS: dict[str, tuple[str, ...]] = {
    VOICE: ("model-tts-qwen3-0.6b", "model-align-ko", "model-nltk-punkt-tab"),
    TRANSCRIBE: ("model-asr-small",),
    ALIGN_EN: ("model-align-en",),
}
"""Model items of each need group, in the order they are prepared. The group order is the
order of this table; a model item of the lock that is in no group is a test failure. The
name avoids the `_ITEMS` suffix, which the lock preflight reads as a list of lock IDs."""
GROUP_ORDER = tuple(GROUP_MODELS)
GROUP_PACKAGES: dict[str, tuple[str, ...]] = {VOICE: ("package-qwen-tts",)}
"""Wheels a group needs besides its models. The installer build installs them; they are
checked, never downloaded, so a missing one fails the group instead of waiting forever."""

POLL_S = 0.25
FREE_MARGIN = 256 << 20
_HF_URL = re.compile(
    r"^https://huggingface\.co/(?P<repo>[^/]+/[^/]+)/resolve/(?P<revision>[0-9a-f]{40})/"
    r"(?P<path>.+)$"
)
_HF_CACHE = (".cache", "huggingface", "download")
# Errors that mean the code is wrong, not the network, so retrying them would only loop.
_PROGRAMMING_ERRORS = (TypeError, AttributeError, ValueError, ImportError, KeyError)

HfDownload = Callable[[str, str, str, Path], str]
"""`(repo_id, filename, revision, local_dir) -> path of the downloaded file`."""


def group_items(items: Sequence[Item], group: str) -> list[Item]:
    """The lock items of one group, in the group's order; items the lock lacks are skipped."""
    by_id = {str(item["id"]): item for item in items}
    return [by_id[name] for name in GROUP_MODELS[group] if name in by_id]


def group_bytes(items: Sequence[Item], group: str, target: Target | None = None) -> int:
    """The bytes of every file of the group for this host."""
    target = target or host_platform()
    return sum(
        int(entry["bytes"])
        for item in group_items(items, group)
        for entry in host_files(item, target)
    )


def hf_source(url: str) -> tuple[str, str, str] | None:
    """`(repo_id, revision, path)` of a Hugging Face `resolve` URL, or None for any other URL."""
    found = _HF_URL.match(url)
    if found is None:
        return None
    return found["repo"], found["revision"], found["path"]


def hf_hub_download_file(repo_id: str, filename: str, revision: str, local_dir: Path) -> str:
    """Download one pinned file with the official client: no token, no telemetry."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import hf_hub_download

    return str(
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            local_dir=str(local_dir),
            token=False,
        )
    )


@dataclass
class _Transfer:
    """One client download that runs in its own thread."""

    finished: threading.Event = field(default_factory=threading.Event)
    path: str | None = None
    error: BaseException | None = None


_transfers: dict[str, _Transfer] = {}
_transfers_lock = threading.Lock()


def _start_transfer(key: str, call: Callable[[], str]) -> _Transfer:
    """Run `call` in a thread, or join the unfinished transfer of the same file.

    The client cannot be interrupted once a download runs. A cancelled job leaves its
    transfer behind, so a job that asks for the same file again waits for that transfer
    instead of starting a second writer on the same partial file.
    """
    with _transfers_lock:
        current = _transfers.get(key)
        if current is not None and not current.finished.is_set():
            return current
        transfer = _Transfer()
        _transfers[key] = transfer

    def work() -> None:
        try:
            transfer.path = call()
        except BaseException as error:  # noqa: BLE001 - handed to the waiting job thread
            transfer.error = error
        finally:
            transfer.finished.set()
            with _transfers_lock:
                if _transfers.get(key) is transfer:
                    del _transfers[key]

    threading.Thread(target=work, name="model-download", daemon=True).start()
    return transfer


def _partial_bytes(staging: Path, name: str) -> int:
    """Bytes the client has written so far, read from its resume file."""
    relative = PurePosixPath(name)
    folder = staging.joinpath(*_HF_CACHE, *relative.parent.parts)
    sizes = []
    try:
        for path in folder.glob(f"{relative.name}.*.incomplete"):
            sizes.append(path.stat().st_size)
    except OSError:
        return 0
    return max(sizes, default=0)


def _hf_error(error: BaseException) -> AppError:
    """Translate what the Hugging Face client raised into a job error code."""
    if isinstance(error, AppError):
        return error
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return AppError("disk_full")
    name = type(error).__name__
    from huggingface_hub import errors as hf_errors

    # Raised when the file is absent locally and the hub cannot be reached; it is also an
    # EntryNotFoundError, so it must be told apart before the permanent cases below.
    if isinstance(error, hf_errors.LocalEntryNotFoundError):
        return AppError("download_failed", detail={"reason": "connect", "error": name})
    missing = (
        hf_errors.RepositoryNotFoundError,
        hf_errors.RevisionNotFoundError,
        hf_errors.EntryNotFoundError,
        hf_errors.GatedRepoError,
    )
    if isinstance(error, missing):
        return AppError("model_missing", detail={"reason": "not_found", "error": name})
    if isinstance(error, hf_errors.HfHubHTTPError):
        response = getattr(error, "response", None)
        status = int(getattr(response, "status_code", 0) or 0)
        if 400 <= status < 500 and status not in (408, 429):
            return AppError("model_missing", detail={"reason": "http", "status": status})
        return AppError("download_failed", detail={"reason": "http", "status": status})
    if isinstance(error, _PROGRAMMING_ERRORS):
        return AppError("internal", detail={"error": name})
    # Connection loss, timeouts and the client's own transport errors: wait and resume.
    return AppError("download_failed", detail={"reason": "interrupted", "error": name})


def _mismatch(reason: str) -> AppError:
    return AppError("model_hash_mismatch", detail={"reason": reason})


def _fetch_hf(
    source: tuple[str, str, str],
    entry: dict[str, Any],
    final: Path,
    staging: Path,
    *,
    hf: HfDownload,
    cancel: CancelToken,
    on_progress: Callable[[int], None] | None,
) -> bool:
    size, sha256 = int(entry["bytes"]), str(entry["sha256"])
    cancel.raise_if_set()
    if download.verified(final, size, sha256, cancel):
        return False
    repo, revision, name = source
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging.joinpath(*archive.safe_parts(name))
    transfer = _start_transfer(str(staged), lambda: hf(repo, name, revision, staging))
    while not transfer.finished.wait(POLL_S):
        cancel.raise_if_set()
        if on_progress is not None:
            on_progress(_partial_bytes(staging, name))
    if transfer.error is not None:
        raise _hf_error(transfer.error)
    path = Path(str(transfer.path))
    try:
        sound = path.is_file() and path.stat().st_size == size
    except OSError:
        sound = False
    if not sound or fsutil.sha256_of(path, cancel) != sha256:
        path.unlink(missing_ok=True)
        raise _mismatch("size" if not sound else "sha256")
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(path, final)
        fsutil.fsync_dir(final.parent)
    except OSError as error:
        fsutil.raise_disk_full(error)
        raise
    if on_progress is not None:
        on_progress(size)
    return True


def fetch_locked_file(
    entry: dict[str, Any],
    final: Path,
    *,
    staging: Path,
    cancel: CancelToken,
    transport: download.Transport | None = None,
    hf: HfDownload | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> bool:
    """Make `final` hold the locked file; False when it already did.

    A Hugging Face file is fetched with the official client into `staging`, and any other
    file with the resumable downloader beside `final`. The locked size and SHA-256 are
    checked before `final` is touched.
    """
    source = hf_source(str(entry["url"]))
    if source is not None:
        return _fetch_hf(
            source,
            entry,
            final,
            staging,
            hf=hf or hf_hub_download_file,
            cancel=cancel,
            on_progress=on_progress,
        )
    return download.fetch(
        str(entry["url"]),
        final,
        size=int(entry["bytes"]),
        sha256=str(entry["sha256"]),
        transport=transport or download.HttpsTransport(),
        cancel=cancel,
        on_progress=on_progress,
    )


def _install_base(model_root: Path, item: Item) -> Path:
    """The folder of one item below the model root, checked to stay inside it."""
    base = model_root.joinpath(*relative_install_path(item).parts)
    _inside(model_root, base)
    return base


def _member(base: Path, relative: str) -> Path:
    path = base.joinpath(*archive.safe_parts(relative))
    _inside(base, path)
    return path


def _inside(root: Path, path: Path) -> None:
    if root.resolve() not in path.resolve().parents:
        raise AppError("download_blocked", detail={"reason": "path_escape"})


def _zip_ready(zipped: Path, target: Path) -> bool:
    """True when every member of the zip is already extracted at its recorded size."""
    try:
        with zipfile.ZipFile(zipped) as bundle:
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                member = target.joinpath(*archive.safe_parts(info.filename))
                if not member.is_file() or member.stat().st_size != info.file_size:
                    return False
    except (zipfile.BadZipFile, OSError):
        return False
    return True


def _members_ready(entries: Sequence[dict[str, Any]], base: Path) -> bool:
    """True when each zip file of the item has all its members extracted beside it."""
    return all(
        _zip_ready(_member(base, str(entry["file"])), base)
        for entry in entries
        if str(entry["file"]).endswith(".zip")
    )


def _extract_members(
    zipped: Path, target: Path, scratch: Path, *, size: int, cancel: CancelToken
) -> None:
    """Extract the zip beside its own file, replacing members that are missing or damaged."""
    fsutil.remove_tree(scratch)
    try:
        archive.extract(zipped, scratch, archive_bytes=size, cancel=cancel)
        for source in sorted(path for path in scratch.rglob("*") if path.is_file()):
            destination = target / source.relative_to(scratch)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
    finally:
        fsutil.remove_tree(scratch)


def _private_data_tree(root: Path) -> None:
    """Remove group and other write bits; NLTK refuses a data path they can write."""
    for path in [root, *root.rglob("*")]:
        path.chmod(0o700 if path.is_dir() else 0o644)


_journal_lock = threading.Lock()


def _record(model_root: Path, item: Item, entries: Sequence[dict[str, Any]]) -> None:
    with _journal_lock:
        records = journal.read(model_root)
        records[str(item["id"])] = {
            "version": item["version"],
            "revision": item["revision"],
            "install_path": item["install_path"],
            "files": {
                str(entry["file"]): {"bytes": entry["bytes"], "sha256": entry["sha256"]}
                for entry in entries
            },
        }
        journal.write(model_root, records)


class _Progress:
    """Bytes in place over all files of a run, from the files already there and a live one."""

    def __init__(self, total: int, done: int, hook: Callable[[int, int], None] | None) -> None:
        self.total = total
        self.done = done
        self._hook = hook

    def report(self, have: int = 0) -> None:
        if self._hook is not None:
            self._hook(min(self.done + have, self.total), self.total)


def _size_matches(path: Path, size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size == size
    except OSError:
        return False


def _check_space(model_root: Path, needed: int) -> None:
    model_root.mkdir(parents=True, exist_ok=True)
    free = fsutil.disk_free(model_root)
    if needed and free < needed + FREE_MARGIN:
        raise AppError("disk_full", detail={"needed": needed, "free": free})


def _prepare_item(
    model_root: Path,
    item: Item,
    entries: list[dict[str, Any]],
    progress: _Progress,
    *,
    cancel: CancelToken,
    transport: download.Transport | None,
    hooks: Hooks,
    hf: HfDownload | None,
) -> None:
    base = _install_base(model_root, item)
    staging = model_root / STAGING_DIR / str(item["id"])
    finals = [_member(base, str(entry["file"])) for entry in entries]
    missing = sum(
        int(entry["bytes"])
        for entry, final in zip(entries, finals, strict=True)
        if not _size_matches(final, int(entry["bytes"]))
    )
    _check_space(model_root, missing)
    fetched_files: set[str] = set()
    with hooks.scope("download"):
        for entry, final in zip(entries, finals, strict=True):
            cancel.raise_if_set()
            size = int(entry["bytes"])
            if _size_matches(final, size):
                if download.verified(final, size, str(entry["sha256"]), cancel):
                    continue
                progress.done -= size
            try:
                if fetch_locked_file(
                    entry,
                    final,
                    staging=staging,
                    cancel=cancel,
                    transport=transport,
                    hf=hf,
                    on_progress=progress.report,
                ):
                    fetched_files.add(str(entry["file"]))
            except OSError as error:
                fsutil.raise_disk_full(error)
                raise
            progress.done += size
            progress.report()
    with hooks.scope("verify"):
        for entry, final in zip(entries, finals, strict=True):
            name = str(entry["file"])
            if not name.endswith(".zip"):
                continue
            if name in fetched_files or not _zip_ready(final, base):
                scratch = model_root / STAGING_DIR / f"{item['id']}-members"
                _extract_members(final, base, scratch, size=int(entry["bytes"]), cancel=cancel)
            if base.parent != model_root:
                _private_data_tree(base.parent)
        _record(model_root, item, entries)
    fsutil.remove_tree(staging)


def prepare_models(
    model_root: Path,
    items: Sequence[Item],
    *,
    cancel: CancelToken,
    transport: download.Transport | None = None,
    hooks: Hooks | None = None,
    target: Target | None = None,
    hf: HfDownload | None = None,
) -> list[str]:
    """Download, verify and record every model item that is not ready; return all ids.

    Raises `AppError` with a job error code (`download_failed`, `model_hash_mismatch`,
    `disk_full`, `download_blocked`, `download_too_large`, `model_missing`) or `Cancelled`.
    A cancel and a lost connection keep the partial files, so the next call resumes; a
    file that fails the lock's size or hash is dropped, and the file already in place is
    never replaced by it.
    """
    target = target or host_platform()
    hooks = hooks or Hooks()
    todo: list[tuple[Item, list[dict[str, Any]]]] = []
    total = done = 0
    for item in items:
        entries = host_files(item, target)
        if not entries:
            raise AppError(
                "model_missing", detail={"item": str(item["id"]), "reason": "no_file"}
            )
        base = _install_base(model_root, item)
        size = sum(int(entry["bytes"]) for entry in entries)
        total += size
        state = model_state(
            model_root, item, entries, journal.read(model_root).get(str(item["id"]))
        )
        if state is RuntimeItemState.ready and _members_ready(entries, base):
            done += size
            continue
        done += sum(
            int(entry["bytes"])
            for entry in entries
            if _size_matches(_member(base, str(entry["file"])), int(entry["bytes"]))
        )
        todo.append((item, entries))
    progress = _Progress(total, done, hooks.progress)
    progress.report()
    for item, entries in todo:
        identifier = str(item["id"])
        try:
            with active(model_root, identifier):
                _prepare_item(
                    model_root,
                    item,
                    entries,
                    progress,
                    cancel=cancel,
                    transport=transport,
                    hooks=hooks,
                    hf=hf,
                )
        except AppError as error:
            if error.code in DISCARD_CODES:
                fsutil.remove_tree(model_root / STAGING_DIR / identifier)
            raise
        finally:
            staging_root = model_root / STAGING_DIR
            if staging_root.is_dir() and not any(staging_root.iterdir()):
                with contextlib.suppress(OSError):
                    staging_root.rmdir()
    return [str(item["id"]) for item in items]


__all__ = [
    "ALIGN_EN",
    "GROUP_MODELS",
    "GROUP_ORDER",
    "GROUP_PACKAGES",
    "TRANSCRIBE",
    "VOICE",
    "fetch_locked_file",
    "group_bytes",
    "group_items",
    "hf_hub_download_file",
    "hf_source",
    "prepare_models",
]
