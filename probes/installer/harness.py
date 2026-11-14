"""Shared plumbing for the per-user installer probe.

The probe measures whether a per-user installer (Windows) and a tarball with `start.sh`
(Linux) start an empty FastAPI app with the bundled Python, under a synthetic user whose
name and home path contain Korean letters and spaces. A check of the thing under test may
fail without failing the workflow: the failure is written to `result.json` and the probe
still exits 0. Only a harness error (an unreadable manifest, a broken archive, a crash in
the probe) exits nonzero.

This module imports only the standard library so the unit checks run without network and
without an x86_64 runner. The product does not import it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

MODULE_DIR = Path(__file__).resolve().parent
MANIFEST = MODULE_DIR / "runtime.json"
TEMPLATE_DIR = MODULE_DIR / "templates"
REQUIREMENTS = MODULE_DIR / "requirements.txt"
BRAND_FILE = Path("core/config/brand.yaml")
APP_ID_PLACEHOLDER = "app"
MINIMAL_PATH = "/usr/bin:/bin"

CHUNK = 1 << 20
DOWNLOAD_TIMEOUT = 600
LONG_PATH_TARGET = 240
# The path of the interpreter that the launch shortcut and `start.sh` must use is recorded
# in the probe result. These are the names to look up in the bundled runtime folder.
BUNDLED_PYTHON = {
    "linux-x86_64": Path("python/bin/python3.11"),
    "windows-x86_64": Path("python/python.exe"),
}


class ProbeError(RuntimeError):
    """The thing under test failed; the probe records it and keeps going."""


class HarnessError(RuntimeError):
    """The probe cannot continue correctly; the workflow must fail."""


@dataclass(frozen=True)
class Completed:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def tail(self, limit: int = 1200) -> str:
        text = (self.stderr.strip() or self.stdout.strip())
        return text[-limit:]


@dataclass
class Check:
    id: str
    status: str
    detail: str = ""
    measurements: dict = field(default_factory=dict)
    error: str = ""
    seconds: float = 0.0
    harness_error: bool = False

    def as_dict(self) -> dict:
        record = {
            "id": self.id,
            "status": self.status,
            "detail": self.detail,
            "seconds": round(self.seconds, 3),
            "measurements": self.measurements,
        }
        if self.error:
            record["error"] = self.error
        if self.harness_error:
            record["harness_error"] = True
        return record


class Probe:
    """Runs checks, records every outcome, and exposes whether the harness itself broke."""

    def __init__(self) -> None:
        self.checks: list[Check] = []

    def check(self, check_id: str, func: Callable[[], dict | None], *, detail: str = "") -> Check:
        started = time.monotonic()
        harness_error = False
        try:
            measurements = func() or {}
            result = Check(
                id=check_id,
                status="pass",
                detail=detail or "ok",
                measurements=measurements,
            )
        except HarnessError as exc:
            harness_error = True
            result = Check(id=check_id, status="fail", detail=detail, error=str(exc))
        except ProbeError as exc:
            result = Check(id=check_id, status="fail", detail=detail, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a probe bug, recorded and failed
            traceback.print_exc(file=sys.stderr)
            harness_error = True
            result = Check(
                id=check_id,
                status="fail",
                detail=detail,
                error=f"{type(exc).__name__}: {exc}",
            )
        result.harness_error = harness_error
        result.seconds = time.monotonic() - started
        self.checks.append(result)
        evidence = result.detail if result.status == "pass" else result.error
        print(f"[{result.status}] {check_id}: {evidence} ({result.seconds:.2f}s)", flush=True)
        return result

    def skip(self, check_id: str, reason: str, *, detail: str = "") -> Check:
        result = Check(id=check_id, status="skipped", detail=detail or "skipped", error=reason)
        self.checks.append(result)
        print(f"[skipped] {check_id}: {reason}", flush=True)
        return result

    @property
    def harness_failed(self) -> bool:
        return any(check.harness_error for check in self.checks)

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if check.status == "fail"]

    @property
    def passed(self) -> list[Check]:
        return [check for check in self.checks if check.status == "pass"]


def require(condition: object, message: str) -> None:
    if not condition:
        raise ProbeError(message)


# --- manifest and brand -------------------------------------------------------------


def load_manifest(path: Path = MANIFEST) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"cannot read the probe manifest {path}: {exc}") from exc


def parse_brand(text: str) -> dict[str, str]:
    """Parse the flat `key: value` brand file. Same shape as the repository brand check."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def read_brand(root: Path) -> dict[str, str]:
    path = Path(root) / BRAND_FILE
    try:
        brand = parse_brand(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HarnessError(f"cannot read {BRAND_FILE}: {exc}") from exc
    for key in ("display_name_en", "app_id"):
        if not brand.get(key):
            raise HarnessError(f"{BRAND_FILE}: {key} is missing")
    return brand


def install_dir(home: Path, app_id: str, version: str) -> Path:
    """The per-user install location the task file fixes for both platforms."""
    return Path(home) / "Programs" / app_id / version


def synthetic_paths(root: Path, os_name: str, app_id: str, version: str) -> dict:
    """A synthetic account and home that carry Korean letters and a space.

    Unix login names cannot contain a space, so Linux uses a Korean login name and a home
    directory with Korean letters and a space. The difference is written to the result.
    """
    if os_name == "windows":
        login_name = "설치 사용자"
        home_name = "사용자 폴더"
    else:
        login_name = "설치사용자"
        home_name = "홈 폴더"
    home = Path(root) / home_name
    return {
        "login_name": login_name,
        "home": home,
        "install": install_dir(home, app_id, version),
    }


def deep_path(base: Path, target_chars: int) -> Path:
    """A path under `base` whose string has exactly `target_chars` characters when possible."""
    path = Path(base)
    index = 1
    while len(str(path)) < target_chars:
        remaining = target_chars - len(str(path))
        if remaining <= 2:
            path = path / ("p" * max(1, remaining - 1))
            break
        name = f"d{index:04d}"
        if len(name) + 1 > remaining:
            path = path / ("p" * (remaining - 1))
            break
        path = path / name
        index += 1
    return path


# --- files --------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_bytes(root: Path) -> int:
    total = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += (Path(base) / name).lstat().st_size
            except OSError:
                continue
    return total


def download(url: str, target: Path, expected_sha256: str, *, timeout: int = DOWNLOAD_TIMEOUT) -> dict:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "installer-probe/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            with target.open("wb") as handle:
                shutil.copyfileobj(response, handle, CHUNK)
    except (OSError, urllib.error.URLError) as exc:
        raise ProbeError(f"download failed: {exc}") from exc
    found = sha256_file(target)
    if found != expected_sha256:
        raise ProbeError(f"sha256 mismatch: expected {expected_sha256}, found {found}")
    return {"url": url, "bytes": target.stat().st_size, "sha256": found}


def tar_modes(path: Path) -> dict[str, int]:
    modes: dict[str, int] = {}
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                name = member.name
                while name.startswith("./"):
                    name = name[2:]
                if member.isfile() or member.isdir() or member.issym() or member.islnk():
                    modes[name] = member.mode
    except (OSError, tarfile.TarError) as exc:
        raise HarnessError(f"cannot read the tarball {path}: {exc}") from exc
    return modes


def missing_exec_modes(modes: dict[str, int], required: list[str]) -> list[str]:
    missing = []
    for name in required:
        mode = modes.get(name)
        if mode is None or not mode & 0o111:
            missing.append(name)
    return missing


def extract_tar(path: Path, dest: Path) -> None:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(path, "r:gz") as archive:
            try:
                archive.extractall(dest, filter="data")
            except TypeError:  # Python before the extraction filter backport.
                archive.extractall(dest)
    except (OSError, tarfile.TarError) as exc:
        raise HarnessError(f"cannot extract {path}: {exc}") from exc


# --- installer templates ------------------------------------------------------------


def render_template(name: str, values: dict[str, str]) -> str:
    text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"@{key}@", value)
    leftover = sorted(set(re.findall(r"@[A-Z_]+@", text)))
    if leftover:
        raise HarnessError(f"template {name} has unfilled values: {leftover}")
    return text


def render_iss(values: dict[str, str]) -> str:
    return render_template("installer.iss", values)


def render_nsi(values: dict[str, str]) -> str:
    return render_template("installer.nsi", values)


# --- port, health and result files --------------------------------------------------


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def parse_port_file(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"port file is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProbeError("port file is not a JSON object")
    if value.get("error"):
        raise ProbeError(f"launcher failed: {value['error']}")
    if not isinstance(value.get("port"), int):
        raise ProbeError("port file has no integer port")
    return value


def wait_port_file(path: Path, port: int, timeout: float = 60.0, interval: float = 0.1) -> dict:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text.strip():
            last = text
            try:
                value = parse_port_file(text)
            except ProbeError:
                raise
            if value["port"] == port:
                return value
        time.sleep(interval)
    raise ProbeError(f"no port file after {timeout:g}s (last content: {last[:200]!r})")


def fetch_json(url: str, timeout: float = 10.0) -> tuple[int, dict]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return response.status, json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProbeError(f"GET {url} returned {exc.code}") from exc
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ProbeError(f"GET {url} failed: {exc}") from exc


def wait_health(port: int, timeout: float = 120.0, interval: float = 0.2) -> dict:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    last = ""
    while time.monotonic() < deadline:
        try:
            status, payload = fetch_json(url, timeout=5.0)
        except ProbeError as exc:
            last = str(exc)
        else:
            if status == 200 and payload.get("status") == "ok":
                return payload
            last = f"status {status}, body {payload!r}"
        time.sleep(interval)
    raise ProbeError(f"health check did not pass after {timeout:g}s: {last}")


def parse_shortcut(text: str) -> tuple[str, str, str]:
    """Read the TargetPath, Arguments and WorkingDirectory lines printed by PowerShell."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        raise HarnessError(f"cannot read the shortcut fields: {text[-400:]!r}")
    return lines[0], lines[1], lines[2]


def parse_task_status(text: str) -> tuple[str, int | None]:
    """Read the Status and Last Result fields of `schtasks /Query /V /FO LIST`."""
    status = ""
    last_result: int | None = None
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "status":
            status = value
        elif key == "last result" and value.isdigit():
            last_result = int(value)
    return status, last_result


def under(path: str, root: Path) -> bool:
    """True when the resolved path is inside root. Follows symlinks."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


def path_under(path: str, root: Path) -> bool:
    """True when the path as written is inside root, without following symlinks.

    A venv interpreter is a symlink to the base interpreter. The probe records the path the
    launcher executed, so this lexical check is the one that proves the installed entry point.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        return False
    try:
        Path(os.path.normpath(str(candidate))).relative_to(Path(os.path.normpath(str(root))))
    except ValueError:
        return False
    return True


# --- process execution --------------------------------------------------------------


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: float = 600.0,
    input_text: str | None = None,
    timeout_is_probe: bool = False,
) -> Completed:
    try:
        process = subprocess.run(
            command,
            input=input_text,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        if timeout_is_probe:
            # A hung installer or launcher is a failure of the thing under test, not of the
            # probe that started it.
            raise ProbeError(f"the probe target timed out after {timeout:g}s: {command[:3]!r}") from exc
        raise HarnessError(f"command timed out after {timeout:g}s: {command[:3]!r}") from exc
    except OSError as exc:
        raise HarnessError(f"cannot start {command[0]!r}: {exc}") from exc
    return Completed(
        command=command,
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def checked(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: float = 600.0,
    timeout_is_probe: bool = False,
) -> Completed:
    completed = run(command, cwd=cwd, env=env, timeout=timeout, timeout_is_probe=timeout_is_probe)
    if not completed.ok:
        raise ProbeError(f"{command[0]} exited {completed.returncode}: {completed.tail()}")
    return completed


# --- output -------------------------------------------------------------------------


def summary_markdown(payload: dict) -> str:
    """A short job summary; the full evidence lives in result.json."""
    checks = payload["checks"]
    failed = [check for check in checks if check["status"] == "fail"]
    broken = [check for check in checks if check.get("harness_error")]
    measurements = payload.get("measurements") or {}
    lines = [
        f"## Installer probe on {payload['os']} ({payload['mode']})",
        "",
        f"- python: `{payload['python']['version']}` from `{payload['python']['asset']['name']}`",
        f"- installer: `{payload['installer']['tool']}`, {payload['installer'].get('bytes')} bytes",
        f"- install dir: `{payload['paths']['install']}`",
        f"- new user: `{payload['user']['created']}` ({payload['user']['login']})",
        "",
        "| measurement | value |",
        "|---|---|",
    ]
    for key in ("download_bytes", "compressed_bytes", "installed_bytes", "install_seconds", "start_seconds"):
        lines.append(f"| {key} | {measurements.get(key)} |")
    lines += ["", "| check | status | detail |", "|---|---|---|"]
    for check in checks:
        detail = check.get("error") or check.get("detail", "")
        detail = detail.replace("|", "\\|").replace("\n", " ")[:160]
        lines.append(f"| {check['id']} | {check['status']} | {detail} |")
    lines += [""]
    if failed:
        lines.append(f"**{len(failed)} of {len(checks)} checks failed; see result.json.**")
    else:
        lines.append(f"**{len(checks)} of {len(checks)} checks passed or skipped.**")
    if broken:
        lines.append("**A harness error occurred; the workflow fails.**")
    return "\n".join(lines) + "\n"


def write_result(output_dir: Path, payload: dict) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    summary_path = output_dir / "summary.md"
    result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary_path.write_text(summary_markdown(payload), encoding="utf-8")
    return result_path, summary_path
