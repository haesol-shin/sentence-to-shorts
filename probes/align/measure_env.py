#!/usr/bin/env python3
"""Record installed versions, environment bytes and cached model bytes.

Runs inside the measured environment so the versions come from the same
packages the probe imported. Cache directories are grouped by model directory,
so the result holds model names and byte counts but no local paths.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

TRACKED = (
    "whisperx",
    "torch",
    "torchaudio",
    "torchcodec",
    "transformers",
    "faster-whisper",
    "ctranslate2",
    "pyannote-audio",
    "onnxruntime",
    "numpy",
)


def _directory_bytes(root: Path) -> int:
    total = 0
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if not (Path(current) / name).is_symlink()]
        for name in names:
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            total += path.stat().st_size
    return total


def _model_name(path: str) -> str | None:
    """Name a cached model, or None for cache bookkeeping files."""
    marker = "models--"
    if marker in path:
        tail = path.split(marker, 1)[1]
        return tail.split(os.sep, 1)[0].replace("--", "/")
    parts = Path(path).parts
    if "checkpoints" in parts:
        return Path(path).name
    return None


def _cache_bytes(roots: list[Path]) -> dict[str, int]:
    models: dict[str, int] = {}
    for root in roots:
        if not root.exists():
            continue
        for current, directories, names in os.walk(root, followlinks=False):
            directories[:] = [name for name in directories if not (Path(current) / name).is_symlink()]
            for name in names:
                path = Path(current) / name
                if path.is_symlink() or not path.is_file():
                    continue
                key = _model_name(str(path))
                if key is not None:
                    models[key] = models.get(key, 0) + path.stat().st_size
    return dict(sorted(models.items()))


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in TRACKED:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return versions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument("--cache", action="append", default=[], type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    models = _cache_bytes(args.cache)
    payload = {
        "schema": 1,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "release": platform.release(),
            "python": platform.python_version(),
            "python_build": platform.python_build()[0],
            "processors": os.cpu_count(),
        },
        "packages": _package_versions(),
        "environment_bytes": _directory_bytes(args.env),
        "model_cache_bytes": models,
        "model_cache_total_bytes": sum(models.values()),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"environment_bytes": payload["environment_bytes"], "models": len(payload["model_cache_bytes"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
