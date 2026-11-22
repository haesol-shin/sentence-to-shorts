"""Stand-in for the TTS worker process, speaking the same line protocol.

`--mode` picks the behavior; `--log` appends one JSON line per event, with the
worker's pid, so a test can tell workers apart and check that they are gone.
Only the standard library is used, so the process starts in milliseconds.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path


def tone(path: str, ms: int = 500, rate: int = 24000, truncate: bool = False) -> None:
    frames = rate * ms // 1000
    data = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate))) for i in range(frames)
    )
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data)
    if truncate:
        with open(path, "r+b") as raw:
            raw.truncate(raw.seek(0, 2) // 2)


PHASES = ("import_torch", "import_qwen_tts", "from_pretrained", "warm_up")
PHASE_GAP_S = 0.7


def report_phases(mode: str, send) -> None:
    """The load-phase modes: slow but steady, silent after two phases, never finishing."""
    if mode == "phased_load":
        for name in PHASES:
            time.sleep(PHASE_GAP_S)
            send({"type": "phase", "name": name, "seconds": PHASE_GAP_S})
    if mode == "stall_after_phase":
        send({"type": "phase", "name": "import_torch", "seconds": 0.1})
        send({"type": "phase", "name": "import_qwen_tts", "seconds": 0.1})
        time.sleep(600)
    if mode == "endless_phases":
        while True:
            time.sleep(PHASE_GAP_S)
            send({"type": "phase", "name": "from_pretrained", "seconds": PHASE_GAP_S})


def deaf(args: argparse.Namespace) -> None:
    """The mode that is ready but never takes a request off the pipe."""
    if args.mode == "deaf":
        time.sleep(600)


def respond(args: argparse.Namespace, request: dict, served: int, send) -> bool:
    """Answer one request by mode; False when the worker leaves instead of answering."""
    if args.mode == "bye_once" and served == 1 and not os.path.exists(args.log + ".done"):
        open(args.log + ".done", "w").close()
        send({"type": "bye"})
        return False
    if args.mode == "no_write_after_one" and served > 1:
        send({"type": "done", "id": request["id"], "sample_rate": 24000})
        return True
    if args.mode == "fail_after_one" and served > 1:
        send({"type": "error", "id": request["id"], "code": "synth_failed"})
        return True
    if args.mode == "slow_synth":
        time.sleep(1.5)
    if args.mode == "hang":
        time.sleep(600)
    if args.mode == "grandchild":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        Path(args.pid_file).write_text(f"{os.getpid()} {child.pid}")
        time.sleep(600)
    if args.mode == "crash":
        os._exit(3)
    if args.mode == "synth_error":
        send({"type": "error", "id": request["id"], "code": "synth_failed", "name": "KeyError"})
        return True
    if args.mode == "synth_error_on_cuda" and args.device == "cuda":
        send({"type": "error", "id": request["id"], "code": "synth_failed", "name": "RuntimeError"})
        return True
    rate = 22050 if args.mode == "wrong_rate" else 24000
    tone(request["out"], rate=rate, truncate=args.mode == "truncated")
    send({"type": "done", "id": request["id"], "sample_rate": rate})
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="ok")
    parser.add_argument("--log", default="")
    parser.add_argument("--pid-file", default="")
    parser.add_argument("--model-dir")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threads")
    parser.add_argument("--idle-s", type=float, default=120.0)
    args = parser.parse_args()

    def log(event: str, **extra: object) -> None:
        if args.log:
            with open(args.log, "a", encoding="ascii") as handle:
                handle.write(json.dumps({"pid": os.getpid(), "event": event, **extra}) + "\n")

    def send(message: dict) -> None:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    requests: queue.Queue = queue.Queue()

    def read() -> None:
        for line in sys.stdin:
            requests.put(json.loads(line))
        requests.put(None)

    threading.Thread(target=read, daemon=True).start()
    log(
        "start",
        mode=args.mode,
        threads=args.threads,
        device=args.device,
        pythonpath=os.environ.get("PYTHONPATH"),
        nousersite=os.environ.get("PYTHONNOUSERSITE"),
    )
    if args.mode == "crash_on_cuda" and args.device == "cuda":
        os._exit(3)
    if args.mode == "no_package":
        send({"type": "error", "code": "package_missing"})
        return 1
    if args.mode == "load_error":
        send({"type": "error", "code": "load_failed", "name": "OSError"})
        return 1
    if args.mode == "slow_load":
        time.sleep(600)
    report_phases(args.mode, send)
    if args.mode == "slow_load_on_cuda" and args.device == "cuda":
        time.sleep(600)
    send({"type": "ready"})
    deaf(args)
    served = 0
    while True:
        try:
            request = requests.get(timeout=args.idle_s)
        except queue.Empty:
            send({"type": "bye"})
            log("idle_exit")
            return 0
        if request is None:
            return 0
        served += 1
        send({"type": "received", "id": request["id"]})
        log("request", text=request["text"], speaker=request["speaker"], seed=request["seed"])
        if not respond(args, request, served, send):
            return 0


if __name__ == "__main__":
    sys.exit(main())
