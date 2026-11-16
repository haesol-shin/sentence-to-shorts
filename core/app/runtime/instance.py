"""Single-instance lock and the small status record of the running launcher."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
from pathlib import Path
from typing import IO, Any

LOCK_NAME = "launcher.lock"
RECORD_NAME = "launcher.json"


class InstanceLock:
    """An exclusive OS lock on a file. The lock dies with the process, so a crash never
    leaves a stale lock. The file itself is never deleted."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: IO[bytes] | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        finally:
            handle.close()

    def __enter__(self) -> InstanceLock:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def write_record(path: Path, record: dict[str, Any]) -> None:
    """Publish the record with one atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(scratch, path)


def read_record(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def bind_free_socket(host: str, preferred: int) -> socket.socket:
    """A listening socket on `preferred`, or on a port the OS picks when that one is busy.

    The launcher hands this socket to the server, so the port cannot be taken between
    the choice and the start.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for port in (preferred, 0):
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            if sys.platform != "win32":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
            sock.bind((host.strip("[]"), port))
            sock.listen(128)
            return sock
        except OSError:
            sock.close()
            if port == 0:
                raise
    raise AssertionError("unreachable")
