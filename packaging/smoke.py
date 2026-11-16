#!/usr/bin/env python3
"""Install a built distribution for a new user and start it without any system Python.

    python packaging/smoke.py --artifact dist/<tarball or setup exe> --os linux \\
        --profile release --output smoke-result.json

The user is synthetic: the home and install folders have Korean letters and spaces, and
PATH holds one empty folder, so a Python or ffmpeg on the machine cannot be used by
accident. The checks that gate the exit code are the install, the profile default of
the distribution, the prepared runtime items with a bundled ffmpeg that runs, and the
distribution started exactly as shipped: `/api/v1/health` 200, the built page, the bundled
interpreter and a clean stop. A fixture-profile start of the same files is run afterwards
as a diagnostic only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HOME_NAME = "사용자 홈 테스트"
INSTALL_NAME = "설치 폴더 테스트"
START_TIMEOUT_S = 120.0


class Result:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: str = "", *, gating: bool = True) -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail, "gating": gating})
        mark = "ok  " if ok else ("FAIL" if gating else "note")
        print(f"{mark} {name}{' ' + detail if detail else ''}", flush=True)
        return bool(ok)

    @property
    def failed(self) -> bool:
        return any(not c["ok"] and c["gating"] for c in self.checks)


def user_environment(work: Path, home: Path, bare_path: Path) -> dict[str, str]:
    local = home / "AppData" / "Local"
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(local),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "TEMP": str(work / "tmp"),
        "TMP": str(work / "tmp"),
        "PATH": str(bare_path),
    }
    if sys.platform == "win32":
        for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
            if name in os.environ:
                env[name] = os.environ[name]
    return env


def install(artifact: Path, os_name: str, parent: Path, work: Path) -> Path:
    parent.mkdir(parents=True)
    if os_name == "linux":
        subprocess.run(["tar", "-xzf", str(artifact), "-C", str(parent)], check=True)
        folders = [path for path in parent.iterdir() if path.is_dir()]
        if len(folders) != 1:
            raise RuntimeError("the tarball must hold one top folder")
        return folders[0]
    target = parent / "app"
    subprocess.run(
        [
            str(artifact), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
            f"/DIR={target}", f"/LOG={work / 'setup.log'}",
        ],
        check=True,
    )
    return target


def bundled_python(root: Path, os_name: str) -> Path:
    return root / ("python/python.exe" if os_name == "windows" else "python/bin/python3.11")


def launch_command(root: Path, os_name: str) -> list[str]:
    if os_name == "linux":
        return [str(root / "start.sh"), "--no-browser"]
    return [str(bundled_python(root, os_name)), str(root / "launch.py"), "--no-browser"]


def get(url: str) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def wait_record(path: Path, process: subprocess.Popen[bytes], timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        time.sleep(0.2)
    return None


def wait_exit(process: subprocess.Popen[bytes], timeout: float) -> int | None:
    try:
        return process.wait(timeout)
    except subprocess.TimeoutExpired:
        return None


def stop(process: subprocess.Popen[bytes]) -> int | None:
    if process.poll() is None:
        process.terminate()
    try:
        return process.wait(30)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()


def run_launcher(
    root: Path, os_name: str, env: dict[str, str], data_dir: Path, log: Path
) -> tuple[dict | None, subprocess.Popen[bytes], Any]:
    output = log.open("wb")
    process = subprocess.Popen(
        launch_command(root, os_name), env=env, stdout=output, stderr=subprocess.STDOUT,
        cwd=root.parent,
    )
    return wait_record(data_dir / "launcher.json", process, START_TIMEOUT_S), process, output


def check_runtime_ready(result: Result, python: Path, root: Path, env: dict[str, str]) -> None:
    code = (
        "import json, sys; sys.path[:0] = [sys.argv[1] + '/core', sys.argv[1] + '/site-packages'];"
        "from app.runtime import status; from app.settings import Settings;"
        "from app.tools.media.adapter import runtime_executable;"
        "s = Settings(); exe = runtime_executable(s);"
        "print(json.dumps({'states': {i.id: i.state.value for i in status(s)},"
        " 'ffmpeg': str(exe) if exe else None}))"
    )
    done = subprocess.run(
        [str(python), "-c", code, str(root)], env={**env, "APP_RUNTIME_DIR": str(root / "rt")},
        capture_output=True, text=True, check=False,
    )
    report = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else {}
    states = report.get("states", {})
    ready = bool(states) and set(states.values()) == {"ready"} and "ffmpeg" in states
    result.check(
        "runtime items, including ffmpeg, are prepared in the distribution",
        ready,
        json.dumps(states) if states else done.stderr.strip()[-300:],
    )
    exe = report.get("ffmpeg")
    version = ""
    if exe and Path(exe).is_file() and Path(exe).resolve().is_relative_to(root.resolve()):
        probe = subprocess.run(
            [exe, "-version"], env=env, capture_output=True, text=True, check=False, timeout=60
        )
        version = probe.stdout.splitlines()[0] if probe.returncode == 0 and probe.stdout else ""
    result.check(
        "the media adapter resolves the bundled ffmpeg, which runs without PATH",
        bool(version),
        version[:60],
    )
    result.check(
        "the GPL text and the FFmpeg notice ship with the distribution",
        (root / "licenses" / "FFmpeg-GPL-3.0.txt").is_file()
        and "FFmpeg" in (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"),
    )


def exercise(
    result: Result, label: str, root: Path, args: argparse.Namespace, env: dict[str, str],
    data_dir: Path, work: Path, *, gating: bool,
) -> None:
    """Start the launcher with `env`, check health and the page, stop it with --stop."""
    record, process, output = run_launcher(root, args.os, env, data_dir, work / f"{label}.log")
    try:
        result.check(f"[{label}] the launcher published its record", record is not None,
                     gating=gating)
        if record is not None:
            port = record["port"]
            status, _body = get(f"http://127.0.0.1:{port}/api/v1/health")
            result.check(f"[{label}] GET /api/v1/health answers 200", status == 200, str(status),
                         gating=gating)
            status, body = get(f"http://127.0.0.1:{port}/")
            result.check(f"[{label}] the built web page is served", status == 200 and b"<" in body,
                         gating=gating)
            bundled = Path(record["python"]).resolve().is_relative_to(root.resolve())
            result.check(f"[{label}] the server runs the bundled interpreter", bundled,
                         record["python"][-40:], gating=gating)
    finally:
        stopper = subprocess.run(
            launch_command(root, args.os)[:-1] + ["--stop"],
            env=env, capture_output=True, check=False,
        )
        code = wait_exit(process, 30)
        if code is None:
            code = stop(process)
        output.close()
    result.check(f"[{label}] the stop command reaches the running launcher",
                 stopper.returncode == 0 or record is None, gating=gating)
    if args.os == "linux" and record is not None:
        result.check(f"[{label}] the launcher exits cleanly when stopped", code == 0, str(code),
                     gating=gating)
    if record is None:
        tail = (work / f"{label}.log").read_bytes()[-400:].decode("utf-8", "replace")
        result.check(f"[{label}] why it did not start", False, tail.strip()[-300:], gating=False)


def smoke(args: argparse.Namespace) -> Result:
    result = Result()
    work = Path(tempfile.mkdtemp(prefix="smoke-"))
    try:
        home = work / HOME_NAME
        bare = work / "empty path"
        for folder in (home, bare, work / "tmp"):
            folder.mkdir(parents=True)
        env = user_environment(work, home, bare)
        root = install(args.artifact.resolve(), args.os, home / INSTALL_NAME, work)
        python = bundled_python(root, args.os)
        result.check("installed into a Korean path with spaces", python.is_file(), str(python.name))
        result.check(
            "no python or ffmpeg is reachable through PATH",
            all(shutil.which(name, path=str(bare)) is None
                for name in ("python", "python3", "ffmpeg")),
        )
        printed = subprocess.run(
            launch_command(root, args.os)[:-1] + ["--print-config"], env=env,
            capture_output=True, text=True, check=False,
        )
        config = json.loads(printed.stdout) if printed.returncode == 0 else {}
        result.check(
            "the distribution file sets the profile default",
            config.get("profile") == args.profile, str(config.get("profile")),
        )
        check_runtime_ready(result, python, root, env)
        data_dir = Path(config.get("data_dir", home / "data"))
        # The gate: the distribution exactly as shipped, with no profile override.
        exercise(result, args.profile, root, args, env, data_dir, work, gating=True)
        # Auxiliary: the same files with the fixture profile, to tell a packaging fault
        # from an application that cannot start yet. It never makes the run pass.
        exercise(result, "fixture", root, args, {**env, "APP_PROFILE": "fixture"}, data_dir,
                 work, gating=False)
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--os", choices=("linux", "windows"), required=True)
    parser.add_argument("--profile", choices=("release", "dev"), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    result = smoke(args)
    if args.output is not None:
        args.output.write_text(
            json.dumps({"checks": result.checks}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
