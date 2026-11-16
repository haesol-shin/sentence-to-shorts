#!/usr/bin/env python3
"""Prepare pinned runtimes, speech inference wheels and model files.

    python scripts/dev_setup.py --runtime
    python scripts/dev_setup.py --models
    python scripts/dev_setup.py --tts-package

Runtime files go to APP_RUNTIME_DIR (default: <repo>/.local/rt); model files go
to APP_MODEL_DIR (default: <repo>/.local/models). Model item IDs start with
``model-`` and their files are installed verbatim, never extracted. Model and
wheel entries do not depend on the host and carry arch ``wasm32``, the lock's
marker for a file that fits every host. The application's runtime preparer skips
``model-`` and ``package-`` items, so this script is the only place that installs them.
core/config/runtime.lock.json is the only source of versions and hashes.
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
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "core" / "config" / "runtime.lock.json"


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
            downloads += prepare_file(entry, destination, force=force)
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
    parser.add_argument("--models", action="store_true", help="download and verify model files")
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
        prepared.extend(install_models(lock, model_root(), force=args.force))
    print("prepared: " + ", ".join(prepared))
    return 0


if __name__ == "__main__":
    sys.exit(main())
