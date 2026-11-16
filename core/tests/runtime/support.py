"""Fake lock items, archives and a range-capable fake transport for the runtime tests."""

from __future__ import annotations

import hashlib
import io
import stat
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.ports import AppError

TARGET = ("linux", "x86_64")


class Flag:
    """Cancel token that tests can set at a chosen moment."""

    def __init__(self) -> None:
        self.cancelled = False

    def is_set(self) -> bool:
        return self.cancelled

    def raise_if_set(self) -> None:
        if self.cancelled:
            from app.ports import Cancelled

            raise Cancelled("cancelled")

    def wait(self, seconds: float) -> bool:
        return self.cancelled


def noise(size: int, seed: str = "a") -> bytes:
    """Incompressible, reproducible bytes."""
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(f"{seed}{counter}".encode()).digest()
        counter += 1
    return bytes(out[:size])


def make_zip(members: dict[str, bytes], *, modes: dict[str, int] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = ((modes or {}).get(name, 0o644) | stat.S_IFREG) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def make_tar_bz2(members: dict[str, bytes], *, extra: list[tarfile.TarInfo] | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
        for info in extra or []:
            archive.addfile(info)
    return buffer.getvalue()


def lock_item(
    item_id: str,
    install_path: str,
    file: str,
    blob: bytes,
    *,
    os_name: str = "any",
    arch: str = "wasm32",
    sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "version": "1.0.0",
        "revision": "0" * 40,
        "install_path": install_path,
        "license": {"spdx": "MIT", "source_url": "https://example.invalid/x"},
        "files": [
            {
                "os": os_name,
                "arch": arch,
                "file": file,
                "url": f"https://download.invalid/{file}",
                "bytes": len(blob),
                "sha256": sha256 or hashlib.sha256(blob).hexdigest(),
            }
        ],
    }


def url_of(item: dict[str, Any]) -> str:
    return str(item["files"][0]["url"])


def make_settings(root: Path, items: list[dict[str, Any]]) -> Any:
    return SimpleNamespace(
        runtime_dir=root / "rt",
        data_dir=root / "data",
        cache_dir=root / "cache",
        runtime=SimpleNamespace(items=items),
    )


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes, fail_after: int | None):
        self.status = status
        self.headers = headers
        self._body = body
        self._position = 0
        self._fail_after = fail_after

    def read(self, size: int) -> bytes:
        if self._fail_after is not None and self._position >= self._fail_after:
            raise ConnectionResetError("connection dropped")
        end = min(self._position + size, len(self._body))
        if self._fail_after is not None:
            end = min(end, self._fail_after)
        chunk = self._body[self._position : end]
        self._position = end
        return chunk

    def close(self) -> None:
        pass


@dataclass
class FakeTransport:
    """Serves blobs by URL. Supports Range, can drop a connection and can hook reads."""

    blobs: dict[str, bytes]
    ranges: bool = True
    fail_after: list[int | None] = field(default_factory=list)
    opens: list[tuple[str, int]] = field(default_factory=list)
    status_override: int | None = None

    def open(self, url: str, *, start: int, timeout: float) -> FakeResponse:
        self.opens.append((url, start))
        if self.status_override is not None:
            detail = {"reason": "http", "status": self.status_override}
            raise AppError("download_failed", detail=detail)
        body = self.blobs[url]
        limit = self.fail_after.pop(0) if self.fail_after else None
        if start and self.ranges:
            headers = {"Content-Range": f"bytes {start}-{len(body) - 1}/{len(body)}"}
            return FakeResponse(206, headers, body[start:], limit)
        return FakeResponse(200, {}, body, limit)

    @property
    def count(self) -> int:
        return len(self.opens)
