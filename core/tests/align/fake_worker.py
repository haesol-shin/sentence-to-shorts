"""Stand-in for the aligner worker process, speaking the same line protocol.

`--mode` picks the behavior and `--log` appends one JSON line per event, with the
worker's pid, so a test can tell workers apart and check that they are gone. Only
the standard library is used, so the process starts in milliseconds.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def words(text: str, mode: str) -> list[dict]:
    tokens = text.split()
    low = set(os.environ.get("FAKE_LOW_WORDS", "").split(","))
    rows = []
    for index, token in enumerate(tokens):
        score = 0.0 if mode == "low" or token in low else 0.9
        start = round(index * 0.25, 3)
        end = round(index * 0.25 + 0.2, 3)
        if mode == "unordered" and index == 1:
            start, end = 0.0, 0.1
        if mode == "missing_time" and index == 0:
            start = None
        rows.append({"word": token, "start": start, "end": end, "score": score})
    if mode == "no_words":
        return []
    return rows


def respond(request: dict, args: argparse.Namespace, served: int, log) -> dict | None:
    """One reply, or None when the worker leaves instead of answering."""
    log("request", text=request["speech_text"], language=request["language"])
    if (
        args.mode == "bye_once"
        and served == 1
        and not os.path.exists(args.log + ".done")
    ):
        if args.log:
            open(args.log + ".done", "w").close()
        return {"type": "bye"}
    if args.mode == "hang":
        time.sleep(600)
    if args.mode == "grandchild":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        Path(args.pid_file).write_text(f"{os.getpid()} {child.pid}")
        time.sleep(600)
    if args.mode == "crash":
        os._exit(3)
    if args.mode == "model_load":
        return {"type": "error", "id": request["id"], "code": "model_load"}
    if args.mode == "align_error":
        return {"type": "error", "id": request["id"], "code": "align_failed"}
    if args.mode == "protocol":
        return {"type": "protocol"}
    reply = {
        "type": "words",
        "id": request["id"],
        "words": words(request["speech_text"], args.mode),
    }
    if args.mode == "wrong_id":
        reply["id"] = request["id"] + 1
    return reply


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="ok")
    parser.add_argument("--log", default="")
    parser.add_argument("--pid-file", default="")
    parser.add_argument("--model-ko")
    parser.add_argument("--model-en")
    parser.add_argument("--model-en-file")
    parser.add_argument("--nltk-data")
    parser.add_argument("--threads", default="1")
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
        nltk=os.environ.get("NLTK_DATA"),
        pythonpath=os.environ.get("PYTHONPATH"),
        nousersite=os.environ.get("PYTHONNOUSERSITE"),
    )
    if args.mode == "start_error":
        send({"type": "error", "code": "model_load"})
        return 1
    send({"type": "ready"})
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
        reply = respond(request, args, served, log)
        if reply is None:
            return 0
        if reply.get("type") == "protocol":
            sys.stdout.write("not json\n")
            sys.stdout.flush()
            continue
        send(reply)


if __name__ == "__main__":
    sys.exit(main())
