"""Sandbox adapter: run generated code only inside the Pyodide on Deno runner.

The host never imports or executes generated code. A request is checked, looked
up in the result cache, and otherwise sent to one fresh runner process. Stdout
is untrusted bytes: it must be exactly one JSON line in the protocol schema for
the same request id, and every file passes the parent PNG or WAV validator
before it is returned or cached. Failures map to the sandbox job error codes;
nothing falls back to native execution.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import TypeAdapter, ValidationError

from app.ports import (
    AppError,
    AppSettings,
    Cancelled,
    CancelToken,
    SandboxPort,
    ValidatedOutput,
    canonical_digest,
)
from app.schemas.sandbox_io import (
    SandboxError,
    SandboxErrorCode,
    SandboxKind,
    SandboxLimits,
    SandboxRequest,
    SandboxResponse,
    SandboxResult,
)
from app.tools import process
from app.tools.sandbox.cache import ResultCache
from app.tools.sandbox.runtime import STARTUP_EXITS, DenoLauncher, SandboxRuntime
from app.tools.sandbox.validate_png import PngRejected, check_png
from app.tools.sandbox.validate_wav import WavRejected, check_wav

logger = logging.getLogger(__name__)

RESPONSE: TypeAdapter[SandboxResult | SandboxError] = TypeAdapter(SandboxResponse)
INPUT_KEYS: dict[SandboxKind, frozenset[str]] = {
    SandboxKind.style_parts: frozenset({"spec", "character", "canvas"}),
    SandboxKind.template_layer: frozenset({"scene", "regions", "canvas"}),
    SandboxKind.bgm_loop: frozenset({"params"}),
}
SINGLE_FILE: dict[SandboxKind, tuple[str, str]] = {
    SandboxKind.template_layer: ("layer", "image/png"),
    SandboxKind.bgm_loop: ("loop", "audio/wav"),
}
MIN_CANVAS_SIDE = 16
META_BYTES = 64 * 1024
# The runner reports Deno permission errors and wasm allocation failures inside
# the Python traceback. The text is untrusted; it only picks between failures.
PERMISSION_DENIED = re.compile(
    r"\b(?:NotCapable|PermissionDenied)\b"
    r"|Requires (?:read|write|net|env|run|ffi|sys|import) access"
)
OUT_OF_MEMORY = re.compile(
    r"\bMemoryError\b|out of memory|Cannot enlarge memory|Maximum memory size exceeded"
    r"|Array buffer allocation failed",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SandboxConfig:
    """Limits from the `sandbox` section of `core/config/app.yaml` (CONTRACTS 9.3)."""

    wall_ms: Mapping[str, int]
    memory_bytes: int
    stdin_bytes: int
    stdout_bytes: int
    stderr_bytes: int
    max_files: int
    max_png_side: int
    max_png_bytes: int
    max_wav_ms: int
    max_wav_bytes: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> SandboxConfig:
        wall = dict(values["wall_ms"])
        missing = [kind.value for kind in SandboxKind if kind.value not in wall]
        if missing:
            raise ValueError(f"sandbox.wall_ms has no {missing[0]}")
        fields = {name: int(values[name]) for name in cls.__dataclass_fields__ if name != "wall_ms"}
        return cls(wall_ms={key: int(value) for key, value in wall.items()}, **fields)


class Launcher(Protocol):
    def __call__(
        self, payload: bytes, *, timeout_s: float, cancel: CancelToken
    ) -> process.ProcessResult: ...


class RuntimeCheck(Protocol):
    def digest(self) -> str: ...

    def verify(self) -> None: ...


def _invalid(reason: str) -> AppError:
    return AppError("sandbox_output_invalid", detail={"reason": reason})


class SandboxAdapter(SandboxPort):
    """One runner process per request; no process is reused (CONTRACTS 9.5)."""

    def __init__(
        self,
        *,
        runtime: RuntimeCheck,
        config: SandboxConfig,
        cache: ResultCache,
        launcher: Launcher,
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._cache = cache
        self._launcher = launcher
        self._digest: str | None = None
        self._ready = False
        self._lock = threading.Lock()

    def runtime_digest(self) -> str:
        if self._digest is None:
            self._digest = self._runtime.digest()
        return self._digest

    def run(self, request: SandboxRequest, *, cancel: CancelToken) -> ValidatedOutput:
        cancel.raise_if_set()
        started = time.monotonic()
        limits = self.effective_limits(request)
        asset_digests = self._check_input(request, limits)
        key = self.cache_key(request, limits, asset_digests)
        cached = self._cache.get(key)
        if cached is not None:
            self._log_run(request.kind, started, cache_hit=True)
            return cached
        try:
            self._ensure_ready()
            payload = request.model_copy(update={"limits": limits}).model_dump_json().encode()
            if len(payload) > self._config.stdin_bytes:
                raise ValueError(f"request is {len(payload)} bytes, over the stdin limit")
            result = self._launcher(
                payload,
                timeout_s=self._config.wall_ms[request.kind.value] / 1000,
                cancel=cancel,
            )
            if result.cancelled:
                cancel.raise_if_set()
                raise Cancelled()
            output = self._interpret(request, limits, result)
        except AppError as error:
            self._log_run(request.kind, started, cache_hit=False, error_code=error.code)
            raise
        try:
            self._cache.put(key, output)
        except OSError:
            logger.warning(
                "sandbox_cache_write_failed", extra={"event": "sandbox_cache_write_failed"}
            )
        self._log_run(request.kind, started, cache_hit=False)
        return output

    def effective_limits(self, request: SandboxRequest) -> SandboxLimits:
        """The request limits, never above the configured ones."""
        return SandboxLimits(
            max_files=min(request.limits.max_files, self._config.max_files),
            max_png_side=min(request.limits.max_png_side, self._config.max_png_side),
            max_wav_ms=min(request.limits.max_wav_ms, self._config.max_wav_ms),
        )

    def cache_key(
        self, request: SandboxRequest, limits: SandboxLimits, asset_digests: list[list[str]]
    ) -> str:
        """Code digest, runtime digest, kind, canonical input, seed (CONTRACTS 9.5)."""
        return canonical_digest(
            {
                "artifact": "sandbox_result",
                "protocol": request.protocol,
                "kind": request.kind.value,
                "code_sha256": hashlib.sha256(request.code.encode("utf-8")).hexdigest(),
                "runtime_digest": self.runtime_digest(),
                "input": request.input,
                "assets": sorted(asset_digests),
                "seed": request.seed,
                "limits": limits.model_dump(),
                # File byte limits also decide what is accepted, so a lower limit
                # must not reuse a result that only passed the higher one.
                "file_bytes": {
                    "png": self._config.max_png_bytes,
                    "wav": self._config.max_wav_bytes,
                },
            }
        )

    def _check_input(self, request: SandboxRequest, limits: SandboxLimits) -> list[list[str]]:
        expected = INPUT_KEYS[request.kind]
        if set(request.input) != expected:
            raise ValueError(f"{request.kind.value} input takes exactly {sorted(expected)}")
        if request.kind is not SandboxKind.bgm_loop:
            canvas = request.input["canvas"]
            if not isinstance(canvas, dict) or set(canvas) != {"width", "height"}:
                raise ValueError("canvas takes exactly width and height")
            for side in canvas.values():
                if type(side) is not int or not MIN_CANVAS_SIDE <= side <= limits.max_png_side:
                    raise ValueError("canvas sides must be integers inside the PNG side limit")
        if request.assets and request.kind is not SandboxKind.template_layer:
            raise ValueError("only template_layer takes part assets")
        names = [asset.name for asset in request.assets]
        if len(set(names)) != len(names):
            raise ValueError("asset names must be unique")
        digests = []
        for asset in request.assets:
            try:
                data = base64.b64decode(asset.png_b64, validate=True)
            except binascii.Error as error:
                raise ValueError(f"asset {asset.name} is not base64") from error
            digests.append([asset.name, hashlib.sha256(data).hexdigest()])
        return digests

    def _ensure_ready(self) -> None:
        with self._lock:
            if self._ready:
                return
            self._runtime.verify()
            cap = process.memory_cap_status(self._config.memory_bytes)
            logger.info(
                "sandbox_runner_start",
                extra={
                    "event": "sandbox_runner_start",
                    "memory_cap": "applied" if cap.applied else "unverified",
                    "memory_cap_mechanism": cap.mechanism,
                    "memory_cap_reason": cap.reason,
                    "memory_cap_bytes": cap.limit_bytes,
                },
            )
            self._ready = True

    def _interpret(
        self, request: SandboxRequest, limits: SandboxLimits, result: process.ProcessResult
    ) -> ValidatedOutput:
        if result.timed_out:
            raise AppError("sandbox_timeout", detail={"wall_ms": result.duration_ms})
        if result.memory_limited:
            raise AppError("sandbox_memory", detail={"reason": "memory cap reached"})
        if result.output_limited or result.stdout_truncated:
            raise _invalid("stdout passed its limit")
        if result.returncode != 0:
            if result.returncode in STARTUP_EXITS and not result.stdout:
                raise AppError("sandbox_unavailable", detail={"reason": "runner did not start"})
            raise AppError("sandbox_crashed", detail={"returncode": result.returncode})
        stdout = result.stdout
        if not stdout.endswith(b"\n") or stdout.count(b"\n") != 1:
            raise _invalid("stdout is not exactly one line")
        try:
            response = RESPONSE.validate_json(stdout[:-1])
        except ValidationError as error:
            raise _invalid(f"response does not match the protocol: {error.error_count()} errors")
        if response.request_id != request.request_id:
            raise _invalid("response is for another request")
        if isinstance(response, SandboxError):
            raise self._runner_error(response)
        return self._validated(request.kind, limits, response)

    @staticmethod
    def _runner_error(response: SandboxError) -> AppError:
        detail = {"runner_code": response.code.value, "message": response.message}
        if response.code is SandboxErrorCode.import_denied:
            return AppError("sandbox_denied", detail=detail)
        if response.code is SandboxErrorCode.python_exception:
            if PERMISSION_DENIED.search(response.message):
                return AppError("sandbox_denied", detail=detail)
            if OUT_OF_MEMORY.search(response.message):
                return AppError("sandbox_memory", detail=detail)
            return AppError("sandbox_crashed", detail=detail)
        if response.code in (SandboxErrorCode.bad_return, SandboxErrorCode.too_many_files):
            return AppError("sandbox_output_invalid", detail=detail)
        return AppError("sandbox_crashed", detail=detail)

    def _validated(
        self, kind: SandboxKind, limits: SandboxLimits, response: SandboxResult
    ) -> ValidatedOutput:
        names = [item.name for item in response.files]
        if len(set(names)) != len(names):
            raise _invalid("file names repeat")
        if len(names) > limits.max_files:
            raise _invalid(f"{len(names)} files, over {limits.max_files}")
        single = SINGLE_FILE.get(kind)
        for item in response.files:
            wanted = single or (item.name, "image/png")
            if (item.name, item.media_type) != wanted or (single and len(names) != 1):
                raise _invalid(f"{kind.value} cannot return {item.media_type} {item.name}")
        files: dict[str, bytes] = {}
        measured: dict[str, dict[str, Any]] = {}
        for item in response.files:
            try:
                data = base64.b64decode(item.b64, validate=True)
            except binascii.Error as error:
                raise _invalid(f"{item.name} is not base64") from error
            try:
                if item.media_type == "image/png":
                    png = check_png(
                        data, max_side=limits.max_png_side, max_bytes=self._config.max_png_bytes
                    )
                    files[item.name] = png.data
                    measured[item.name] = {"width": png.width, "height": png.height}
                else:
                    wav = check_wav(
                        data, max_ms=limits.max_wav_ms, max_bytes=self._config.max_wav_bytes
                    )
                    files[item.name] = wav.data
                    measured[item.name] = {
                        "duration_ms": wav.duration_ms,
                        "frames": wav.frames,
                        "sample_peak_dbfs_x10": wav.sample_peak_dbfs_x10,
                        "loudness_lufs_x10": wav.loudness_lufs_x10,
                    }
            except (PngRejected, WavRejected) as error:
                raise _invalid(f"{item.name}: {error}") from error
        program_meta: dict[str, Any] = {}
        if kind is SandboxKind.template_layer:
            program_meta = response.meta
            if len(json.dumps(program_meta, ensure_ascii=True)) > META_BYTES:
                raise _invalid("layer meta is too large")
        return ValidatedOutput(files=files, meta={"program": program_meta, "files": measured})

    def _log_run(
        self,
        kind: SandboxKind,
        started: float,
        *,
        cache_hit: bool,
        error_code: str | None = None,
    ) -> None:
        logger.info(
            "sandbox_run",
            extra={
                "event": "sandbox_run",
                "kind": kind.value,
                "cache_hit": cache_hit,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "error_code": error_code,
            },
        )


class SkeletonSandbox(SandboxPort):
    """Fixture-profile placeholder; every call reports not implemented."""

    def run(self, request: SandboxRequest, *, cancel: CancelToken) -> ValidatedOutput:
        raise NotImplementedError

    def runtime_digest(self) -> str:
        raise NotImplementedError


def _settings_part(settings: AppSettings, *path: str) -> Any:
    value: Any = settings
    for name in path:
        value = getattr(value, name, None)
        if value is None:
            raise TypeError(f"settings have no {'.'.join(path)}")
    return value


def create(settings: AppSettings) -> SandboxAdapter:
    """Build the adapter without touching the runtime; files are checked on first run."""
    config = SandboxConfig.from_mapping(_settings_part(settings, "app", "sandbox").model_dump())
    lock_items = [item.model_dump() for item in _settings_part(settings, "runtime", "items")]
    runtime = SandboxRuntime(Path(settings.runtime_dir), lock_items)
    sandbox_cache = Path(settings.cache_dir) / "sandbox"
    return SandboxAdapter(
        runtime=runtime,
        config=config,
        cache=ResultCache(sandbox_cache / "results"),
        launcher=DenoLauncher(
            runtime,
            cache_dir=sandbox_cache,
            memory_bytes=config.memory_bytes,
            stdout_bytes=config.stdout_bytes,
            stderr_bytes=config.stderr_bytes,
        ),
    )


def create_skeleton(settings: AppSettings) -> SkeletonSandbox:
    return SkeletonSandbox()
