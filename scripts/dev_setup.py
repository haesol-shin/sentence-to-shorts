#!/usr/bin/env python3
"""Download the pinned Deno and Pyodide runtime files and verify their SHA-256.

    python scripts/dev_setup.py --runtime

Files go to APP_RUNTIME_DIR (default: <repo>/.local/rt). The lock file
core/config/runtime.lock.json is the only source of versions and hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtime", action="store_true", help="download and verify runtime files")
    parser.add_argument("--force", action="store_true", help="download again even when verified")
    args = parser.parse_args(argv)
    if not args.runtime:
        parser.error("pass --runtime")
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    prepared = install(lock, runtime_root(), force=args.force)
    print("prepared: " + ", ".join(prepared))
    return 0


if __name__ == "__main__":
    sys.exit(main())
