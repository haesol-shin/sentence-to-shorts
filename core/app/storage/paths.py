"""Storage roots and the short on-disk layout under them.

Roots come from APP_DATA_DIR, APP_CACHE_DIR, APP_MODEL_DIR and APP_RUNTIME_DIR,
falling back to the per-OS defaults. Every path below a root is built from app ids
only, never from user file names, and stays within 80 characters after the root.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.ports import AppSettings
from app.schemas.common import DIGEST_PATTERN, TYPEID_PATTERN

ENV_DATA_DIR = "APP_DATA_DIR"
ENV_CACHE_DIR = "APP_CACHE_DIR"
ENV_MODEL_DIR = "APP_MODEL_DIR"
ENV_RUNTIME_DIR = "APP_RUNTIME_DIR"

CHUNK = 1 << 20

_ID = re.compile(TYPEID_PATTERN)
_DIGEST = re.compile(DIGEST_PATTERN)
_EXTENSION = re.compile(r"^[a-z0-9]{1,4}$")


@dataclass(frozen=True)
class Roots:
    data: Path
    cache: Path
    model: Path
    runtime: Path


def _env_dir(env: Mapping[str, str], name: str) -> Path | None:
    value = env.get(name)
    return Path(value).expanduser() if value else None


def _xdg(env: Mapping[str, str], name: str, fallback: Path) -> Path:
    """XDG base directory; an unset, empty or relative value is ignored."""
    value = env.get(name)
    if value and Path(value).is_absolute():
        return Path(value)
    return fallback


def default_roots(
    app_id: str,
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
    install_dir: Path | None = None,
) -> Roots:
    """Per-OS roots without environment overrides."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform == "win32":
        local = env.get("LOCALAPPDATA")
        base = (Path(local) if local else home / "AppData" / "Local") / app_id
        data, cache = base / "data", base / "cache"
    else:
        data = _xdg(env, "XDG_DATA_HOME", home / ".local" / "share") / app_id
        cache = _xdg(env, "XDG_CACHE_HOME", home / ".cache") / app_id
    runtime = (install_dir if install_dir is not None else data) / "rt"
    return Roots(data=data, cache=cache, model=data / "models", runtime=runtime)


def resolve_roots(
    app_id: str,
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
    install_dir: Path | None = None,
) -> Roots:
    """Roots with APP_* overrides applied. MODEL_DIR follows an overridden DATA_DIR."""
    env = os.environ if env is None else env
    defaults = default_roots(
        app_id, env=env, platform=platform, home=home, install_dir=install_dir
    )
    data = _env_dir(env, ENV_DATA_DIR) or defaults.data
    return Roots(
        data=data,
        cache=_env_dir(env, ENV_CACHE_DIR) or defaults.cache,
        model=_env_dir(env, ENV_MODEL_DIR) or data / "models",
        runtime=_env_dir(env, ENV_RUNTIME_DIR) or defaults.runtime,
    )


def check_id(value: str) -> str:
    """Reject anything that is not an app TypeID before it becomes a path segment."""
    if not _ID.fullmatch(value):
        raise ValueError(f"invalid id: {value!r}")
    return value


@dataclass(frozen=True)
class Layout:
    """DATA_DIR and CACHE_DIR placement of the files storage owns."""

    data: Path
    cache: Path

    @classmethod
    def from_settings(cls, settings: AppSettings) -> Layout:
        return cls(data=settings.data_dir, cache=settings.cache_dir)

    @property
    def state_db(self) -> Path:
        return self.data / "state.db"

    def project_dir(self, project_id: str) -> Path:
        return self.data / "p" / check_id(project_id)

    def project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def revision_file(self, project_id: str, video_id: str, revision: int) -> Path:
        if revision < 1:
            raise ValueError(f"invalid revision: {revision}")
        return self.project_dir(project_id) / "v" / check_id(video_id) / "r" / f"{revision}.json"

    def output_dir(self, video_id: str) -> Path:
        return self.data / "o" / check_id(video_id)

    def output_file(self, video_id: str, artifact_id: str, extension: str) -> Path:
        return self.output_dir(video_id) / _file_name(artifact_id, extension)

    def job_dir(self, job_id: str) -> Path:
        return self.cache / "j" / check_id(job_id)

    @staticmethod
    def cache_artifact(digest: str, artifact_id: str, extension: str) -> str:
        """Path of an intermediate artifact relative to CACHE_DIR."""
        if not _DIGEST.fullmatch(digest):
            raise ValueError("invalid digest")
        return f"a/{digest[:2]}/{_file_name(artifact_id, extension)}"


def _file_name(artifact_id: str, extension: str) -> str:
    if not _EXTENSION.fullmatch(extension):
        raise ValueError(f"invalid extension: {extension!r}")
    return f"{check_id(artifact_id)}.{extension}"


def fsync_dir(directory: Path) -> None:
    """Persist a rename. Windows has no directory handle to flush."""
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _staging(target: Path) -> Path:
    return target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")


def write_atomic(target: Path, data: bytes) -> None:
    """Write to a temporary name, fsync, close the handle, then rename over target."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = _staging(target)
    try:
        with staging.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, target)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    fsync_dir(target.parent)


def file_digest(path: Path) -> tuple[str, int]:
    """SHA-256 hex and size, read in chunks."""
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            sha.update(chunk)
            size += len(chunk)
    return sha.hexdigest(), size


def copy_atomic(source: Path, target: Path) -> tuple[str, int]:
    """Copy through a temporary name and return the digest and size of the copy."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = _staging(target)
    sha = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as reader, staging.open("xb") as writer:
            for chunk in iter(lambda: reader.read(CHUNK), b""):
                sha.update(chunk)
                size += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(staging, target)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    fsync_dir(target.parent)
    return sha.hexdigest(), size


__all__ = [
    "ENV_CACHE_DIR",
    "ENV_DATA_DIR",
    "ENV_MODEL_DIR",
    "ENV_RUNTIME_DIR",
    "Layout",
    "Roots",
    "check_id",
    "copy_atomic",
    "default_roots",
    "file_digest",
    "fsync_dir",
    "resolve_roots",
    "write_atomic",
]
