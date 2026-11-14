"""Typed settings from core/config files and APP_* environment variables.

Only the bootstrap imports this module. Importing it must not download, create
directories, or connect to anything.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

CORE = Path(__file__).resolve().parent.parent
CONFIG_DIR = CORE / "config"

Profile = Literal["fixture", "dev", "release"]
Deployment = Literal["local", "hosted"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrandConfig(_Model):
    display_name_ko: str
    display_name_en: str
    repository: str
    app_id: str


class Providers(_Model):
    adapters: dict[str, str]
    fixture_adapters: dict[str, str] = {}


class Limits(_Model):
    list_page_max: Annotated[int, Field(ge=1, le=200)]
    idempotency_key_ttl_hours: Annotated[int, Field(ge=1, le=168)]


class Jobs(_Model):
    deadlines_s: dict[str, int | None]
    max_attempts: dict[str, Annotated[int, Field(ge=1, le=5)]]


class SandboxWall(_Model):
    style_parts: int
    template_layer: int
    bgm_loop: int


class Sandbox(_Model):
    wall_ms: SandboxWall
    memory_bytes: int
    stdin_bytes: int
    stdout_bytes: int
    stderr_bytes: int
    max_files: int
    max_png_side: int
    max_png_bytes: int
    max_wav_ms: int
    max_wav_bytes: int


class Uploads(_Model):
    reference_max_bytes: int
    reference_max_ms: int
    bgm_max_bytes: int
    bgm_max_ms: int
    material_max_chars: int


class AppSection(_Model):
    profile: Profile
    deployment: Deployment
    bind_host: str
    port: Annotated[int, Field(ge=1, le=65535)]
    log_level: str


class AppFile(_Model):
    app: AppSection
    providers: Providers
    limits: Limits
    jobs: Jobs
    sandbox: Sandbox
    uploads: Uploads


class Route(_Model):
    model: str
    effort: Literal["low", "medium", "high"]
    timeout_s: Annotated[int, Field(ge=1)]
    retries: Annotated[int, Field(ge=0, le=5)]


class ModelsFile(_Model):
    models: dict[str, dict[str, str]]
    routes: dict[str, Route]


class RuntimeFileEntry(_Model):
    os: Literal["windows", "linux", "any"]
    arch: Literal["x86_64", "aarch64", "wasm32"]
    file: str
    url: str
    bytes: Annotated[int, Field(ge=1)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RuntimeItem(_Model):
    id: str
    version: str
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    install_path: str
    license: dict[str, str]
    files: list[RuntimeFileEntry]


class RuntimeFile(_Model):
    schema_version: Literal[1]
    items: list[RuntimeItem]


class Settings(BaseModel):
    """Concrete app settings. Fields match the surface in app.ports.AppSettings."""

    model_config = ConfigDict(extra="forbid")

    profile: Profile
    deployment: Deployment
    app_version: str
    port: Annotated[int, Field(ge=1, le=65535)]
    lan: bool
    bind_host: str
    log_level: str
    data_dir: Path
    cache_dir: Path
    model_dir: Path
    runtime_dir: Path
    config_dir: Path
    brand: BrandConfig
    app: AppFile
    models: ModelsFile
    runtime: RuntimeFile

    @property
    def providers(self) -> Providers:
        return self.app.providers

    @field_validator("data_dir", "cache_dir", "model_dir", "runtime_dir")
    @classmethod
    def _expand_home(cls, value: Path) -> Path:
        return value.expanduser()

    def __init__(self, **overrides: object) -> None:
        values = _read_settings()
        values.update(overrides)
        super().__init__(**values)


def _default_data_dir(app_id: str) -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / app_id / "data"
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / app_id / "data"


def _default_cache_dir(app_id: str) -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / app_id / "cache"
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / app_id / "cache"


def _read_app_version() -> str:
    with (CORE / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str):
        raise RuntimeError("core/pyproject.toml has no project.version")
    return version


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} must contain a mapping")
    return loaded


def _env_profile() -> Profile:
    value = os.environ.get("APP_PROFILE", "")
    if value in ("fixture", "dev", "release"):
        return value  # type: ignore[return-value]
    raise RuntimeError("APP_PROFILE must be fixture, dev or release")


def _env_deployment() -> Deployment:
    value = os.environ.get("APP_DEPLOYMENT", "")
    if value in ("local", "hosted"):
        return value  # type: ignore[return-value]
    raise RuntimeError("APP_DEPLOYMENT must be local or hosted")


def _read_settings() -> dict[str, object]:
    brand = BrandConfig.model_validate(_load_yaml(CONFIG_DIR / "brand.yaml"))
    app_file = AppFile.model_validate(_load_yaml(CONFIG_DIR / "app.yaml"))
    models = ModelsFile.model_validate(_load_yaml(CONFIG_DIR / "models.yaml"))
    runtime = RuntimeFile.model_validate_json(
        (CONFIG_DIR / "runtime.lock.json").read_text(encoding="utf-8")
    )

    profile = _env_profile() if "APP_PROFILE" in os.environ else app_file.app.profile
    deployment = (
        _env_deployment() if "APP_DEPLOYMENT" in os.environ else app_file.app.deployment
    )
    lan = os.environ.get("APP_LAN") == "1"
    data_dir = Path(os.environ.get("APP_DATA_DIR") or _default_data_dir(brand.app_id))
    cache_dir = Path(os.environ.get("APP_CACHE_DIR") or _default_cache_dir(brand.app_id))
    model_dir = Path(os.environ.get("APP_MODEL_DIR") or data_dir / "models")
    runtime_dir = Path(os.environ.get("APP_RUNTIME_DIR") or data_dir / "rt")
    port = int(os.environ.get("APP_PORT") or app_file.app.port)
    log_level = os.environ.get("APP_LOG_LEVEL") or app_file.app.log_level

    return {
        "profile": profile,
        "deployment": deployment,
        "app_version": _read_app_version(),
        "port": port,
        "lan": lan,
        "bind_host": app_file.app.bind_host if lan else "127.0.0.1",
        "log_level": log_level,
        "data_dir": data_dir,
        "cache_dir": cache_dir,
        "model_dir": model_dir,
        "runtime_dir": runtime_dir,
        "config_dir": CONFIG_DIR,
        "brand": brand,
        "app": app_file,
        "models": models,
        "runtime": runtime,
    }
