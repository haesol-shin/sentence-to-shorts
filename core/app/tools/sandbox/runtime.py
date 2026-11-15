"""Pinned sandbox runtime: file checks, digest and the Deno command line.

The versions and hashes come from `core/config/runtime.lock.json`, passed in by
the factory. `verify` checks the installed files against that lock before the
first run. `launch` starts one Deno process for one request with the fixed flag
set, an environment of three Deno variables, a fresh empty working folder and a
dedicated Deno cache, and the host memory cap when the host supports one.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.ports import AppError, CancelToken, canonical_digest
from app.tools import process

RUNNER_DIR = Path(__file__).resolve().parent / "runner"
RUNNER_ENTRY = RUNNER_DIR / "runner.js"
RUNNER_SOURCES = (RUNNER_ENTRY, RUNNER_DIR / "bootstrap.js")
RUNTIME_ITEMS = ("deno", "pyodide-core", "pyodide-pillow")
UNAVAILABLE = "sandbox_unavailable"
# Deno flags confirmed by the sandbox probe. Read covers only the runtime folder
# and is revoked by the runner before the request is read.
DENY_FLAGS = (
    "--deny-write",
    "--deny-net",
    "--deny-env",
    "--deny-run",
    "--deny-ffi",
    "--deny-sys",
    "--deny-import",
)
WINDOWS_BOOT_ENV = ("SYSTEMROOT", "WINDIR", "PATHEXT")
# Exit statuses the runner uses before it has read a request.
STARTUP_EXITS = frozenset({3, 4, 5})


def host_platform() -> tuple[str, str]:
    os_name = "windows" if sys.platform == "win32" else "linux"
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}
    return os_name, arch.get(machine, machine)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def runner_digest() -> str:
    """Digest of the runner sources with line endings normalized across checkouts."""
    hasher = hashlib.sha256()
    for path in RUNNER_SOURCES:
        hasher.update(path.name.encode("utf-8") + b"\0")
        hasher.update(path.read_bytes().replace(b"\r\n", b"\n"))
        hasher.update(b"\0")
    return hasher.hexdigest()


class SandboxRuntime:
    """Installed Deno and Pyodide files under the runtime root."""

    def __init__(self, root: Path, lock_items: Sequence[Mapping[str, Any]]) -> None:
        self.root = root.resolve()
        items = {str(item["id"]): item for item in lock_items}
        missing = [name for name in RUNTIME_ITEMS if name not in items]
        if missing:
            raise ValueError(f"runtime lock has no {missing[0]} entry")
        self._items = items
        self._os, self._arch = host_platform()

    def _file(self, item_id: str) -> Mapping[str, Any]:
        for entry in self._items[item_id]["files"]:
            if entry["os"] in (self._os, "any") and entry["arch"] in (self._arch, "wasm32"):
                return entry
        raise AppError(UNAVAILABLE, detail={"reason": f"no {item_id} file for this platform"})

    @property
    def deno(self) -> Path:
        name = "deno.exe" if self._os == "windows" else "deno"
        return self.root / str(self._items["deno"]["install_path"]) / name

    @property
    def pyodide_dir(self) -> Path:
        return self.root / str(self._items["pyodide-core"]["install_path"])

    def digest(self) -> str:
        """Digest of the pinned runtime and runner; the same on every host OS."""
        return canonical_digest(
            {
                "deno": self._items["deno"]["version"],
                "pyodide-core": self._items["pyodide-core"]["files"][0]["sha256"],
                "pyodide-pillow": self._items["pyodide-pillow"]["files"][0]["sha256"],
                "runner": runner_digest(),
            }
        )

    def verify(self) -> None:
        """Check the install journal and the files against the lock; raise when unsafe."""
        journal_path = self.root / "installed.json"
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise AppError(UNAVAILABLE, detail={"reason": "runtime is not installed"}) from error
        for item_id in RUNTIME_ITEMS:
            entry = self._file(item_id)
            installed = journal.get(item_id) if isinstance(journal, dict) else None
            if not isinstance(installed, dict) or installed.get("sha256") != entry["sha256"]:
                raise AppError(
                    UNAVAILABLE, detail={"reason": f"{item_id} does not match the runtime lock"}
                )
        wheel = self.root / str(self._items["pyodide-pillow"]["install_path"])
        wheel = wheel / str(self._file("pyodide-pillow")["file"])
        required = (
            self.deno,
            self.pyodide_dir / "pyodide.mjs",
            self.pyodide_dir / "pyodide-lock.json",
        )
        for path in (*required, wheel):
            if not path.is_file():
                raise AppError(UNAVAILABLE, detail={"reason": f"missing runtime file {path.name}"})
        if _sha256(wheel) != self._file("pyodide-pillow")["sha256"]:
            raise AppError(UNAVAILABLE, detail={"reason": "Pillow wheel differs from the lock"})

    def argv(self) -> list[str]:
        return [
            str(self.deno),
            "run",
            "--quiet",
            "--no-prompt",
            "--no-config",
            "--cached-only",
            f"--allow-read={self.root}",
            *DENY_FLAGS,
            str(RUNNER_ENTRY),
            str(self.root),
        ]


def child_env(deno_dir: Path, workdir: Path) -> dict[str, str]:
    """The whole child environment; nothing is inherited except Windows boot values."""
    env = {"DENO_DIR": str(deno_dir), "DENO_NO_UPDATE_CHECK": "1", "NO_COLOR": "1"}
    if sys.platform == "win32":
        for name in WINDOWS_BOOT_ENV:
            value = os.environ.get(name)
            if value:
                env[name] = value
        env["TEMP"] = str(workdir)
        env["TMP"] = str(workdir)
    return env


class DenoLauncher:
    """Start one runner process for one request and supervise it."""

    def __init__(
        self,
        runtime: SandboxRuntime,
        *,
        cache_dir: Path,
        memory_bytes: int,
        stdout_bytes: int,
        stderr_bytes: int,
    ) -> None:
        self._runtime = runtime
        self._deno_dir = cache_dir / "deno"
        self._work_root = cache_dir / "work"
        self._memory_bytes = memory_bytes
        self._stdout_bytes = stdout_bytes
        self._stderr_bytes = stderr_bytes

    def __call__(
        self, payload: bytes, *, timeout_s: float, cancel: CancelToken
    ) -> process.ProcessResult:
        self._deno_dir.mkdir(parents=True, exist_ok=True)
        self._work_root.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="run-", dir=self._work_root))
        try:
            return process.run(
                self._runtime.argv(),
                cwd=workdir,
                env=child_env(self._deno_dir, workdir),
                timeout_s=timeout_s,
                max_stdout_bytes=self._stdout_bytes,
                max_stderr_bytes=self._stderr_bytes,
                cancel=cancel,
                stdin_data=payload,
                kill_on_stdout_limit=True,
                memory_limit_bytes=self._memory_bytes,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
