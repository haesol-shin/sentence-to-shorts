#!/usr/bin/env python3
"""Install the pinned WhisperX wheel without its declared dependencies.

Run inside the aligner environment:

    python install_whisperx.py

WhisperX 3.8.6 declares pyannote-audio, torchvision, torchcodec and triton.
Its alignment module imports none of them, so this script verifies the wheel
against ``whisperx.lock.json`` and the ``poetry.lock`` hash and installs it with
``pip --no-deps``, then deletes the VAD model file the wheel ships. The Poetry
main group carries the packages the alignment module imports; the optional
``audit`` group keeps WhisperX's declared packages in the lock for dependency
review without installing them.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from importlib import metadata, util
from pathlib import Path

PIN = Path(__file__).resolve().with_name("whisperx.lock.json")
LOCK = Path(__file__).resolve().with_name("poetry.lock")
NAME = "whisperx"
UNUSED = ("pyannote", "torchcodec", "torchvision", "triton")
# Locked packages the alignment path never imports: torch's optional graph
# helper and Hugging Face's optional transfer client. The dev setup and the
# bundle build remove them from the aligner environment after the lock installs.
PRUNED = ("hf-xet", "networkx")
# The wheel ships a VAD model. Alignment models come through the model
# download, so this file is never read.
MODEL_FILE = Path("whisperx") / "assets" / "pytorch_model.bin"


def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def verified(path: Path, pin: dict) -> bool:
    """True when the file has the pinned byte count and SHA-256."""
    return path.is_file() and path.stat().st_size == pin["bytes"] and sha256(path) == pin["sha256"]


def pinned() -> dict:
    """The wheel from the pin with the version and hash from the Poetry lock."""
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    package = next((item for item in lock["package"] if item["name"] == NAME), None)
    if package is None:
        raise SystemExit(f"{LOCK.name} has no {NAME} entry")
    filename = pin["url"].rsplit("/", 1)[-1]
    hashes = [
        str(entry["hash"]).removeprefix("sha256:")
        for entry in package.get("files", [])
        if entry.get("file") == filename
        and str(entry.get("hash", "")).startswith("sha256:")
    ]
    if len(hashes) != 1:
        raise SystemExit(f"{LOCK.name} has no unique wheel hash for {filename}")
    return {
        "name": NAME,
        "version": package["version"],
        "url": pin["url"],
        "bytes": pin["bytes"],
        "sha256": hashes[0],
    }


def installed_version() -> str | None:
    try:
        return metadata.version("whisperx")
    except metadata.PackageNotFoundError:
        return None


def alignment_import_error() -> str | None:
    """The original error when ``whisperx.alignment`` does not import."""
    try:
        importlib.import_module("whisperx.alignment")
    except Exception as error:  # any import failure means the install is unusable
        return f"{type(error).__name__}: {error}"
    return None


def unused_packages() -> list[str]:
    """Packages the alignment path does not import but WhisperX metadata declares."""
    return [name for name in UNUSED if util.find_spec(name) is not None]


def remove_model_file(site: Path) -> None:
    """Delete the VAD model the wheel ships from the folder that holds ``whisperx``."""
    (site / MODEL_FILE).unlink(missing_ok=True)


def installed_site() -> Path | None:
    """The folder that holds the installed ``whisperx`` package."""
    spec = util.find_spec("whisperx")
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).parent.parent


def drop_model_file() -> None:
    site = installed_site()
    if site is not None:
        remove_model_file(site)


def download(url: str, destination: Path) -> None:
    print(f"download {url}")
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report an environment that holds packages the alignment path does not import",
    )
    args = parser.parse_args(argv)
    pin = pinned()
    extras = unused_packages()
    if extras:
        print(f"the aligner environment holds unused packages: {', '.join(extras)}")
        if args.check:
            return 2
        print("remove the unused packages, then run this script again")
        return 1
    if args.check:
        return 0
    if installed_version() == pin["version"]:
        error = alignment_import_error()
        if error is None:
            drop_model_file()
            print(f"verified {pin['name']} {pin['version']}")
            return 0
        print(
            f"installed {pin['name']} {pin['version']} does not import "
            f"its alignment module: {error}"
        )
    with tempfile.TemporaryDirectory(prefix="whisperx-") as temporary:
        wheel = Path(temporary) / pin["url"].rsplit("/", 1)[-1]
        download(pin["url"], wheel)
        if not verified(wheel, pin):
            print(f"bytes or sha256 mismatch for {wheel.name}")
            return 1
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
                "--force-reinstall", "--disable-pip-version-check", str(wheel),
            ],
            check=True,
        )
    drop_model_file()
    error = alignment_import_error()
    if installed_version() != pin["version"] or error is not None:
        if error is not None:
            print(
                f"{pin['name']} {pin['version']} does not import its alignment "
                f"module after the install: {error}"
            )
        else:
            print(f"{pin['name']} {pin['version']} is not usable after the install")
        return 1
    print(f"installed {pin['name']} {pin['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
