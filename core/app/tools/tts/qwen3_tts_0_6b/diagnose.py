"""Run the installed TTS worker by hand and write what the adapter drops to a JSON file.

    <bundled python> diagnose.py --root <install folder> --out report.json

The release smoke runs this when a voice check ends in `tts_timeout` or `tts_failed`. The
adapter keeps no worker stderr, so a worker that never reports a load phase leaves no
trace. This script starts the worker with the argv and environment the adapter builds
(`Qwen3TtsAdapter.worker_launch`), reads its protocol lines with their times, keeps the
exit status and the stderr tail, and times `python -X importtime -c "import torch"` with the
same interpreter and environment. It is for CI only: it uses no user text, and the report
goes to the smoke artifact, never to a user log. The caller gives the environment the
launcher gives the app (`APP_MAIN_SITE`, `APP_RUNTIME_DIR`).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

WORKER_LIMIT_S = 600.0
"""How long the worker may take to report `ready`; longer than the adapter's phase limit."""
IMPORT_LIMIT_S = 600.0
STDERR_TAIL_BYTES = 4000
MAX_LINES = 50
MAX_LINE_CHARS = 300
SLOWEST = 5
IMPORT_PREFIX = "import time:"


def parse_importtime(text: str) -> dict[str, Any]:
    """Total and the slowest imports from `-X importtime` output, by their own time."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith(IMPORT_PREFIX):
            continue
        parts = [part.strip() for part in line[len(IMPORT_PREFIX):].split("|", 2)]
        if len(parts) != 3 or not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        rows.append({"module": parts[2], "self_us": int(parts[0]), "cumulative_us": int(parts[1])})
    slowest = sorted(rows, key=lambda row: row["self_us"], reverse=True)[:SLOWEST]
    return {"total_ms": round(sum(row["self_us"] for row in rows) / 1000, 1), "slowest": slowest}


def time_import_torch(
    python: str, env: Mapping[str, str], limit_s: float = IMPORT_LIMIT_S
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        done = subprocess.run(
            [python, "-X", "importtime", "-c", "import torch"],
            env=dict(env), capture_output=True, check=False, timeout=limit_s,
        )
    except subprocess.TimeoutExpired:
        return {"returncode": None, "seconds": round(time.monotonic() - started, 1),
                "timed_out": True}
    report = parse_importtime(done.stderr.decode("utf-8", "replace"))
    return {"returncode": done.returncode, "seconds": round(time.monotonic() - started, 1),
            "timed_out": False, **report}


def run_worker(
    argv: Sequence[str], env: Mapping[str, str], limit_s: float = WORKER_LIMIT_S
) -> dict[str, Any]:
    """Start the worker like the adapter does and watch it until `ready`, exit or the limit."""
    kwargs: dict[str, Any] = {
        "env": dict(env), "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    process = subprocess.Popen(list(argv), **kwargs)
    lines: list[dict[str, Any]] = []
    tail: deque[bytes] = deque()
    tail_size = 0
    ready = threading.Event()
    ended = threading.Event()
    lock = threading.Lock()

    def read_stdout() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            text = raw.decode("utf-8", "replace").rstrip()
            with lock:
                lines.append({"at": round(time.monotonic() - started, 1), "text": text})
            if '"type":"ready"' in text.replace(" ", ""):
                ready.set()
        ended.set()

    def read_stderr() -> None:
        nonlocal tail_size
        assert process.stderr is not None
        while chunk := process.stderr.read1(4096):
            with lock:
                tail.append(chunk)
                tail_size += len(chunk)
                while tail_size - len(tail[0]) >= STDERR_TAIL_BYTES:
                    tail_size -= len(tail.popleft())

    threads = [threading.Thread(target=read_stdout, daemon=True),
               threading.Thread(target=read_stderr, daemon=True)]
    for thread in threads:
        thread.start()
    deadline = started + limit_s
    while time.monotonic() < deadline and process.poll() is None and not ready.is_set():
        time.sleep(0.1)
    timed_out = process.poll() is None and not ready.is_set()
    reached_ready = ready.is_set()
    if process.poll() is None:
        process.kill()
    returncode = process.wait()
    for thread in threads:
        thread.join(timeout=5)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    with lock:
        recorded = [
            {"at": line["at"], "text": line["text"][:MAX_LINE_CHARS]} for line in lines[:MAX_LINES]
        ]
        stderr = b"".join(tail)[-STDERR_TAIL_BYTES:].decode("utf-8", "replace")
    return {
        "ready": reached_ready,
        "timed_out": timed_out,
        "returncode": None if timed_out else returncode,
        "seconds": round(time.monotonic() - started, 1),
        "lines": recorded,
        "stderr_tail": stderr,
    }


def diagnose(
    argv: Sequence[str], env: Mapping[str, str], python: str,
    worker_limit_s: float = WORKER_LIMIT_S, import_limit_s: float = IMPORT_LIMIT_S,
) -> dict[str, Any]:
    return {
        "worker": run_worker(argv, env, worker_limit_s),
        "import_torch": time_import_torch(python, env, import_limit_s),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    for name in ("core", "site-packages"):
        folder = root / name
        if folder.is_dir():
            sys.path.insert(0, str(folder))
    try:
        from app.settings import Settings
        from app.tools.tts.qwen3_tts_0_6b.adapter import create

        adapter = create(Settings())
        launch_argv, launch_env = adapter.worker_launch()
        report = diagnose(launch_argv, launch_env, sys.executable)
    except Exception as error:  # noqa: BLE001 - the report must say what broke
        report = {"error": f"{type(error).__name__}: {str(error)[:300]}"}
    staged = args.out.with_name(args.out.name + ".tmp")
    staged.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staged.replace(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
