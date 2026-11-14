#!/usr/bin/env python3
"""Download the model snapshots named in a candidate ``models.json``.

Every entry carries a full revision, so a rerun fetches the same files. The
download happens before the measured process starts; nothing here is timed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from huggingface_hub import snapshot_download


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    args.root.mkdir(parents=True, exist_ok=True)
    for entry in spec["models"]:
        target = args.root / entry["local_dir"]
        target.mkdir(parents=True, exist_ok=True)
        print(f"downloading {entry['repo_id']} at {entry['revision']} into {target}")
        snapshot_download(
            repo_id=entry["repo_id"],
            revision=entry["revision"],
            local_dir=str(target),
            allow_patterns=entry.get("allow_patterns"),
            max_workers=8,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
