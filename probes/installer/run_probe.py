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
from pathlib import Path, PureWindowsPath
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    BUNDLED_PYTHON,
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
    run_windows_command,
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
        self.base_python: Path | None = None
        self.env_python: Path | None = None
        self.python_version = manifest["python"]["version"]
        self.site_packages_rel = ""
        self.site_packages_bytes = 0
        self.fallback: dict = {}
        self.artifact: dict = {}
        self.nsis_artifact: dict = {}
        self.nsis_error = ""
        self.primary_artifact: dict = {}
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


def purelib(env_python: Path) -> Path:
    completed = checked([str(env_python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"])
    path = Path(completed.stdout.strip())
    require(path.is_absolute(), f"purelib is not absolute: {path}")
    return path


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
        checked([str(python), "-m", "venv", "--without-pip", str(session.bundle / "env")], timeout=TIMEOUTS["command"])
        env_python = session.bundle / "env" / ("Scripts/python.exe" if session.os_name == "windows" else "bin/python")
        require(env_python.is_file(), f"venv interpreter is missing: {env_python}")
        session.env_python = env_python
        session.base_python = python
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


def pack_site_packages(session: Session, probe: Probe) -> None:
    ready(session, "env_python")

    def action() -> dict:
        packages = purelib(session.env_python)
        target = session.bundle / "site-packages"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(packages, target)
        session.site_packages_rel = packages.relative_to(session.bundle).as_posix()
        session.site_packages_bytes = tree_bytes(target)
        # The build venv holds absolute paths to this bundle. Ship only its package files;
        # the installed launcher passes that folder as PYTHONPATH.
        shutil.rmtree(session.bundle / "env")
        require(not (session.bundle / "env").exists(), "the build environment is still in the bundle")
        if session.args.dry_run:
            link = session.bundle / "python/bin/python3.11"
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.exists():
                link.symlink_to(Path(session.base_python or sys.executable))
        return {
            "relative": session.site_packages_rel,
            "bytes": session.site_packages_bytes,
            "files": sum(1 for path in target.rglob("*") if path.is_file()),
        }

    stage(probe, "env.site_packages", action, detail="package files copied out of the build environment")


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


def build_nsis_artifact(session: Session, makensis: str) -> dict:
    setup = session.dist / f"{session.app_id}-{session.version}-windows-x86_64-nsis-setup.exe"
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
    checked([makensis, "/V2", str(script)], timeout=TIMEOUTS["command"])
    require(setup.is_file(), f"NSIS did not write {setup.name}")
    return {"tool": "nsis", "path": str(setup), "bytes": setup.stat().st_size, "sha256": sha256_file(setup)}


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
                session.artifact = build_nsis_artifact(session, nsis)
                if inno_error:
                    session.artifact["inno_error"] = inno_error
            if not session.artifact:
                if inno_error:
                    raise ProbeError(f"Inno Setup failed and NSIS is not installed: {inno_error}")
                raise ProbeError("neither Inno Setup nor NSIS is installed")
            if session.artifact.get("tool") == "inno" and nsis:
                # Keep an NSIS setup ready so an install or start failure can rerun the same
                # test after the build bundle is removed.
                try:
                    session.nsis_artifact = build_nsis_artifact(session, nsis)
                except (ProbeError, HarnessError) as exc:
                    session.nsis_error = str(exc)
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
            require("site-packages/fastapi/__init__.py" in modes, "tar has no bundled package folder")
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
        require("python\\pythonw.exe" in lowered and "launcher.py" in lowered, "the shortcut does not run the bundled interpreter")
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


def windows_user_home(login: str) -> PureWindowsPath:
    drive = os.environ.get("SystemDrive", "C:").rstrip("\\/") + "\\"
    return PureWindowsPath(drive) / "Users" / login


def make_windows_user(session: Session) -> dict:
    login = session.paths["login_name"]
    password = "Pb-" + secrets.token_hex(12)
    completed = run(["net", "user", login, password, "/add"], timeout=TIMEOUTS["command"])
    if completed.ok:
        run(["net", "localgroup", "Users", login, "/add"], timeout=TIMEOUTS["command"])
        session.password = password
        profile = Path(windows_user_home(login))
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


def as_user(
    session: Session,
    command: list[str],
    *,
    env: dict | None = None,
    timeout: float = TIMEOUTS["command"],
    timeout_is_probe: bool = False,
):
    if session.os_name == "linux" and session.user.get("created"):
        return run(
            ["sudo", "-n", "-u", session.user["login"], "--", "env", f"HOME={session.user['home']}", f"PATH={MINIMAL_PATH}", *command],
            timeout=timeout,
            timeout_is_probe=timeout_is_probe,
        )
    environment = (env or os.environ).copy()
    environment["HOME"] = session.user.get("home", str(session.paths["home"]))
    if session.os_name == "linux":
        environment["PATH"] = MINIMAL_PATH
    return run(command, env=environment, timeout=timeout, timeout_is_probe=timeout_is_probe)


def install_tarball(session: Session, target: Path) -> None:
    created = as_user(session, ["mkdir", "-p", str(target)], timeout_is_probe=True)
    if not created.ok:
        raise ProbeError(f"cannot create the install directory: {created.tail()}")
    extracted = as_user(session, ["tar", "-xzf", session.artifact["path"], "-C", str(target)], timeout_is_probe=True)
    if not extracted.ok:
        raise ProbeError(f"tar extraction failed: {extracted.tail()}")
    start_sh = target / "start.sh"
    require(start_sh.is_file(), "start.sh was not installed")
    require(os.access(start_sh, os.X_OK), "the installed start.sh is not executable")


def apply_install(session: Session, probe: Probe, check_id: str = "install.apply", target: Path | None = None) -> None:
    ready(session, "artifact", "user")

    def action() -> dict:
        install_root = Path(target or session.user["install"])
        started = time.monotonic()
        if session.os_name == "linux":
            install_tarball(session, install_root)
        else:
            run_windows_installer(session)
            require(install_root.is_dir(), f"installer did not create {install_root}")
        elapsed = time.monotonic() - started
        session.install = install_root
        if check_id == "install.apply":
            session.measurements["install_seconds"] = round(elapsed, 3)
            session.measurements["installed_bytes"] = tree_bytes(install_root)
        elif check_id == "nsis.install":
            session.measurements["fallback_install_seconds"] = round(elapsed, 3)
        return {
            "install_dir": str(install_root),
            "installed_bytes": tree_bytes(install_root),
            "seconds": round(elapsed, 3),
        }

    stage(probe, check_id, action, detail="silent install of the bundled interpreter, environment and app")


def windows_installer_command(tool: str, installer: str, install_path: Path | None = None) -> str:
    """Build the command line with the quoting each setup tool parses.

    Inno Setup wants a literal quoted /DIR value. NSIS wants /D as the last unquoted item.
    Passing a list to subprocess would escape the Inno quotes and quote the NSIS path.
    """
    command = f'"{installer}"'
    if tool == "nsis":
        command += " /S"
        if install_path is not None:
            command += f" /D={install_path}"
        return command
    command += " /VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
    if install_path is not None:
        command += f' /DIR="{install_path}"'
    return command


def run_windows_installer(session: Session) -> None:
    install_path = Path(session.user["install"])
    installer = session.artifact["path"]
    if session.user.get("created"):
        task = f"installer-probe-{secrets.token_hex(4)}"
        # The default {localappdata} of the new account is the Korean profile path, so the
        # task needs no directory override and the command line stays short.
        command = windows_installer_command(session.artifact["tool"], installer)
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
    completed = run_windows_command(
        windows_installer_command(session.artifact["tool"], installer, install_path),
        env=windows_user_env(session.user),
        timeout=TIMEOUTS["install"],
        timeout_is_probe=True,
    )
    if not completed.ok:
        raise ProbeError(f"the installer exited {completed.returncode}: {completed.tail()}")


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


def bundle_removed(session: Session, probe: Probe) -> None:
    def action() -> dict:
        if session.bundle.exists():
            shutil.rmtree(session.bundle)
        require(not session.bundle.exists(), f"the build folder still exists: {session.bundle}")
        return {"build_folder": str(session.bundle), "removed": True}

    stage(probe, "bundle.removed", action, detail="build folder removed before the app starts")


def verify_shortcut(session: Session, probe: Probe, check_id: str = "shortcut.target") -> None:
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
        expected = str(session.install / "python" / "pythonw.exe")
        require(target.lower() == expected.lower(), f"shortcut does not use the app environment: {target}")
        session.record.update({"shortcut": str(shortcut), "target": target, "arguments": arguments, "working_directory": working_directory})
        return {"shortcut": str(shortcut), "target": target, "arguments": arguments}

    stage(probe, check_id, action, detail="start shortcut runs the launcher with the bundled interpreter")


def shortcut_arguments(text: str) -> list[str]:
    """Split the shortcut argument string. The probe writes one quoted launcher path."""
    value = text.strip()
    if value.startswith('"') and value.endswith('"') and value.count('"') == 2:
        return [value[1:-1]]
    return [part for part in value.split() if part]


# --- start, health, stop ------------------------------------------------------------


def launch_linux(session: Session, target: Path) -> subprocess.Popen:
    command = [str(target / "start.sh")]
    if session.user.get("created"):
        command = ["sudo", "-n", "-u", session.user["login"], "--", "env", f"HOME={session.user['home']}", f"PATH={MINIMAL_PATH}", *command]
    environment = os.environ.copy()
    if not session.user.get("created"):
        environment["HOME"] = session.user.get("home", str(session.paths["home"]))
        environment["PATH"] = MINIMAL_PATH
    return subprocess.Popen(
        command,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def windows_user_env(user: dict) -> dict:
    environment = os.environ.copy()
    environment["USERPROFILE"] = str(user["home"])
    environment["LOCALAPPDATA"] = str(Path(user["home"]) / "AppData" / "Local")
    return environment


def launch_windows_direct(session: Session, target: Path) -> subprocess.Popen:
    environment = windows_user_env(session.user)
    return subprocess.Popen(
        [session.record["target"], *shortcut_arguments(session.record["arguments"])],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_for_app(session: Session, target: Path, process: subprocess.Popen | None) -> tuple[dict, dict, float]:
    started = time.monotonic()
    port_file = target / "port.json"
    deadline = time.monotonic() + TIMEOUTS["start"]
    last = ""
    while time.monotonic() < deadline:
        if port_file.exists() and port_file.stat().st_size:
            break
        if process is not None and process.poll() is not None:
            last = (process.stderr.read() or "")[-800:] if process.stderr else ""
            break
        time.sleep(0.1)
    if not port_file.exists():
        raise ProbeError(f"the launcher did not write a port file: {last}")
    record = parse_port_file(port_file.read_text(encoding="utf-8"))
    payload = wait_health(record["port"], timeout=max(1.0, deadline - time.monotonic()))
    return record, payload, time.monotonic() - started


def start(session: Session, probe: Probe, check_id: str = "app.start", target: Path | None = None) -> None:
    def action() -> dict:
        app_root = Path(target or session.install)
        port_file = app_root / "port.json"
        if port_file.exists():
            port_file.unlink()
        if session.os_name == "linux":
            process = launch_linux(session, app_root)
        elif session.user.get("created"):
            schedule_windows_launcher(session, app_root)
            process = None
        else:
            process = launch_windows_direct(session, app_root)
        record, payload, seconds = wait_for_app(session, app_root, process)
        session.process = process
        session.record.update({**record, "health": payload})
        if check_id == "app.start":
            session.measurements["start_seconds"] = round(seconds, 3)
        return {
            "port": record["port"],
            "launcher_pid": record.get("launcher_pid"),
            "server_pid": record.get("server_pid"),
            "browser_opened": record.get("browser_opened"),
            "seconds": round(seconds, 3),
        }

    stage(probe, check_id, action, detail="no-argument start opened a free port and became healthy")


def schedule_windows_launcher(session: Session, target: Path) -> None:
    task = f"installer-probe-{secrets.token_hex(4)}"
    command = f'"{session.record["target"]}" {session.record["arguments"]}'
    create = run(
        ["schtasks", "/Create", "/TN", task, "/RU", session.user["login"], "/RP", session.password, "/SC", "ONCE", "/ST", "23:59", "/TR", command, "/F"],
        timeout=TIMEOUTS["command"],
    )
    if not create.ok:
        raise ProbeError(f"cannot schedule the launcher as the new account: {create.tail()}")
    run(["schtasks", "/Run", "/TN", task], timeout=TIMEOUTS["command"])
    session.task = task


def health(session: Session, probe: Probe, check_id: str = "app.health", target: Path | None = None) -> None:
    def action() -> dict:
        app_root = Path(target or session.install)
        payload = session.record.get("health") or {}
        require(payload.get("status") == "ok", f"/health body is not ok: {payload}")
        server_python = str(payload.get("python", ""))
        base_prefix = str(payload.get("base_prefix", ""))
        require(bool(server_python), "/health did not report the interpreter")
        require(path_under(server_python, app_root), f"the server interpreter is outside the install dir: {server_python}")
        base_inside = under(base_prefix, app_root) if base_prefix else False
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

    stage(probe, check_id, action, detail="GET /health returned 200 after install")


def not_from_path(session: Session, probe: Probe, check_id: str = "python.not_from_path", target: Path | None = None) -> None:
    def action() -> dict:
        app_root = Path(target or session.install)
        server_python = str((session.record.get("health") or {}).get("python", ""))
        on_path = shutil.which("python") or shutil.which("python3")
        require(on_path is not None, "no Python on PATH, so the check cannot prove the negative")
        require(Path(server_python).resolve() != Path(on_path).resolve(), "the server used the interpreter from PATH")
        require(path_under(server_python, app_root), f"server interpreter is not installed: {server_python}")
        return {
            "server_python": server_python,
            "path_python": on_path,
            "path": MINIMAL_PATH if session.os_name == "linux" else os.environ.get("PATH", ""),
            "install_dir": str(app_root),
        }

    stage(probe, check_id, action, detail="the server ran the installed interpreter, not PATH python")


def stop_windows_process(process: subprocess.Popen | None, record: dict) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=TIMEOUTS["stop"])
        except subprocess.TimeoutExpired:
            process.kill()
    for key in ("launcher_pid", "server_pid"):
        pid = record.get(key)
        if pid:
            run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=60)


def long_install_path(base: Path) -> Path:
    """A fresh 240+ character path for one long-path attempt."""
    return deep_path(base, LONG_PATH_TARGET) / f"r{secrets.token_hex(4)}"


def windows_long_path(session: Session, probe: Probe, check_id: str = "path.long") -> None:
    """Install and start on the running Windows account at a path of 240 characters or more."""

    def action() -> dict:
        require(session.user and session.artifact, "no installer or account")
        target = long_install_path(Path(session.user["install"]).parent)
        environment = windows_user_env(session.user)
        started = time.monotonic()
        completed = run_windows_command(
            windows_installer_command(session.artifact["tool"], session.artifact["path"], target),
            env=environment,
            timeout=TIMEOUTS["install"],
            timeout_is_probe=True,
        )
        if not completed.ok:
            raise ProbeError(f"the installer exited {completed.returncode}: {completed.tail()}")
        install_seconds = time.monotonic() - started
        require(target.is_dir(), f"the installer did not create the long path: {target}")
        interpreter = target / "python" / "pythonw.exe"
        launcher_script = target / "launcher.py"
        require(interpreter.is_file(), f"the bundled interpreter is missing: {interpreter}")
        require(launcher_script.is_file(), f"the launcher is missing: {launcher_script}")
        port_file = target / "port.json"
        if port_file.exists():
            port_file.unlink()
        process = subprocess.Popen(
            [str(interpreter), str(launcher_script)],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        record: dict = {}
        try:
            record, payload, start_seconds = wait_for_app(session, target, process)
            require(payload.get("status") == "ok", f"/health body is not ok: {payload}")
            server_python = str(payload.get("python", ""))
            require(path_under(server_python, target), f"long-path server interpreter is outside: {server_python}")
            require(under(str(payload.get("base_prefix", "")), target), "long-path base interpreter is outside")
        finally:
            stop_windows_process(process, record)
        return {
            "install_dir_chars": len(str(target)),
            "install_dir": str(target),
            "install_seconds": round(install_seconds, 3),
            "start_seconds": round(start_seconds, 3),
            "server_python": server_python,
            "account": os.environ.get("USERNAME", ""),
            "note": "installed and started on the running account at a path of 240 characters or more",
        }

    stage(probe, check_id, action, detail="full Windows install and /health at a long install path")


def long_path(session: Session, probe: Probe, check_id: str = "path.long") -> None:
    if session.os_name == "windows":
        windows_long_path(session, probe, check_id)
        return

    def action() -> dict:
        require(session.user and session.user.get("install"), "no install root")
        target = long_install_path(Path(session.user["install"]).parent)
        started = time.monotonic()
        install_tarball(session, target)
        install_seconds = time.monotonic() - started
        port_file = target / "port.json"
        if port_file.exists():
            port_file.unlink()
        process = launch_linux(session, target)
        store = {**session.record}
        try:
            record, payload, start_seconds = wait_for_app(session, target, process)
            require(payload.get("status") == "ok", f"/health body is not ok: {payload}")
            server_python = str(payload.get("python", ""))
            require(path_under(server_python, target), f"long-path server interpreter is outside: {server_python}")
            if not session.args.dry_run:
                require(under(str(payload.get("base_prefix", "")), target), "long-path base interpreter is outside")
        finally:
            stop_linux(session, process, record if "record" in locals() else {})
        session.record = store
        return {
            "install_dir_chars": len(str(target)),
            "install_dir": str(target),
            "install_seconds": round(install_seconds, 3),
            "start_seconds": round(start_seconds, 3),
            "server_python": server_python,
            "note": "installed and started at a path of 240 characters or more; paths above 260 depend on the OS policy",
        }

    stage(probe, check_id, action, detail="full install and /health at a long install path")


def stop_linux(session: Session, process: subprocess.Popen | None, record: dict) -> None:
    if process is None:
        return
    if process.poll() is None:
        if not session.user.get("created"):
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
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
        process.wait(timeout=TIMEOUTS["stop"])
    except subprocess.TimeoutExpired:
        process.kill()


def stop_process(session: Session) -> None:
    """Stop the launcher and the server. Safe to call twice."""
    if session.stopped:
        return
    session.stopped = True
    record = session.record
    if session.os_name == "windows":
        if session.process is not None and session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=TIMEOUTS["stop"])
            except subprocess.TimeoutExpired:
                session.process.kill()
        for key in ("launcher_pid", "server_pid"):
            pid = record.get(key)
            if pid:
                run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=60)
        if session.task:
            run(["schtasks", "/End", "/TN", session.task], timeout=60)
            run(["schtasks", "/Delete", "/TN", session.task, "/F"], timeout=60)
        return
    stop_linux(session, session.process, record)


def stop(session: Session, probe: Probe, check_id: str = "app.stop") -> None:
    def action() -> dict:
        stop_process(session)
        return {"stopped": True}

    if session.process is None and not session.record.get("server_pid") and not session.task:
        probe.skip(check_id, "the app never started")
        return
    stage(probe, check_id, action, detail="launcher and server stopped")


INSTALL_FAILURE_IDS = {"install.apply", "shortcut.target", "app.start", "app.health", "python.not_from_path", "path.long"}


def run_nsis_retry(session: Session, probe: Probe) -> None:
    """The task gate: after an Inno install or start failure, run the same test with NSIS."""
    if session.os_name != "windows" or session.artifact.get("tool") != "inno":
        return
    failed = {check.id for check in probe.failed}
    if not failed & INSTALL_FAILURE_IDS:
        return
    stop_process(session)
    session.stopped = False
    session.process = None
    session.task = ""
    session.record = {}
    makensis = find_tool("makensis", "makensis.exe")
    if not makensis:
        probe.skip("nsis.build", "NSIS is not installed")
        return

    def build() -> dict:
        if session.nsis_artifact:
            return dict(session.nsis_artifact)
        if not session.bundle.is_dir():
            raise ProbeError(f"no NSIS setup and no build bundle: {session.nsis_error}")
        return build_nsis_artifact(session, makensis)

    try:
        artifact = stage(probe, "nsis.build", build, detail="NSIS setup at user level after the Inno failure")
    except Blocked:
        return
    session.fallback = {"tool": "nsis", "reason": f"Inno Setup failed at {sorted(failed & INSTALL_FAILURE_IDS)}"}
    session.artifact = artifact
    target = Path(session.user["install"])
    shutil.rmtree(target, ignore_errors=True)
    home = Path(session.user["home"])
    programs = home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if programs.is_dir():
        for shortcut in programs.rglob("*.lnk"):
            try:
                shortcut.unlink()
            except OSError:
                pass
    blocked: str | None = None
    steps: list[tuple[str, Callable[..., None]]] = [
        ("nsis.install", apply_install),
        ("nsis.shortcut", verify_shortcut),
        ("nsis.start", start),
        ("nsis.health", health),
        ("nsis.not_from_path", not_from_path),
        ("nsis.stop", stop),
        ("nsis.path.long", long_path),
    ]
    for check_id, func in steps:
        if blocked:
            probe.skip(check_id, blocked)
            continue
        try:
            func(session, probe, check_id=check_id)
        except Blocked as exc:
            blocked = str(exc)


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
    ("env.site_packages", pack_site_packages),
    ("bundle.app", copy_app),
    ("archive.build", build_archive),
    ("archive.check", check_archive),
    ("install.user", resolve_user),
    ("install.apply", apply_install),
    ("bundle.removed", bundle_removed),
    ("shortcut.target", verify_shortcut),
    ("app.start", start),
    ("app.health", health),
    ("python.not_from_path", not_from_path),
    ("app.stop", stop),
    ("path.long", long_path),
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
        session.primary_artifact = dict(session.artifact)
        run_nsis_retry(session, probe)
    finally:
        stop_process(session)
        payload["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload["harness_error"] = probe.harness_failed
        payload["checks"] = [check.as_dict() for check in probe.checks]
        primary = session.primary_artifact or session.artifact
        payload["installer"] = {
            "tool": primary.get("tool"),
            "path": primary.get("path"),
            "bytes": primary.get("bytes"),
            "sha256": primary.get("sha256"),
        }
        if session.fallback:
            payload["fallback_installer"] = {
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
        if session.fallback:
            payload["fallback"] = session.fallback
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
