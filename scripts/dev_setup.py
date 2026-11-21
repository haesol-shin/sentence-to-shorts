#!/usr/bin/env python3
"""Prepare pinned runtimes, speech inference wheels and model files.

    python scripts/dev_setup.py --runtime
    python scripts/dev_setup.py --models
    python scripts/dev_setup.py --tts-package

Runtime files go to APP_RUNTIME_DIR (default: <repo>/.local/rt); model files go
to APP_MODEL_DIR (default: <repo>/.local/models). Model item IDs start with
``model-``. The models are prepared by the application's own function
``app.runtime.models.prepare_models``, the one the installed app runs in the
background, so an item has one way to be installed: Hugging Face files through
the official client, other files through the resumable downloader, each checked
against the locked size and SHA-256. A model file that is a ``.zip`` stays in
place and its members are extracted beside it, so NLTK reads its data
directory. core/config/runtime.lock.json is the only source of versions and
hashes.

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
under APP_RUNTIME_DIR by ``app.runtime.prepare.write_package_record``, including
the Python environment used for installation. ``--force`` downloads the runtime
files and the inference wheel again; a model file is replaced when it fails its
size or hash, so delete one to fetch it again.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
    elif entry["file"].endswith((".zip", ".tar.bz2", ".tar.gz")):
        extract(archive, root)
    else:
        installed.mkdir(parents=True, exist_ok=True)
        binary = installed / entry["file"]
        shutil.copy2(archive, binary)
        if entry["os"] != "windows":
            binary.chmod(binary.stat().st_mode | 0o111)


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


def install_tts_package(lock: dict, root: Path, *, force: bool) -> list[str]:
    app_error, models, prepare = app_modules()
    item = next(item for item in lock["items"] if item["id"] == "package-qwen-tts")
    entry = select_file(item, host_os(), host_arch())
    from app.runtime import archive
    from app.runtime.lock import relative_install_path

    wheel = root.joinpath(*relative_install_path(item).parts, *archive.safe_parts(entry["file"]))
    if force:
        wheel.unlink(missing_ok=True)
    try:
        models.fetch_locked_file(
            entry, wheel, staging=root / ".tmp", cancel=NeverCancelled()
        )
    except app_error as error:
        raise SystemExit(f"wheel download failed: {error.code} {error.detail}") from error
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
            "--force-reinstall", "--disable-pip-version-check", str(wheel),
        ],
        check=True,
    )
    prepare.write_package_record(root, item, entry)
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


def aligner_installer(project: Path):  # type: ignore[no-untyped-def]
    """The aligner's install script, the one source of the packages it prunes."""
    spec = importlib.util.spec_from_file_location(
        "align_install_whisperx", project / "install_whisperx.py"
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"{project.name}/install_whisperx.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def packages_to_remove(installed: set[str], project: Path) -> list[str]:
    """Installed packages the aligner's main group does not select, and the pruned ones."""
    pruned = {distribution_name(name) for name in aligner_installer(project).PRUNED}
    keep = (locked_packages(project, "main") - pruned) | {
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


class NeverCancelled:
    """The cancel token of a script nobody can cancel from outside."""

    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


def app_modules():  # type: ignore[no-untyped-def]
    """The application's runtime modules. This script runs in the application's environment."""
    core = str(ROOT / "core")
    if core not in sys.path:
        sys.path.insert(0, core)
    import importlib

    from app.ports import AppError

    # `app.runtime` re-exports a function named `prepare`, so the module is imported by name.
    return (
        AppError,
        importlib.import_module("app.runtime.models"),
        importlib.import_module("app.runtime.prepare"),
    )


def install_models(lock: dict, root: Path) -> list[str]:
    """Prepare every model item with the function the installed app uses."""
    app_error, models, prepare = app_modules()
    items = [item for item in lock["items"] if item["id"].startswith("model-")]
    shown = [-1]

    def progress(done: int, total: int) -> None:
        percent = done * 100 // total if total else 100
        if percent // 10 != shown[0]:
            shown[0] = percent // 10
            print(f"models {percent}% ({done >> 20} of {total >> 20} MiB)", flush=True)

    try:
        prepared = models.prepare_models(
            root, items, cancel=NeverCancelled(), hooks=prepare.Hooks(progress=progress)
        )
    except app_error as error:
        raise SystemExit(f"model preparation failed: {error.code} {error.detail}") from error
    for name in prepared:
        print(f"verified {name} at {root}")
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="download the runtime files and the inference wheel again even when verified",
    )
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
        prepared.extend(install_models(lock, model_root()))
    print("prepared: " + ", ".join(prepared))
    return 0


if __name__ == "__main__":
    sys.exit(main())
