#!/usr/bin/env python3
"""Prepare pinned runtimes, speech inference wheels and model files.

    python scripts/dev_setup.py --runtime
    python scripts/dev_setup.py --models
    python scripts/dev_setup.py --tts-package

Runtime files go to APP_RUNTIME_DIR (default: <repo>/.local/rt); model files go
to APP_MODEL_DIR (default: <repo>/.local/models). Model item IDs start with
``model-`` and their files are installed verbatim, never extracted, except a
model file that is a ``.zip``: the archive stays in place and its members are
also extracted beside it, so NLTK reads its data directory. The application's
runtime preparer skips ``model-`` and ``package-`` items, so this script is the
only place that installs them. core/config/runtime.lock.json is the only source
of versions and hashes.

``--models`` also installs both Poetry environments (``core`` and
``core/align_runtime``), the pinned WhisperX wheel into the aligner
environment, and checks every direct dependency against its ``poetry.lock``.
An aligner environment built by an older lock is trimmed in place, whether it
lives in the project or in Poetry's cache. A project without one gets a
``.venv``. Each project keeps its own environment: the Poetry subprocesses
ignore the venv or Conda environment that the caller has activated. The second
run installs nothing and downloads no model file.
Run --models or --tts-package with the application's Python environment: the
verified Qwen wheel is installed there with pip --no-deps, without its demo UI.
Its manifest revision is the SHA-1 of the wheel, not an upstream Git revision.
Successful wheel installs are recorded separately in packages.installed.json
under APP_RUNTIME_DIR, including the Python environment used for installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "core" / "config" / "runtime.lock.json"
PROJECTS = (("core", ROOT / "core"), ("align", ROOT / "core" / "align_runtime"))
INSTALLED_PACKAGES = """
import importlib.metadata
import json

print(json.dumps(sorted({
    distribution.metadata["Name"]
    for distribution in importlib.metadata.distributions()
    if distribution.metadata["Name"]
})))
"""
CHECK_ENVIRONMENT = """
import importlib.metadata
import json
import sys

expected = json.loads(sys.argv[1])
bad = {}
for name, versions in expected.items():
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        actual = None
    if actual not in versions:
        bad[name] = actual
print(json.dumps(bad, sort_keys=True))
raise SystemExit(1 if bad else 0)
"""


def host_os() -> str:
    return "windows" if sys.platform == "win32" else "linux"


def host_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    raise SystemExit(f"unsupported architecture: {machine}")


def runtime_root() -> Path:
    configured = os.environ.get("APP_RUNTIME_DIR")
    return Path(configured).expanduser() if configured else ROOT / ".local" / "rt"


def model_root() -> Path:
    configured = os.environ.get("APP_MODEL_DIR")
    return Path(configured).expanduser() if configured else ROOT / ".local" / "models"


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def select_file(item: dict, os_name: str, arch: str) -> dict:
    candidates = [
        entry
        for entry in item["files"]
        if entry["arch"] in (arch, "wasm32") and entry["os"] in (os_name, "any")
    ]
    if not candidates:
        raise SystemExit(f"{item['id']} has no file for {os_name}/{arch}")
    return candidates[0]


def download(url: str, destination: Path) -> None:
    print(f"download {url}")
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)


def extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(target)
    elif "".join(archive.suffixes[-2:]) in (".tar.bz2", ".tar.gz"):
        with tarfile.open(archive) as bundle:
            bundle.extractall(target)
    else:
        shutil.copy2(archive, target / archive.name)


def private_data_tree(root: Path) -> None:
    """Remove group and other write bits; NLTK refuses a data path they can write."""
    for path in [root, *root.rglob("*")]:
        path.chmod(0o700 if path.is_dir() else 0o644)


def archive_ready(archive: Path, target: Path) -> bool:
    """True when every member of the zip is already extracted at its recorded size."""
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                parts = Path(info.filename).parts
                if Path(info.filename).is_absolute() or ".." in parts:
                    return False
                member = target.joinpath(*parts)
                if not member.is_file() or member.stat().st_size != info.file_size:
                    return False
    except (zipfile.BadZipFile, OSError):
        return False
    return True


def extract_item(item: dict, entry: dict, archive: Path, root: Path) -> None:
    installed = root / item["install_path"]
    if item["id"] == "ffmpeg":
        installed.mkdir(parents=True, exist_ok=True)
        binary = installed / entry["file"]
        with zipfile.ZipFile(archive) as wheel:
            with wheel.open(f"imageio_ffmpeg/binaries/{entry['file']}") as source:
                with binary.open("wb") as target:
                    shutil.copyfileobj(source, target)
        if entry["os"] != "windows":
            binary.chmod(binary.stat().st_mode | 0o111)
    elif entry["file"].endswith(".whl"):
        installed.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, installed / entry["file"])
    elif item["id"] == "deno":
        extract(archive, installed)
    else:
        extract(archive, root)


def make_executable(root: Path) -> None:
    if sys.platform == "win32":
        return
    binary = root / "deno" / "deno"
    if binary.is_file():
        binary.chmod(binary.stat().st_mode | 0o111)


def install(lock: dict, root: Path, *, force: bool) -> list[str]:
    root.mkdir(parents=True, exist_ok=True)
    journal_path = root / "installed.json"
    journal = json.loads(journal_path.read_text()) if journal_path.is_file() else {}
    prepared: list[str] = []
    os_name, arch = host_os(), host_arch()
    for item in lock["items"]:
        if item["id"].startswith(("model-", "package-")):
            continue
        entry = select_file(item, os_name, arch)
        installed = root / item["install_path"]
        previous = journal.get(item["id"])
        if (
            not force
            and installed.exists()
            and previous
            and previous.get("sha256") == entry["sha256"]
        ):
            print(f"verified {item['id']} {item['version']} (already installed)")
            prepared.append(item["id"])
            continue
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            archive = Path(temporary) / entry["file"]
            download(entry["url"], archive)
            actual = sha256(archive)
            if actual != entry["sha256"]:
                raise SystemExit(
                    f"sha256 mismatch for {entry['file']}: {actual} != {entry['sha256']}"
                )
            extract_item(item, entry, archive, root)
        make_executable(root)
        journal[item["id"]] = {
            "version": item["version"],
            "revision": item["revision"],
            "file": entry["file"],
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "install_path": item["install_path"],
        }
        scratch = root / "installed.json.tmp"
        scratch.write_text(json.dumps(journal, indent=2) + "\n")
        scratch.replace(journal_path)
        prepared.append(item["id"])
        print(f"installed {item['id']} {item['version']} at {installed}")
    return prepared


def model_path(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise SystemExit(f"model path escapes installation directory: {relative}")
    return path


def verified_file(path: Path, entry: dict) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == entry["bytes"]
        and sha256(path) == entry["sha256"]
    )


def prepare_file(entry: dict, destination: Path, *, force: bool) -> bool:
    if not force and verified_file(destination, entry):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        scratch = Path(temporary) / "download"
        download(entry["url"], scratch)
        if not verified_file(scratch, entry):
            raise SystemExit(f"bytes or sha256 mismatch for {entry['file']}")
        scratch.replace(destination)
    return True


def _write_journal(path: Path, journal: dict) -> None:
    with tempfile.TemporaryDirectory(dir=path.parent) as temporary:
        scratch = Path(temporary) / "journal.json"
        scratch.write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")
        scratch.replace(path)


def install_tts_package(lock: dict, root: Path, *, force: bool) -> list[str]:
    item = next(item for item in lock["items"] if item["id"] == "package-qwen-tts")
    entry = select_file(item, host_os(), host_arch())
    wheel = model_path(model_path(root, item["install_path"]), entry["file"])
    prepare_file(entry, wheel, force=force)
    journal_path = root / "packages.installed.json"
    journal = json.loads(journal_path.read_text()) if journal_path.is_file() else {}
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
            "--force-reinstall", "--disable-pip-version-check", str(wheel),
        ],
        check=True,
    )
    journal[item["id"]] = {
        "version": item["version"],
        "revision": item["revision"],
        "file": entry["file"],
        "sha256": entry["sha256"],
        "bytes": entry["bytes"],
        "install_path": item["install_path"],
        "python": sys.executable,
    }
    _write_journal(journal_path, journal)
    return [item["id"]]


def poetry_command() -> list[str]:
    """The Poetry command of this host: the executable or this interpreter's module."""
    found = shutil.which("poetry")
    return [found] if found else [sys.executable, "-m", "poetry"]


def poetry_environment() -> dict[str, str]:
    """Poetry's environment without the caller's active venv or Conda env.

    ``poetry run`` sets VIRTUAL_ENV. If Poetry inherits it, it installs every
    project into that one venv. Poetry also falls back to CONDA_PREFIX when the
    project has no registered environment, so a named Conda env would become the
    install target.
    """
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env.pop("CONDA_PREFIX", None)
    return env


def locked_versions(project: Path) -> dict[str, set[str]]:
    """Every version of every package in the project's poetry.lock."""
    lock = tomllib.loads((project / "poetry.lock").read_text(encoding="utf-8"))
    versions: dict[str, set[str]] = {}
    for package in lock.get("package", []):
        versions.setdefault(package["name"], set()).add(package["version"])
    return versions


def direct_requirements(project: Path) -> list[str]:
    """Distribution names of the project's direct dependencies."""
    data = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    names = {
        re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].strip()
        for requirement in data["project"].get("dependencies", [])
    }
    return sorted(name for name in names if name)


def distribution_name(name: str) -> str:
    """A distribution name normalized the way pip compares names."""
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_packages(project: Path, group: str) -> set[str]:
    """Distribution names the lock selects for one dependency group."""
    lock = tomllib.loads((project / "poetry.lock").read_text(encoding="utf-8"))
    return {
        distribution_name(package["name"])
        for package in lock.get("package", [])
        if group in package.get("groups", [])
    }


def in_project_python(project: Path) -> Path:
    """The interpreter path of the project's in-project environment."""
    binary = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return project / ".venv" / binary


def existing_environment_python(project: Path) -> Path | None:
    """The interpreter of one existing Poetry environment of the project."""
    in_project = in_project_python(project)
    if in_project.is_file():
        return in_project
    completed = subprocess.run(
        [*poetry_command(), "env", "list", "--full-path"],
        cwd=project,
        env=poetry_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        return None
    paths = set()
    for line in completed.stdout.splitlines():
        line = re.sub(r"\s+\(Activated\)$", "", line.strip())
        if not line:
            continue
        python = Path(line) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if python.is_file():
            paths.add(python)
    return paths.pop() if len(paths) == 1 else None


def environment_python(project: Path) -> Path:
    """The interpreter of the Poetry environment of the project."""
    python = existing_environment_python(project)
    if python is None:
        raise SystemExit(f"poetry created no environment for {project.name}")
    return python


def installed_packages(python: Path) -> set[str]:
    """Distribution names installed in the environment."""
    completed = subprocess.run(
        [str(python), "-c", INSTALLED_PACKAGES],
        capture_output=True,
        text=True,
        check=True,
    )
    return {name.lower() for name in json.loads(completed.stdout)}


def packages_to_remove(installed: set[str], project: Path) -> list[str]:
    """Installed packages the aligner's main group does not select."""
    keep = locked_packages(project, "main") | {
        distribution_name(name) for name in ("pip", "setuptools", "wheel", "whisperx")
    }
    return sorted(name for name in installed if distribution_name(name) not in keep)


def remove_unused_packages(project: Path, python: Path) -> None:
    """Remove installed packages the aligner's main group does not select."""
    extras = packages_to_remove(installed_packages(python), project)
    if not extras:
        return
    print(f"removing {len(extras)} packages the alignment path does not use")
    subprocess.run([str(python), "-m", "pip", "uninstall", "-y", *extras], check=True)


def verify_environment(python: Path, project: Path) -> None:
    """Check every direct dependency at the version the project's lock names."""
    locked = locked_versions(project)
    expected = {}
    for name in direct_requirements(project):
        versions = locked.get(name)
        if not versions:
            raise SystemExit(f"{project.name} lock has no version for {name}")
        expected[name] = sorted(versions)
    completed = subprocess.run(
        [str(python), "-c", CHECK_ENVIRONMENT, json.dumps(expected)],
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stdout.strip() or completed.stderr.strip()
        raise SystemExit(f"{project.name} environment does not match its poetry.lock: {detail}")
    print(f"verified {project.name} environment at {python}")


def install_environment(project: Path, *, in_project: bool | None = None) -> None:
    """Install the project into its own Poetry environment."""
    env = poetry_environment()
    if in_project is not None:
        env["POETRY_VIRTUALENVS_IN_PROJECT"] = "true" if in_project else "false"
    subprocess.run(
        [*poetry_command(), "install", "--no-root"],
        cwd=project,
        env=env,
        check=True,
    )


def install_pinned_wheel(project: Path, python: Path) -> None:
    """Install the wheel the project pins outside its lock into its environment."""
    subprocess.run([str(python), str(project / "install_whisperx.py")], check=True)


def install_environments() -> list[str]:
    """Install both Poetry projects and verify their direct dependency versions."""
    prepared = []
    for name, project in PROJECTS:
        if name == "align":
            existing = existing_environment_python(project)
            in_project = existing is None or existing == in_project_python(project)
            install_environment(project, in_project=in_project)
            python = existing_environment_python(project)
            if python is None:
                raise SystemExit(f"poetry created no environment for {project.name}")
            remove_unused_packages(project, python)
            install_pinned_wheel(project, python)
        else:
            install_environment(project)
            python = environment_python(project)
        verify_environment(python, project)
        prepared.append(f"env-{name}")
    return prepared


def install_models(lock: dict, root: Path, *, force: bool) -> list[str]:
    root.mkdir(parents=True, exist_ok=True)
    journal_path = root / "installed.json"
    journal = json.loads(journal_path.read_text()) if journal_path.is_file() else {}
    prepared: list[str] = []
    downloads = 0
    for item in lock["items"]:
        if not item["id"].startswith("model-"):
            continue
        installed = model_path(root, item["install_path"])
        for entry in item["files"]:
            destination = model_path(installed, entry["file"])
            changed = prepare_file(entry, destination, force=force)
            downloads += changed
            if entry["file"].endswith(".zip"):
                if changed or not archive_ready(destination, installed):
                    extract(destination, installed)
                if installed.parent != root:
                    private_data_tree(installed.parent)
        journal[item["id"]] = {
            "version": item["version"],
            "revision": item["revision"],
            "install_path": item["install_path"],
            "files": {
                entry["file"]: {"bytes": entry["bytes"], "sha256": entry["sha256"]}
                for entry in item["files"]
            },
        }
        _write_journal(journal_path, journal)
        prepared.append(item["id"])
        print(f"verified {item['id']} {item['version']} at {installed}")
    print(f"model downloads: {downloads}")
    return prepared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtime", action="store_true", help="download and verify runtime files")
    parser.add_argument(
        "--models",
        action="store_true",
        help="install both Poetry environments and download and verify model files",
    )
    parser.add_argument(
        "--tts-package", action="store_true", help="install the inference wheel only"
    )
    parser.add_argument("--force", action="store_true", help="download again even when verified")
    args = parser.parse_args(argv)
    if not (args.runtime or args.models or args.tts_package):
        parser.error("pass --runtime, --models or --tts-package")
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    prepared = []
    if args.runtime:
        prepared.extend(install(lock, runtime_root(), force=args.force))
    if args.models or args.tts_package:
        prepared.extend(install_tts_package(lock, runtime_root(), force=args.force))
    if args.models:
        prepared.extend(install_environments())
        prepared.extend(install_models(lock, model_root(), force=args.force))
    print("prepared: " + ", ".join(prepared))
    return 0


if __name__ == "__main__":
    sys.exit(main())
