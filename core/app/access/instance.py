"""Process ownership of one data store, acquired before recovering pending requests."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO


def acquire_instance_lock(state_db: Path) -> BinaryIO:
    """Hold an OS lock until the returned handle closes or the process exits.

    Keep the lock file in place: unlinking it lets another process lock a different
    inode while an earlier owner is still running. The DB must not be opened or
    recovered until this nonblocking acquisition succeeds.
    """
    state_db.parent.mkdir(parents=True, exist_ok=True)
    handle = state_db.with_name(state_db.name + ".lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise RuntimeError("The data store is already in use by another server.") from error
        raise
    except BaseException:
        handle.close()
        raise
    return handle
