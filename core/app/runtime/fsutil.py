"""Small file helpers shared by the runtime modules."""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import sys
from pathlib import Path

from app.ports import AppError, CancelToken

CHUNK = 1 << 20


def raise_disk_full(error: OSError) -> None:
    """Translate a full-disk OSError into the app error; other errors pass through."""
    if error.errno == errno.ENOSPC:
        raise AppError("disk_full") from error


def disk_free(path: Path) -> int:
    """Free bytes on the volume that holds `path`."""
    return shutil.disk_usage(path).free


def fsync_dir(path: Path) -> None:
    """Flush a directory entry change. Windows has no directory fsync."""
    if sys.platform == "win32":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sha256_of(path: Path, cancel: CancelToken | None = None) -> str:
    """SHA-256 of a file; a set cancel token stops the read."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            if cancel is not None:
                cancel.raise_if_set()
            digest.update(chunk)
    return digest.hexdigest()


def remove_tree(path: Path) -> None:
    """Delete a folder, a file or a symlink without following a link."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
