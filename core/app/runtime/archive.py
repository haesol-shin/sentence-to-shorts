"""Safe extraction of a verified runtime archive into an empty staging folder.

Only regular files and folders are written, each through a path that is checked to stay
inside the staging folder. Absolute paths, drive letters, backslashes, `..` parts, links
and device files are refused. The bytes written are counted while extracting and capped
by a multiple of the archive size, so a small archive that expands without limit is
stopped before it fills the disk.
"""

from __future__ import annotations

import contextlib
import errno
import lzma
import os
import stat
import tarfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO

from app.ports import AppError, CancelToken
from app.runtime import fsutil

MAX_EXPANSION = 40
MAX_EXPANDED_BYTES = 4 << 30
MAX_MEMBERS = 20_000
FREE_MARGIN = 64 << 20
ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")
_STREAM = 1 << 20


def is_archive(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_SUFFIXES)


def _blocked(reason: str, name: str = "") -> AppError:
    detail: dict[str, str] = {"reason": reason}
    if name:
        detail["member"] = name[:80]
    return AppError("download_blocked", detail=detail)


def safe_parts(name: str) -> tuple[str, ...]:
    """The path parts of an archive member name; raise when it could leave the folder."""
    if not name or "\\" in name or "\0" in name:
        raise _blocked("bad_name", name)
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") or ":" in part for part in path.parts):
        raise _blocked("path_escape", name)
    return path.parts


@dataclass
class _Budget:
    """Bytes and members a single extraction may still use."""

    remaining: int
    members: int = MAX_MEMBERS

    def member(self) -> None:
        self.members -= 1
        if self.members < 0:
            raise AppError("download_too_large", detail={"reason": "members"})

    def take(self, count: int) -> None:
        self.remaining -= count
        if self.remaining < 0:
            raise AppError("download_too_large", detail={"reason": "expanded"})


def _target(root: Path, parts: tuple[str, ...]) -> Path:
    target = root.joinpath(*parts)
    resolved = target.resolve()
    if root.resolve() not in resolved.parents:
        raise _blocked("path_escape", "/".join(parts))
    return target


def _write_file(
    source: IO[bytes], target: Path, mode: int, budget: _Budget, cancel: CancelToken
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise _blocked("duplicate", target.name)
    free = fsutil.disk_free(target.parent)
    if free < FREE_MARGIN:
        raise AppError("disk_full", detail={"free": free})
    try:
        with target.open("xb") as out:
            for chunk in iter(lambda: source.read(_STREAM), b""):
                cancel.raise_if_set()
                budget.take(len(chunk))
                out.write(chunk)
    except OSError as error:
        if error.errno == errno.ENOSPC:
            raise AppError("disk_full") from error
        raise
    if os.name != "nt":
        target.chmod(0o755 if mode & 0o111 else 0o644)


def _zip_members(archive: zipfile.ZipFile) -> Iterator[tuple[zipfile.ZipInfo, int]]:
    for info in archive.infolist():
        mode = info.external_attr >> 16 if info.create_system == 3 else 0
        kind = stat.S_IFMT(mode)
        if kind == stat.S_IFLNK:
            raise _blocked("link", info.filename)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise _blocked("special", info.filename)
        yield info, mode


def _extract_zip(path: Path, root: Path, budget: _Budget, cancel: CancelToken) -> None:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise _blocked("unreadable") from error
    with archive:
        for info, mode in _zip_members(archive):
            budget.member()
            parts = safe_parts(info.filename.rstrip("/") if info.is_dir() else info.filename)
            if not parts:
                continue
            target = _target(root, parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            with archive.open(info) as source:
                _write_file(source, target, mode, budget, cancel)


def _extract_tar(path: Path, root: Path, budget: _Budget, cancel: CancelToken) -> None:
    try:
        with tarfile.open(path, mode="r|*") as archive:
            for member in archive:
                budget.member()
                parts = safe_parts(member.name.rstrip("/") if member.isdir() else member.name)
                if not parts:
                    continue
                target = _target(root, parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isreg():
                    link = member.issym() or member.islnk()
                    raise _blocked("link" if link else "special", member.name)
                source = archive.extractfile(member)
                if source is None:
                    raise _blocked("unreadable", member.name)
                with contextlib.closing(source):
                    _write_file(source, target, member.mode, budget, cancel)
    except (tarfile.TarError, EOFError, lzma.LZMAError) as error:
        raise _blocked("unreadable") from error
    except OSError as error:
        if error.errno == errno.ENOSPC:
            raise AppError("disk_full") from error
        raise


def extract(archive: Path, root: Path, *, archive_bytes: int, cancel: CancelToken) -> None:
    """Extract `archive` into the existing empty folder `root`."""
    root.mkdir(parents=True, exist_ok=True)
    budget = _Budget(remaining=min(MAX_EXPANDED_BYTES, MAX_EXPANSION * archive_bytes))
    if archive.name.lower().endswith((".zip", ".whl")):
        _extract_zip(archive, root, budget, cancel)
    else:
        _extract_tar(archive, root, budget, cancel)


def extract_member(
    archive: Path, member: str, target: Path, *, archive_bytes: int, cancel: CancelToken
) -> None:
    """Write the single regular file `member` of a zip or wheel to the new file `target`."""
    safe_parts(member)
    budget = _Budget(remaining=min(MAX_EXPANDED_BYTES, MAX_EXPANSION * archive_bytes))
    try:
        bundle = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as error:
        raise _blocked("unreadable") from error
    with bundle:
        for info, mode in _zip_members(bundle):
            if info.filename == member and not info.is_dir():
                with bundle.open(info) as source:
                    _write_file(source, target, mode, budget, cancel)
                return
    raise _blocked("member_missing", member)
