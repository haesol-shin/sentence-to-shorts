"""Runtime lock access: which file of an item fits this host, and where it installs."""

from __future__ import annotations

import platform
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from app.ports import AppError, AppSettings

Target = tuple[str, str]
Item = Mapping[str, Any]

_ARCH = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}
_DRIVE = re.compile(r"^[A-Za-z]:")


def host_platform() -> Target:
    """Operating system ("windows" or "linux") and CPU ("x86_64" or "aarch64")."""
    name = "windows" if sys.platform == "win32" else "linux"
    machine = platform.machine().lower()
    return name, _ARCH.get(machine, machine)


EXTERNAL_PREFIXES = ("model-", "package-")


def runtime_owned(item: Item) -> bool:
    """True for items this preparer installs below the runtime root.

    `model-` items live below `APP_MODEL_DIR` and `package-` items are Python wheels
    installed with pip. Both are prepared by `scripts/dev_setup.py`, which skips the
    other items for the same reason, so the preparer never plans or reports them.
    """
    return not str(item["id"]).startswith(EXTERNAL_PREFIXES)


def lock_items(settings: AppSettings) -> list[dict[str, Any]]:
    """The runtime lock items of the settings that the preparer installs, as dictionaries."""
    lock = getattr(settings, "runtime", None)
    items = getattr(lock, "items", None) or []
    dumped = [
        item.model_dump(mode="python") if hasattr(item, "model_dump") else dict(item)
        for item in items
    ]
    return [item for item in dumped if runtime_owned(item)]


_ARCHIVE_SUFFIXES = (".zip", ".whl", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")


def archive_member(entry: Item) -> bool:
    """True when `file` names an installed member inside the downloaded archive.

    A `file` without a slash is the downloaded file itself. A nested `file` is a path
    inside the archive that the application runs. In both cases `bytes` and `sha256`
    describe the downloaded file, never the member.
    """
    path = urlsplit(str(entry["url"])).path.lower()
    return "/" in str(entry["file"]) and path.endswith(_ARCHIVE_SUFFIXES)


WHEEL_BINARY_DIR = "imageio_ffmpeg/binaries"


def wheel_binary(entry: Item) -> str | None:
    """The member of the downloaded wheel that holds the executable `file`, or None.

    The development lock names the FFmpeg wheel as the download and the executable it
    carries as `file`; `scripts/dev_setup.py` extracts that member and installs it flat
    below the item folder. A `file` that is itself a wheel, or a nested path, is not this.
    """
    name = str(entry["file"])
    path = urlsplit(str(entry["url"])).path.lower()
    if path.endswith(".whl") and "/" not in name and not name.lower().endswith(".whl"):
        return f"{WHEEL_BINARY_DIR}/{name}"
    return None


def download_name(entry: Item) -> str:
    """The local name of the downloaded file."""
    if not archive_member(entry) and wheel_binary(entry) is None:
        return str(entry["file"])
    name = unquote(urlsplit(str(entry["url"])).path.rsplit("/", 1)[-1])
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise AppError("download_blocked", detail={"reason": "bad_download_name"})
    return name


def select_file(item: Item, target: Target) -> Mapping[str, Any] | None:
    """The lock file entry for the target, or None when the item has none for it."""
    os_name, arch = target
    for entry in item["files"]:
        if entry["os"] in (os_name, "any") and entry["arch"] in (arch, "wasm32"):
            return entry
    return None


def require_file(item: Item, target: Target) -> Mapping[str, Any]:
    entry = select_file(item, target)
    if entry is None:
        raise AppError("model_missing", detail={"item": str(item["id"]), "reason": "no_file"})
    return entry


def relative_install_path(item: Item) -> PurePosixPath:
    """The install path of an item, checked to stay below the runtime root."""
    raw = str(item["install_path"])
    path = PurePosixPath(raw.replace("\\", "/"))
    bad = (
        not raw
        or path.is_absolute()
        or _DRIVE.match(raw) is not None
        or any(part in ("", ".", "..") for part in path.parts)
    )
    if bad:
        raise AppError("model_missing", detail={"item": str(item["id"]), "reason": "bad_path"})
    return path


def install_dir(root: Path, item: Item) -> Path:
    """Folder below the runtime root that holds the installed files of the item."""
    return root.joinpath(*relative_install_path(item).parts)


def installed_path(settings: AppSettings, item: Item) -> Path:
    return install_dir(settings.runtime_dir, item)


def shares_install_path(item: Item, items: Sequence[Item]) -> bool:
    """True when another lock item installs into the same folder."""
    mine = relative_install_path(item)
    return any(
        other["id"] != item["id"] and relative_install_path(other) == mine for other in items
    )
