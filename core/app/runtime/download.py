"""Resumable, verified download of one runtime file.

The file is written under a temporary name next to its final name and renamed only
after the byte count and the SHA-256 both match the lock. An interrupted download keeps
its partial file and the next call resumes it with a Range request; a server that does
not honour the range makes the download start over. A hash mismatch deletes the partial
file, because resuming cannot repair it.
"""

from __future__ import annotations

import contextlib
import errno
import http.client
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO, Protocol
from urllib.parse import urlsplit

from app.ports import AppError, CancelToken
from app.runtime.fsutil import fsync_dir, sha256_of

READ_SIZE = 256 * 1024
TIMEOUT_S = 30.0
PART_SUFFIX = ".part"


class Response(Protocol):
    """The part of an HTTP response the downloader reads."""

    status: int
    headers: Mapping[str, str]

    def read(self, size: int) -> bytes: ...

    def close(self) -> None: ...


class Transport(Protocol):
    def open(self, url: str, *, start: int, timeout: float) -> Response:
        """Open the URL from byte `start`. Raise AppError("download_failed") on failure."""


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urlsplit(newurl).scheme != "https":
            raise urllib.error.URLError("redirect leaves https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpsTransport:
    """urllib transport for https URLs. Redirects must stay on https."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_HttpsOnly())

    def open(self, url: str, *, start: int, timeout: float) -> Response:
        if urlsplit(url).scheme != "https":
            raise AppError("download_failed", detail={"reason": "not_https"})
        request = urllib.request.Request(url, headers={"User-Agent": "runtime-prepare"})
        if start:
            request.add_header("Range", f"bytes={start}-")
        try:
            return self._opener.open(request, timeout=timeout)  # type: ignore[return-value]
        except urllib.error.HTTPError as error:
            raise AppError(
                "download_failed", detail={"reason": "http", "status": int(error.code)}
            ) from error
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            raise AppError("download_failed", detail={"reason": "connect"}) from error


def partial_path(final: Path) -> Path:
    return final.with_name(final.name + PART_SUFFIX)


def verified(path: Path, size: int, sha256: str, cancel: CancelToken | None = None) -> bool:
    """True when the file has exactly the locked size and SHA-256."""
    return path.is_file() and path.stat().st_size == size and sha256_of(path, cancel) == sha256


def _mismatch(reason: str) -> AppError:
    return AppError("model_hash_mismatch", detail={"reason": reason})


def _answers_range(response: Response, have: int) -> bool:
    """True when the response continues at `have`; False when it is the whole file."""
    if response.status == 206:
        if response.headers.get("Content-Range", "").startswith(f"bytes {have}-"):
            return True
        raise AppError("download_failed", detail={"reason": "range"})
    if response.status == 200:
        return False
    raise AppError("download_failed", detail={"reason": "http", "status": int(response.status)})


def _copy(
    response: Response,
    handle: IO[bytes],
    have: int,
    size: int,
    cancel: CancelToken,
    on_progress: Callable[[int], None] | None,
) -> int:
    """Write the response to the partial file and return the bytes the file holds."""
    try:
        while True:
            cancel.raise_if_set()
            chunk = response.read(READ_SIZE)
            if not chunk:
                return have
            if have + len(chunk) > size:
                raise _mismatch("size_exceeded")
            handle.write(chunk)
            have += len(chunk)
            if on_progress is not None:
                on_progress(have)
    except (OSError, http.client.HTTPException, socket.timeout) as error:
        if isinstance(error, OSError) and error.errno == errno.ENOSPC:
            raise AppError("disk_full") from error
        raise AppError("download_failed", detail={"reason": "interrupted"}) from error


def _download_rest(
    url: str,
    part: Path,
    have: int,
    size: int,
    transport: Transport,
    cancel: CancelToken,
    on_progress: Callable[[int], None] | None,
    timeout: float,
) -> int:
    with contextlib.closing(transport.open(url, start=have, timeout=timeout)) as response:
        if have and not _answers_range(response, have):
            have = 0
        elif not have and response.status != 200:
            raise AppError(
                "download_failed", detail={"reason": "http", "status": int(response.status)}
            )
        if on_progress is not None:
            on_progress(have)
        try:
            with part.open("ab" if have else "wb") as handle:
                try:
                    return _copy(response, handle, have, size, cancel, on_progress)
                finally:
                    handle.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(handle.fileno())
        except AppError as error:
            if error.code == "model_hash_mismatch":
                part.unlink(missing_ok=True)
            raise
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise AppError("disk_full") from error
            raise


def fetch(
    url: str,
    final: Path,
    *,
    size: int,
    sha256: str,
    transport: Transport,
    cancel: CancelToken,
    on_progress: Callable[[int], None] | None = None,
    timeout: float = TIMEOUT_S,
) -> bool:
    """Make `final` hold the locked file. Return False when it was already there.

    `on_progress` receives the number of bytes the partial file holds, counting the
    bytes of a resumed partial file, so a caller can show progress against `size`.
    """
    cancel.raise_if_set()
    if verified(final, size, sha256, cancel):
        return False
    final.parent.mkdir(parents=True, exist_ok=True)
    part = partial_path(final)
    have = part.stat().st_size if part.is_file() else 0
    if have > size:
        part.unlink()
        have = 0
    if have < size:
        have = _download_rest(url, part, have, size, transport, cancel, on_progress, timeout)
    if have != size:
        raise AppError("download_failed", detail={"reason": "truncated"})
    if sha256_of(part, cancel) != sha256:
        part.unlink(missing_ok=True)
        raise _mismatch("sha256")
    try:
        os.replace(part, final)
        fsync_dir(final.parent)
    except OSError as error:
        if error.errno == errno.ENOSPC:
            raise AppError("disk_full") from error
        raise
    return True
