#!/usr/bin/env python3
"""Write a result for a setup failure that happened before synthesis.

An install failure is a result of the candidate environment, not a harness
error: the workflow keeps going, uploads this file and ends successfully.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import SCHEMA_VERSION, host_info  # noqa: E402

TAIL_LINES = 80
TAIL_CHARS = 6000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--code", default=None)
    parser.add_argument("--log", default=None, type=Path)
    parser.add_argument("--seconds", default=None, type=float)
    args = parser.parse_args(argv)
    message = "setup failed"
    if args.log is not None and args.log.is_file():
        lines = args.log.read_text(encoding="utf-8", errors="replace").splitlines()
        message = "\n".join(lines[-TAIL_LINES:])[-TAIL_CHARS:]
    payload = {
        "schema": SCHEMA_VERSION,
        "candidate": args.candidate,
        "status": "failed",
        "failure": {
            "stage": args.stage,
            "code": args.code or f"{args.stage}_failed",
            "message": message,
            "seconds": args.seconds,
        },
        "host": host_info(),
        "cold_start_ms": None,
        "first_wav_ms": None,
        "rtf": None,
        "peak_rss_bytes": None,
        "texts": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["failure"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
