#!/usr/bin/env python3
"""Run one command with a wall-clock limit and a log file.

Used before a candidate environment exists, so it imports only the standard
library. On timeout the whole child process tree is killed and the exit code is
124, which the workflow records as a timeout result instead of a failed job.

Usage:
    python run_limited.py --timeout 1800 --log install.log -- python -m pip install ...
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

TIMEOUT_EXIT = 124


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            check=False,
            capture_output=True,
        )
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", required=True, type=float)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command after --")

    args.log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with args.log.open("wb") as log:
        kwargs: dict[str, object] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            log.write(
                (
                    f"\nrun_limited: command exceeded {args.timeout:g} seconds; "
                    "killing the process tree\n"
                ).encode()
            )
            log.flush()
            _kill_tree(process)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            code = TIMEOUT_EXIT
        elapsed = time.monotonic() - started
        log.write(f"\nrun_limited: exit {code} after {elapsed:.1f} seconds\n".encode())
    return code if code >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
