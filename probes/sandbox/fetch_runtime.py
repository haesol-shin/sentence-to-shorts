#!/usr/bin/env python3
"""Fetch the pinned Deno and Pyodide files, verify their SHA-256, and unpack them.

The probe downloads official release files directly, so its pins are independent
of any other lockfile. A hash mismatch stops the run before the sandbox starts.

Run it with the runtime manifest next to this file:
    python probes/sandbox/fetch_runtime.py --dest <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

MANIFEST = Path(__file__).with_name("runtime.json")
CHUNK = 1 << 20
DOWNLOAD_TIMEOUT = 300


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def host_platform(explicit: str) -> str:
    if explicit != "auto":
        return explicit
    return "windows" if sys.platform == "win32" else "linux"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path, expected: str) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "sandbox-probe/1"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        with target.open("wb") as handle:
            shutil.copyfileobj(response, handle, CHUNK)
    found = sha256_file(target)
    if found != expected:
        raise SystemExit(f"hash mismatch for {target.name}: expected {expected}, found {found}")
    return found


def safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for member in archive.getmembers():
        name = member.name
        if name.startswith("/") or ".." in Path(name).parts:
            raise SystemExit(f"unsafe archive member: {name!r}")
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"non-regular archive member: {name!r}")
        members.append(member)
    return members


def extract_pyodide(archive_path: Path, dest: Path) -> None:
    with tarfile.open(archive_path, "r:bz2") as archive:
        members = safe_members(archive)
        try:
            archive.extractall(dest, members=members, filter="fully_trusted")
        except TypeError:  # Python < 3.12 has no extraction filters.
            archive.extractall(dest, members=members)


def extract_deno(archive_path: Path, dest: Path, binary: str) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if names != [binary]:
            raise SystemExit(f"unexpected deno archive members: {names}")
        target = dest / binary
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(binary) as source, target.open("wb") as handle:
            shutil.copyfileobj(source, handle, CHUNK)
    if os.name == "posix":
        target.chmod(0o755)
    return target


def verify_deno(binary: Path, version: str) -> str:
    env = dict(os.environ)
    env.setdefault("DENO_NO_UPDATE_CHECK", "1")
    done = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, timeout=60, env=env
    )
    first_line = (done.stdout or done.stderr).splitlines()[0] if (done.stdout or done.stderr) else ""
    if done.returncode != 0:
        raise SystemExit(f"deno --version failed: {first_line}")
    if first_line.split()[1:2] != [version]:
        raise SystemExit(f"deno version mismatch: expected {version}, found {first_line}")
    return first_line.strip()


def fetch(dest: Path, platform: str) -> dict:
    manifest = load_manifest()
    dest.mkdir(parents=True, exist_ok=True)
    downloads = Path(tempfile.mkdtemp(prefix="probe-download-", dir=dest))
    verified: dict[str, str] = {}
    try:
        deno_entry = manifest["deno"]["archives"][platform]
        deno_archive = downloads / deno_entry["file"]
        verified[deno_entry["file"]] = download(deno_entry["url"], deno_archive, deno_entry["sha256"])
        deno_binary = extract_deno(deno_archive, dest / "deno", manifest["deno"]["binary"][platform])
        deno_version = verify_deno(deno_binary, manifest["deno"]["version"])

        pyodide_entry = manifest["pyodide"]["archive"]
        pyodide_archive = downloads / pyodide_entry["file"]
        verified[pyodide_entry["file"]] = download(
            pyodide_entry["url"], pyodide_archive, pyodide_entry["sha256"]
        )
        extract_pyodide(pyodide_archive, dest)

        for package in manifest["packages"]:
            target = dest / "pyodide" / package["file"]
            verified[package["file"]] = download(package["url"], target, package["sha256"])
    finally:
        shutil.rmtree(downloads, ignore_errors=True)

    summary = {
        "platform": platform,
        "deno": {"path": str(deno_binary), "version": deno_version},
        "pyodide": manifest["pyodide"]["version"],
        "verified": verified,
    }
    (dest / "runtime-verified.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, required=True)
    parser.add_argument("--platform", choices=("auto", "linux", "windows"), default="auto")
    args = parser.parse_args(argv)
    platform = host_platform(args.platform)
    summary = fetch(args.dest.resolve(), platform)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
