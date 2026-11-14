#!/usr/bin/env python3
"""Build the per-user installer and the Linux tarball, install them, and start the app.

Usage on a runner:
    python probes/installer/run_probe.py --output probes/installer/out

`--dry-run` builds and starts the Linux bundle with a local Python. It is a smoke check
for this host, not a measurement: the result records `mode: dry_run` and the RESULT table
is left empty.

A failed check of the thing under test is written to result.json and the process exits 0.
A harness error sets `harness_error`, which fails the workflow; `--strict` exits 2 for it
in a local run.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    BUNDLED_PYTHON,
    LONG_PATH_BEYOND,
    LONG_PATH_TARGET,
    MINIMAL_PATH,
    REQUIREMENTS,
    HarnessError,
    Probe,
    ProbeError,
    checked,
    deep_path,
    download,
    extract_tar,
    install_dir,
    load_manifest,
    missing_exec_modes,
    path_under,
    parse_port_file,
    parse_shortcut,
    parse_task_status,
    read_brand,
    render_iss,
    render_nsi,
    require,
    run,
    sha256_file,
    summary_markdown,
    synthetic_paths,
    tar_modes,
    tree_bytes,
    under,
    wait_health,
    write_result,
)

OS_LABELS = {"linux": "linux-x86_64", "windows": "windows-x86_64"}
TIMEOUTS = {"install": 900.0, "start": 180.0, "stop": 30.0, "command": 600.0}


class Blocked(RuntimeError):
    """A prerequisite check failed; this check and the later ones are skipped."""


class Session:
    def __init__(self, args: argparse.Namespace, manifest: dict, brand: dict, os_name: str) -> None:
        self.args = args
        self.manifest = manifest
        self.brand = brand
        self.os_name = os_name
        self.label = OS_LABELS[os_name]
        self.app_id = brand["app_id"]
        self.display_name = brand["display_name_en"]
        self.version = manifest["app_version"]
        self.work = Path(args.work_dir).resolve()
        self.root = self.work / "installer probe"
        self.bundle = self.root / "bundle"
        self.dist = self.root / "dist"
        self.paths = synthetic_paths(self.root, os_name, self.app_id, self.version)
        self.asset_file: Path | None = None
        self.python_exe: Path | None = None
        self.env_python: Path | None = None
        self.python_version = manifest["python"]["version"]
        self.artifact: dict = {}
        self.user: dict = {}
        self.password = ""
        self.install: Path = self.paths["install"]
        self.process: subprocess.Popen | None = None
        self.task = ""
        self.record: dict = {}
        self.stopped = False
        self.measurements: dict = {key: None for key in manifest.get("measurements", [])}
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def make_dirs(self) -> None:
        for path in (self.root, self.bundle, self.dist):
            path.mkdir(parents=True, exist_ok=True)
            if self.os_name != "windows":
                path.chmod(0o755)


def stage(probe: Probe, check_id: str, func, *, detail: str = "") -> dict:
    result = probe.check(check_id, func, detail=detail)
    if result.status != "pass":
        raise Blocked(f"{check_id} failed")
    return result.measurements


def ready(session: Session, *attributes: str) -> None:
    missing = [name for name in attributes if not getattr(session, name)]
    if missing:
        raise Blocked(f"missing prerequisite: {', '.join(missing)}")


# --- runtime ------------------------------------------------------------------------


def download_runtime(session: Session, probe: Probe) -> None:
    if session.args.dry_run:
        probe.skip("runtime.download", "dry run uses a local interpreter", detail="no download")
        return
    asset = session.manifest["python"]["assets"][session.label]
    session.asset_file = session.root / asset["name"]

    def action() -> dict:
        result = download(asset["url"], session.asset_file, asset["sha256"])
        session.measurements["download_bytes"] = result["bytes"]
        return {"asset": asset["name"], "url": asset["url"], "bytes": result["bytes"], "sha256": result["sha256"]}

    stage(probe, "runtime.download", action, detail="pinned install_only archive matches its SHA-256")


def extract_runtime(session: Session, probe: Probe) -> None:
    if session.args.dry_run:
        probe.skip("runtime.extract", "dry run uses a local interpreter", detail="no bundled runtime")
        return
    ready(session, "asset_file")

    def action() -> dict:
        extract_tar(session.asset_file, session.bundle)
        relative = BUNDLED_PYTHON[session.label]
        session.python_exe = session.bundle / relative
        require(session.python_exe.is_file(), f"bundled interpreter is missing: {relative}")
        completed = checked(
            [str(session.python_exe), "-c", "import platform, sys; print(platform.python_version()); print(sys.executable)"]
        )
        lines = completed.stdout.strip().splitlines()
        require(lines and lines[0].startswith(session.manifest["python"]["version"]), f"unexpected interpreter version: {completed.stdout.strip()!r}")
        require(Path(lines[-1]).is_absolute(), "the interpreter did not report an absolute path")
        require(under(lines[-1], session.bundle), f"interpreter is outside the bundle: {lines[-1]}")
        return {"executable": lines[-1], "version": lines[0], "bytes": tree_bytes(session.bundle / "python")}

    stage(probe, "runtime.extract", action, detail="extracted bundled interpreter runs")


# --- bundle -------------------------------------------------------------------------


def create_venv(session: Session, probe: Probe) -> None:
    if session.args.dry_run:
        python = Path(session.args.python or sys.executable).resolve()
    else:
        ready(session, "python_exe")
        python = session.python_exe
    assert python is not None

    def action() -> dict:
        checked([str(python), "-m", "venv", str(session.bundle / "env")], timeout=TIMEOUTS["command"])
        env_python = session.bundle / "env" / ("Scripts/python.exe" if session.os_name == "windows" else "bin/python")
        require(env_python.is_file(), f"venv interpreter is missing: {env_python}")
        session.env_python = env_python
        version = checked([str(env_python), "-c", "import platform; print(platform.python_version())"]).stdout.strip()
        session.python_version = version
        return {"executable": str(env_python), "version": version, "base": str(python)}

    stage(probe, "env.venv", action, detail="environment made from the bundled interpreter")


def sync_requirements(session: Session, probe: Probe) -> None:
    ready(session, "env_python")

    def action() -> dict:
        uv = shutil.which("uv")
        require(uv is not None, "uv is not on PATH")
        checked(
            [uv, "pip", "sync", "--require-hashes", "--python", str(session.env_python), str(REQUIREMENTS)],
            timeout=TIMEOUTS["command"],
        )
        installed = checked(
            [
                str(session.env_python),
                "-c",
                "import json, platform, fastapi, uvicorn; print(json.dumps({'fastapi': fastapi.__version__, 'uvicorn': uvicorn.__version__, 'python': platform.python_version()}))",
            ]
        )
        return {
            "requirements_sha256": sha256_file(REQUIREMENTS),
            "uv": checked([uv, "--version"]).stdout.strip(),
            **json.loads(installed.stdout),
        }

    stage(probe, "env.requirements", action, detail="hash-pinned sync with uv")


def copy_app(session: Session, probe: Probe) -> None:
    def action() -> dict:
        target = session.bundle / "app"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(Path(__file__).with_name("app"), target)
        shutil.copy2(Path(__file__).with_name("launcher.py"), session.bundle / "launcher.py")
        start = session.bundle / "start.sh"
        shutil.copy2(Path(__file__).with_name("start.sh"), start)
        start.chmod(0o755)
        files = sorted(str(path.relative_to(session.bundle)) for path in session.bundle.rglob("*") if path.is_file())
        require("launcher.py" in files and "app/health_app.py" in files, "bundle is missing launcher or app")
        return {"files": len(files), "has_launcher": True}

    stage(probe, "bundle.app", action, detail="empty app, launcher and start.sh copied into the bundle")


# --- packaging ----------------------------------------------------------------------


def find_tool(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for path in (
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files (x86)\NSIS\makensis.exe"),
        Path(r"C:\Program Files\NSIS\makensis.exe"),
    ):
        if path.is_file():
            return str(path)
    return None


def build_archive(session: Session, probe: Probe) -> None:
    def action() -> dict:
        if session.os_name == "linux":
            archive = session.dist / f"{session.app_id}-{session.version}-linux-x86_64.tar.gz"
            checked(["tar", "-C", str(session.bundle), "-czf", str(archive), "."], timeout=TIMEOUTS["command"])
            session.artifact = {"tool": "tarball", "path": str(archive), "bytes": archive.stat().st_size, "sha256": sha256_file(archive)}
        else:
            iscc = find_tool("iscc", "ISCC.exe")
            nsis = find_tool("makensis", "makensis.exe")
            inno_error = ""
            if iscc:
                output_name = f"{session.app_id}-{session.version}-windows-x86_64-setup"
                script = session.dist / "installer.iss"
                script.write_text(
                    render_iss(
                        {
                            "APP_ID": session.app_id,
                            "DISPLAY_NAME": session.display_name,
                            "VERSION": session.version,
                            "BUNDLE_DIR": str(session.bundle),
                            "OUTPUT_DIR": str(session.dist),
                            "OUTPUT_NAME": output_name,
                        }
                    ),
                    encoding="utf-8-sig",
                )
                compiled = run([iscc, "/Q", str(script)], timeout=TIMEOUTS["command"])
                if compiled.ok and (session.dist / f"{output_name}.exe").is_file():
                    setup = session.dist / f"{output_name}.exe"
                    session.artifact = {"tool": "inno", "path": str(setup), "bytes": setup.stat().st_size, "sha256": sha256_file(setup)}
                else:
                    # The task file's gate: if Inno Setup fails, run the same check with NSIS
                    # at user level and record both facts.
                    inno_error = compiled.tail()
            if not session.artifact and nsis:
                setup = session.dist / f"{session.app_id}-{session.version}-windows-x86_64-setup.exe"
                script = session.dist / "installer.nsi"
                script.write_text(
                    render_nsi(
                        {
                            "APP_ID": session.app_id,
                            "DISPLAY_NAME": session.display_name,
                            "VERSION": session.version,
                            "BUNDLE_DIR": str(session.bundle),
                            "OUTPUT_FILE": str(setup),
                        }
                    ),
                    encoding="utf-8",
                )
                checked([nsis, "/V2", str(script)], timeout=TIMEOUTS["command"])
                require(setup.is_file(), f"NSIS did not write {setup.name}")
                session.artifact = {"tool": "nsis", "path": str(setup), "bytes": setup.stat().st_size, "sha256": sha256_file(setup)}
                if inno_error:
                    session.artifact["inno_error"] = inno_error
            if not session.artifact:
                if inno_error:
                    raise ProbeError(f"Inno Setup failed and NSIS is not installed: {inno_error}")
                raise ProbeError("neither Inno Setup nor NSIS is installed")
        session.measurements["compressed_bytes"] = session.artifact["bytes"]
        return dict(session.artifact)

    stage(probe, "archive.build", action, detail="installer or tarball built from the bundle")


def check_archive(session: Session, probe: Probe) -> None:
    ready(session, "artifact")

    def action() -> dict:
        if session.os_name == "linux":
            modes = tar_modes(Path(session.artifact["path"]))
            required = ["start.sh"]
            if session.python_exe is not None:
                required.append("python/bin/python3.11")
            missing = missing_exec_modes(modes, required)
            require(not missing, f"tar lost the executable bit: {missing}")
            return {
                "start_sh_mode": oct(modes["start.sh"]),
                "python_mode": oct(modes.get("python/bin/python3.11", 0)),
                "required": required,
            }
        tool = session.artifact["tool"]
        script = session.dist / ("installer.iss" if tool == "inno" else "installer.nsi")
        text = script.read_text(encoding="utf-8-sig" if tool == "inno" else "utf-8")
        lowered = text.lower()
        if tool == "inno":
            require("privilegesrequired=lowest" in lowered, "the Inno script does not install per user")
            require("{localappdata}\\programs\\" in lowered, "the Inno script does not install below localappdata")
        else:
            require("requestexecutionlevel user" in lowered, "the NSIS script does not install per user")
            require("$localappdata" in lowered, "the NSIS script does not install below localappdata")
        require("pythonw.exe" in lowered and "launcher.py" in lowered, "the shortcut does not run the launcher")
        return {"tool": tool, "privileges": "lowest" if tool == "inno" else "user", "shortcut_launcher": True}

    stage(probe, "archive.check", action, detail="archive keeps its start path and per-user install")


# --- user, install, shortcut --------------------------------------------------------


def resolve_user(session: Session, probe: Probe) -> None:
    if session.args.dry_run:
        probe.skip("install.user", "dry run uses the current account", detail="no new account")
        session.user = {
            "created": False,
            "login": os.environ.get("USER", os.environ.get("USERNAME", "")),
            "home": str(session.paths["home"]),
            "install": str(session.paths["install"]),
            "difference": "dry run: no new account",
        }
        session.install = Path(session.paths["install"])
        return

    def action() -> dict:
        return make_linux_user(session) if session.os_name == "linux" else make_windows_user(session)

    data = stage(probe, "install.user", action, detail="synthetic Korean account and home")
    session.user = data
    session.install = Path(data["install"])


def make_linux_user(session: Session) -> dict:
    login = session.paths["login_name"]
    home = session.paths["home"]
    home.parent.mkdir(parents=True, exist_ok=True)
    home.parent.chmod(0o755)
    completed = run(
        ["sudo", "-n", "useradd", "--badname", "--create-home", "--home-dir", str(home), "--shell", "/bin/sh", login],
        timeout=TIMEOUTS["command"],
    )
    if not completed.ok:
        exists = run(["id", "-u", login], timeout=30)
        if not exists.ok:
            return {
                "created": False,
                "login": os.environ.get("USER", ""),
                "home": str(home),
                "install": str(install_dir(home, session.app_id, session.version)),
                "difference": f"useradd failed, so the current account used a Korean and spaced HOME: {completed.tail(400)}",
            }
    return {
        "created": True,
        "login": login,
        "home": str(home),
        "install": str(install_dir(home, session.app_id, session.version)),
        "difference": "Linux login names cannot contain a space; the home path has Korean letters and a space",
    }


def make_windows_user(session: Session) -> dict:
    login = session.paths["login_name"]
    password = "Pb-" + secrets.token_hex(12)
    completed = run(["net", "user", login, password, "/add"], timeout=TIMEOUTS["command"])
    if completed.ok:
        run(["net", "localgroup", "Users", login, "/add"], timeout=TIMEOUTS["command"])
        session.password = password
        profile = Path(os.environ.get("SystemDrive", "C:")) / "Users" / login
        return {
            "created": True,
            "login": login,
            "home": str(profile),
            "install": str(install_dir(profile / "AppData" / "Local", session.app_id, session.version)),
            "difference": "the install path is the account's own localappdata",
        }
    return {
        "created": False,
        "login": os.environ.get("USERNAME", ""),
        "home": str(session.paths["home"]),
        "install": str(install_dir(session.paths["home"] / "AppData" / "Local", session.app_id, session.version)),
        "difference": f"net user failed, so the current account overrode USERPROFILE and LOCALAPPDATA: {completed.tail(400)}",
    }


def as_user(session: Session, command: list[str], *, env: dict | None = None, timeout: float = TIMEOUTS["command"]):
    if session.os_name == "linux" and session.user.get("created"):
        return run(
            ["sudo", "-n", "-u", session.user["login"], "--", "env", f"HOME={session.user['home']}", f"PATH={MINIMAL_PATH}", *command],
            timeout=timeout,
        )
    environment = (env or os.environ).copy()
    environment["HOME"] = session.user.get("home", str(session.paths["home"]))
    if session.os_name == "linux":
        environment["PATH"] = MINIMAL_PATH
    return run(command, env=environment, timeout=timeout)


def apply_install(session: Session, probe: Probe) -> None:
    ready(session, "artifact", "user")

    def action() -> dict:
        if session.os_name == "linux":
            target = Path(session.user["install"])
            created = as_user(session, ["mkdir", "-p", str(target)])
            if not created.ok:
                raise ProbeError(f"cannot create the install directory: {created.tail()}")
            started = time.monotonic()
            extracted = as_user(session, ["tar", "-xzf", session.artifact["path"], "-C", str(target)])
            elapsed = time.monotonic() - started
            if not extracted.ok:
                raise ProbeError(f"tar extraction failed: {extracted.tail()}")
            start_sh = target / "start.sh"
            require(start_sh.is_file(), "start.sh was not installed")
            require(os.access(start_sh, os.X_OK), "the installed start.sh is not executable")
        else:
            started = time.monotonic()
            run_windows_installer(session)
            elapsed = time.monotonic() - started
            target = Path(session.user["install"])
            require(target.is_dir(), f"installer did not create {target}")
        session.install = target
        session.measurements["install_seconds"] = round(elapsed, 3)
        session.measurements["installed_bytes"] = tree_bytes(target)
        return {"install_dir": str(target), "installed_bytes": session.measurements["installed_bytes"], "seconds": session.measurements["install_seconds"]}

    stage(probe, "install.apply", action, detail="silent install into the synthetic home")


def silent_flags(tool: str, install_path: Path | None) -> list[str]:
    """Silent install switches for the built installer, with an optional directory override."""
    if tool == "nsis":
        flags = ["/S"]
        if install_path is not None:
            # NSIS wants /D last and unquoted; the probe records a failure to install there.
            flags.append(f"/D={install_path}")
        return flags
    flags = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    if install_path is not None:
        flags.append(f'/DIR="{install_path}"')
    return flags


def run_windows_installer(session: Session) -> None:
    install_path = Path(session.user["install"])
    installer = session.artifact["path"]
    if session.user.get("created"):
        task = f"installer-probe-{secrets.token_hex(4)}"
        # The default {localappdata} of the new account is the Korean profile path, so the
        # task needs no directory override and the command line stays short.
        command = f'"{installer}" ' + " ".join(silent_flags(session.artifact["tool"], None))
        create = run(
            ["schtasks", "/Create", "/TN", task, "/RU", session.user["login"], "/RP", session.password, "/SC", "ONCE", "/ST", "23:59", "/TR", command, "/F"],
            timeout=TIMEOUTS["command"],
        )
        if not create.ok:
            raise ProbeError(f"cannot schedule the installer as the new account: {create.tail()}")
        run(["schtasks", "/Run", "/TN", task], timeout=TIMEOUTS["command"])
        try:
            result = wait_windows_task(task, TIMEOUTS["install"])
        finally:
            run(["schtasks", "/Delete", "/TN", task, "/F"], timeout=60)
        if result != 0:
            raise ProbeError(f"the installer exited {result} as {session.user['login']}")
        return
    environment = os.environ.copy()
    environment["USERPROFILE"] = str(session.user["home"])
    environment["LOCALAPPDATA"] = str(Path(session.user["home"]) / "AppData" / "Local")
    checked(
        [installer, *silent_flags(session.artifact["tool"], install_path)],
        env=environment,
        timeout=TIMEOUTS["install"],
    )


def wait_windows_task(task: str, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        completed = run(["schtasks", "/Query", "/TN", task, "/FO", "LIST", "/V"], timeout=60)
        last = completed.stdout
        status, result = parse_task_status(last)
        if status == "Ready" and result not in (None, 267011):
            return int(result)
        time.sleep(1.0)
    raise ProbeError(f"the scheduled task did not finish in {timeout:g}s: {last[-400:]}")


def verify_shortcut(session: Session, probe: Probe) -> None:
    def action() -> dict:
        if session.os_name == "linux":
            start_sh = session.install / "start.sh"
            mode = start_sh.stat().st_mode & 0o777
            require(mode & 0o111, f"start.sh mode is {oct(mode)}")
            return {"start_sh": str(start_sh), "mode": oct(mode)}
        home = Path(session.user["home"])
        programs = home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        shortcuts = sorted(programs.rglob("*.lnk")) if programs.is_dir() else []
        require(shortcuts, f"no shortcut under {programs}")
        shortcut = shortcuts[0]
        completed = checked(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}');"
                "Write-Output $s.TargetPath; Write-Output $s.Arguments; Write-Output $s.WorkingDirectory",
            ],
            timeout=120,
        )
        target, arguments, working_directory = parse_shortcut(completed.stdout)
        require(Path(target).is_file(), f"shortcut target does not exist: {target}")
        require("launcher.py" in arguments, f"shortcut does not run the launcher: {arguments}")
        require(under(target, session.install), f"shortcut target is outside the install dir: {target}")
        session.record.update({"shortcut": str(shortcut), "target": target, "arguments": arguments, "working_directory": working_directory})
        return {"shortcut": str(shortcut), "target": target, "arguments": arguments}

    stage(probe, "shortcut.target", action, detail="start shortcut runs the bundled launcher")


# --- start, health, stop ------------------------------------------------------------


def start(session: Session, probe: Probe) -> None:
    def action() -> dict:
        session.port_file = session.install / "port.json"
        if session.port_file.exists():
            session.port_file.unlink()
        started = time.monotonic()
        if session.os_name == "linux":
            command = [str(session.install / "start.sh"), "--port-file", str(session.port_file), "--no-browser"]
            if session.user.get("created"):
                command = ["sudo", "-n", "-u", session.user["login"], "--", "env", f"HOME={session.user['home']}", f"PATH={MINIMAL_PATH}", *command]
            environment = os.environ.copy()
            if not session.user.get("created"):
                environment["HOME"] = session.user.get("home", str(session.paths["home"]))
                environment["PATH"] = MINIMAL_PATH
            session.process = subprocess.Popen(
                command,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        else:
            schedule_windows_launcher(session)
        deadline = time.monotonic() + TIMEOUTS["start"]
        last = ""
        while time.monotonic() < deadline:
            if session.port_file.exists() and session.port_file.stat().st_size:
                break
            if session.process is not None and session.process.poll() is not None:
                last = (session.process.stderr.read() or "")[-800:] if session.process.stderr else ""
                break
            time.sleep(0.1)
        if not session.port_file.exists():
            raise ProbeError(f"the launcher did not write a port file: {last}")
        record = parse_port_file(session.port_file.read_text(encoding="utf-8"))
        payload = wait_health(record["port"], timeout=max(1.0, deadline - time.monotonic()))
        session.record.update({**record, "health": payload})
        session.measurements["start_seconds"] = round(time.monotonic() - started, 3)
        return {
            "port": record["port"],
            "launcher_pid": record.get("launcher_pid"),
            "server_pid": record.get("server_pid"),
            "seconds": session.measurements["start_seconds"],
        }

    stage(probe, "app.start", action, detail="launcher picked a free port and the app became healthy")


def schedule_windows_launcher(session: Session) -> None:
    task = f"installer-probe-{secrets.token_hex(4)}"
    command = f'"{session.record["target"]}" {session.record["arguments"]} --port-file "{session.port_file}" --no-browser'
    create = run(
        ["schtasks", "/Create", "/TN", task, "/RU", session.user["login"], "/RP", session.password, "/SC", "ONCE", "/ST", "23:59", "/TR", command, "/F"],
        timeout=TIMEOUTS["command"],
    )
    if not create.ok:
        raise ProbeError(f"cannot schedule the launcher as the new account: {create.tail()}")
    run(["schtasks", "/Run", "/TN", task], timeout=TIMEOUTS["command"])
    session.task = task


def health(session: Session, probe: Probe) -> None:
    def action() -> dict:
        payload = session.record.get("health") or {}
        require(payload.get("status") == "ok", f"/health body is not ok: {payload}")
        server_python = str(payload.get("python", ""))
        base_prefix = str(payload.get("base_prefix", ""))
        require(bool(server_python), "/health did not report the interpreter")
        require(path_under(server_python, session.install), f"the server interpreter is outside the install dir: {server_python}")
        base_inside = under(base_prefix, session.install) if base_prefix else False
        if not session.args.dry_run:
            require(base_inside, f"the base interpreter is outside the install dir: {base_prefix}")
        return {
            "status": payload["status"],
            "server_python": server_python,
            "server_python_version": payload.get("version"),
            "server_base_prefix": base_prefix,
            "base_prefix_inside_install": base_inside,
            "port": session.record.get("port"),
        }

    stage(probe, "app.health", action, detail="GET /health returned 200 after install")


def not_from_path(session: Session, probe: Probe) -> None:
    def action() -> dict:
        server_python = str((session.record.get("health") or {}).get("python", ""))
        on_path = shutil.which("python") or shutil.which("python3")
        require(on_path is not None, "no Python on PATH, so the check cannot prove the negative")
        require(Path(server_python).resolve() != Path(on_path).resolve(), "the server used the interpreter from PATH")
        require(path_under(server_python, session.install), f"server interpreter is not installed: {server_python}")
        return {
            "server_python": server_python,
            "path_python": on_path,
            "path": MINIMAL_PATH if session.os_name == "linux" else os.environ.get("PATH", ""),
            "install_dir": str(session.install),
        }

    stage(probe, "python.not_from_path", action, detail="the server ran the installed interpreter, not PATH python")


def long_path(session: Session, probe: Probe) -> None:
    def action() -> dict:
        require(session.install.is_dir(), "the install directory is missing")
        target = deep_path(session.install, LONG_PATH_TARGET)
        target.mkdir(parents=True, exist_ok=True)
        marker = target / "probe.txt"
        marker.write_text("ok\n", encoding="utf-8")
        require(marker.read_text(encoding="utf-8").strip() == "ok", "cannot read the deep marker")
        beyond = deep_path(session.install, LONG_PATH_BEYOND)
        beyond_ok = False
        beyond_error = ""
        try:
            beyond.mkdir(parents=True, exist_ok=True)
            (beyond / "probe.txt").write_text("ok\n", encoding="utf-8")
            beyond_ok = True
        except OSError as exc:
            beyond_error = f"{type(exc).__name__}: {exc}"
        return {
            "install_dir_chars": len(str(session.install)),
            "deep_path": str(target),
            "deep_path_chars": len(str(target)),
            "beyond_max_chars": len(str(beyond)),
            "beyond_max_created": beyond_ok,
            "beyond_max_error": beyond_error,
            "note": "paths above 260 characters depend on the OS policy and are recorded, not gated",
        }

    stage(probe, "path.long", action, detail="deep path under the install directory")


def stop_process(session: Session) -> None:
    """Stop the launcher and the server. Safe to call twice."""
    if session.stopped:
        return
    session.stopped = True
    record = session.record
    if session.os_name == "windows":
        for key in ("launcher_pid", "server_pid"):
            pid = record.get(key)
            if pid:
                run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=60)
        if session.task:
            run(["schtasks", "/End", "/TN", session.task], timeout=60)
            run(["schtasks", "/Delete", "/TN", session.task, "/F"], timeout=60)
        return
    if session.process is None:
        return
    if session.process.poll() is None:
        if not session.user.get("created"):
            try:
                os.killpg(os.getpgid(session.process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        for key in ("launcher_pid", "server_pid"):
            pid = record.get(key)
            if pid:
                command = ["kill", "-TERM", str(pid)]
                if session.user.get("created"):
                    command = ["sudo", "-n", *command]
                run(command, timeout=30)
    try:
        session.process.wait(timeout=TIMEOUTS["stop"])
    except subprocess.TimeoutExpired:
        session.process.kill()


def stop(session: Session, probe: Probe) -> None:
    def action() -> dict:
        stop_process(session)
        return {"stopped": True}

    if session.process is None and not session.record.get("server_pid") and not session.task:
        probe.skip("app.stop", "the app never started")
        return
    stage(probe, "app.stop", action, detail="launcher and server stopped")


# --- main ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("out"))
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--os", choices=("auto", "linux", "windows"), default="auto")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--python", default="", help="interpreter for --dry-run")
    parser.add_argument("--keep", action="store_true", help="keep the work directory")
    parser.add_argument("--strict", action="store_true", help="exit 2 on a harness error")
    return parser.parse_args(argv)


def detect_os(explicit: str) -> str:
    if explicit != "auto":
        return explicit
    return "windows" if sys.platform == "win32" else "linux"


def default_work_dir() -> Path:
    for name in ("RUNNER_TEMP", "TMPDIR", "TEMP", "TMP"):
        value = os.environ.get(name)
        if value:
            return Path(value) / f"installer-probe-{os.getpid()}"
    return Path(tempfile.mkdtemp(prefix="installer-probe-"))


def cleanup(session: Session) -> None:
    if session.os_name == "linux" and session.user.get("created"):
        run(["sudo", "-n", "rm", "-rf", str(session.work)], timeout=120)
        return
    shutil.rmtree(session.work, ignore_errors=True)


def base_payload(session: Session, mode: str) -> dict:
    return {
        "probe": "installer",
        "mode": mode,
        "os": session.os_name,
        "label": session.label,
        "runner": session.manifest["runners"][session.label],
        "started_at": session.started_at,
        "finished_at": None,
        "harness_error": False,
        "app_version": session.version,
        "brand": {"display_name_en": session.display_name, "app_id": session.app_id},
        "paths": {"work": str(session.root), "install": str(session.install)},
        "python": {
            "version": session.manifest["python"]["version"],
            "release": session.manifest["python"]["release"],
            "distribution": session.manifest["python"]["distribution"],
            "asset": {},
            "executable": "",
        },
        "installer": {"tool": None, "path": None, "bytes": None, "sha256": None},
        "user": {"created": False, "login": "", "home": str(session.paths["home"]), "difference": ""},
        "measurements": session.measurements,
        "checks": [],
    }


PIPELINE: list[tuple[str, Callable[[Session, Probe], None]]] = [
    ("runtime.download", download_runtime),
    ("runtime.extract", extract_runtime),
    ("env.venv", create_venv),
    ("env.requirements", sync_requirements),
    ("bundle.app", copy_app),
    ("archive.build", build_archive),
    ("archive.check", check_archive),
    ("install.user", resolve_user),
    ("install.apply", apply_install),
    ("shortcut.target", verify_shortcut),
    ("app.start", start),
    ("app.health", health),
    ("python.not_from_path", not_from_path),
    ("path.long", long_path),
    ("app.stop", stop),
]


def run_pipeline(session: Session, probe: Probe) -> None:
    blocked: str | None = None
    for check_id, func in PIPELINE:
        if blocked:
            probe.skip(check_id, blocked)
            continue
        try:
            func(session, probe)
        except Blocked as exc:
            blocked = str(exc)
        except Exception as exc:  # noqa: BLE001 - an unexpected probe bug is a harness error
            failure = exc

            def raise_failure(failure=failure) -> dict:
                raise failure

            probe.check(f"{check_id}.error", raise_failure)
            blocked = f"{check_id} raised {type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    os_name = detect_os(args.os)
    if args.dry_run and os_name != "linux":
        raise SystemExit("--dry-run supports Linux only")
    manifest = load_manifest()
    brand = read_brand(Path(__file__).resolve().parents[2])
    if args.work_dir is None:
        args.work_dir = default_work_dir()
    session = Session(args, manifest, brand, os_name)
    session.make_dirs()
    payload = base_payload(session, "dry_run" if args.dry_run else "real")
    probe = Probe()
    try:
        run_pipeline(session, probe)
    finally:
        stop_process(session)
        payload["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload["harness_error"] = probe.harness_failed
        payload["checks"] = [check.as_dict() for check in probe.checks]
        payload["installer"] = {
            "tool": session.artifact.get("tool"),
            "path": session.artifact.get("path"),
            "bytes": session.artifact.get("bytes"),
            "sha256": session.artifact.get("sha256"),
        }
        payload["python"]["asset"] = session.manifest["python"]["assets"][session.label] if not args.dry_run else {"name": "dry-run"}
        payload["python"]["version"] = session.python_version
        payload["python"]["executable"] = str(session.python_exe or session.env_python or "")
        if session.user:
            payload["user"] = session.user
        payload["paths"]["install"] = str(session.install)
        payload["measurements"] = session.measurements
        if session.record:
            payload["launcher"] = {key: value for key, value in session.record.items() if key != "health"}
            payload["launcher"]["health"] = session.record.get("health")
        result_path, _summary_path = write_result(args.output, payload)
        print(f"result: {result_path}")
        print(summary_markdown(payload))
        if not args.keep and not Path(args.output).resolve().is_relative_to(session.work):
            cleanup(session)
    if probe.harness_failed:
        print("harness error: the workflow must fail", file=sys.stderr)
        return 2 if args.strict else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
