"""Run the installed TTS worker by hand and report what the adapter drops.

The release smoke calls this, in the installed interpreter, when a voice check ends in
`tts_timeout` or `tts_failed`. The adapter keeps no worker stderr, so a worker that never
reports a load phase leaves no trace. `diagnose` starts the worker with the argv and
environment the adapter builds (`Qwen3TtsAdapter.worker_launch`), reads its protocol lines
with their times, keeps the exit status and the stderr tail, and times
`python -X importtime -c "import torch"` with the same interpreter and environment. After
`ready` it writes one real synth request, when it is given one, and times three points: the
request written, the first reply byte and the answer. A worker that never answers shows no
first reply (the request did not cross the pipe or the worker is stuck before it reports it),
one that sends `received` and then nothing is stuck in the synthesis, and a late `done` is a
slow synthesis. It is for CI only: it uses no user text, and the report goes to the smoke
artifact, never to a user log.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.tools.tts.qwen3_tts_0_6b.adapter import LANGUAGES

WORKER_LIMIT_S = 600.0
"""How long the worker may take to report `ready`; longer than the adapter's phase limit."""
SYNTH_LIMIT_S = 240.0
"""How long the one request may take after `ready`: well above the adapter's sentence limit, so
a slow synthesis ends with its real duration and a hang ends at this limit."""
IMPORT_LIMIT_S = 600.0
STDERR_TAIL_BYTES = 4000
MAX_LINES = 50
MAX_LINE_CHARS = 300
SLOWEST = 5
IMPORT_PREFIX = "import time:"
SENTENCE = "안녕하세요. 오늘은 커피 고르는 법을 알려 드릴게요."
"""The line of the installed voice probe, so a diagnosis synthesizes what the probe did."""


def synth_request(manifest: Path, out: Path) -> dict[str, Any]:
    """The request the adapter sends for `SENTENCE` with the voice of `manifest`."""
    voice = json.loads(manifest.read_text(encoding="utf-8"))
    return {
        "text": SENTENCE, "language": LANGUAGES["ko"], "speaker": voice["speaker"],
        "seed": voice["settings"]["seed"], "speed": voice["settings"]["speed"], "out": str(out),
    }


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


def _note_reply(synth: dict[str, Any], kind: Any, at: float, text: str) -> bool:
    """Record a protocol line that arrives after the request was written; True at the answer."""
    if synth["written_at"] is None:
        return False
    if synth["first_reply_at"] is None:
        synth["first_reply_at"] = at
    if kind == "received":
        synth["received_at"] = at
    if kind in ("done", "error"):
        synth["done_at"], synth["answer"] = at, text[:MAX_LINE_CHARS]
        return True
    return False


def _run_request(
    process: subprocess.Popen[bytes], request: Mapping[str, Any], started: float,
    synth: dict[str, Any], lock: threading.Lock, answered: threading.Event, limit_s: float,
) -> bool:
    """Write the request to the worker's stdin the way the adapter does and wait for its answer.

    The write runs in its own thread: a pipe that blocks the write is a finding, not a reason
    to hang the diagnosis. `written_at` is taken before the write starts and `sent` is set when
    it returned. True when the limit passed without an answer or an exit.
    """
    line = json.dumps({"id": 1, **request}, ensure_ascii=True, separators=(",", ":")) + "\n"

    def write() -> None:
        try:
            assert process.stdin is not None
            process.stdin.write(line.encode("ascii"))
            process.stdin.flush()
        except (OSError, ValueError) as error:
            with lock:
                synth["write_error"] = type(error).__name__
            return
        with lock:
            synth["sent"] = True

    deadline = time.monotonic() + limit_s
    with lock:
        synth["written_at"] = round(time.monotonic() - started, 1)
    writer = threading.Thread(target=write, daemon=True)
    writer.start()
    writer.join(limit_s)
    with lock:
        if writer.is_alive():
            synth["write_error"] = "blocked"
        if not synth["sent"]:
            return False
    return not answered.wait(max(0.0, deadline - time.monotonic()))


def _popen_kwargs(env: Mapping[str, str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "env": dict(env), "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _close_streams(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def run_worker(
    argv: Sequence[str], env: Mapping[str, str], limit_s: float = WORKER_LIMIT_S,
    request: Mapping[str, Any] | None = None, synth_limit_s: float = SYNTH_LIMIT_S,
) -> dict[str, Any]:
    """Start the worker like the adapter does and watch it until `ready`, exit or the limit.

    With a `request` (the fields the adapter sends, without `id`), write it after `ready` and
    watch the worker until it answers, exits or `synth_limit_s` passes; `synth` holds the times.
    """
    started = time.monotonic()
    process = subprocess.Popen(list(argv), **_popen_kwargs(env))
    lines: list[dict[str, Any]] = []
    tail: deque[bytes] = deque()
    tail_size = 0
    ready = threading.Event()
    answered = threading.Event()
    lock = threading.Lock()
    synth: dict[str, Any] = {
        "sent": False, "written_at": None, "first_reply_at": None, "received_at": None,
        "done_at": None, "answer": None,
    }

    def read_stdout() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            at = round(time.monotonic() - started, 1)
            text = raw.decode("utf-8", "replace").rstrip()
            try:
                message = json.loads(text)
            except ValueError:
                message = None
            kind = message.get("type") if isinstance(message, dict) else None
            with lock:
                lines.append({"at": at, "text": text})
                if _note_reply(synth, kind, at, text):
                    answered.set()
            if kind == "ready":
                ready.set()
        # The output ended: the worker exited, so nothing more will answer.
        answered.set()

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
    reached_ready = ready.is_set()
    timed_out = process.poll() is None and not reached_ready
    synth_timed_out = False
    if request is not None and reached_ready:
        synth_timed_out = _run_request(
            process, request, started, synth, lock, answered, synth_limit_s
        )
    exited = process.poll() is not None
    if not exited:
        process.kill()
    returncode = process.wait()
    for thread in threads:
        thread.join(timeout=5)
    _close_streams(process)
    with lock:
        recorded = [
            {"at": line["at"], "text": line["text"][:MAX_LINE_CHARS]} for line in lines[:MAX_LINES]
        ]
        stderr = b"".join(tail)[-STDERR_TAIL_BYTES:].decode("utf-8", "replace")
        synth["timed_out"] = synth_timed_out
        synth["answered"] = synth["done_at"] is not None
        synth["worker_exited"] = exited
    report: dict[str, Any] = {
        "ready": reached_ready,
        "timed_out": timed_out,
        "returncode": None if timed_out else returncode,
        "seconds": round(time.monotonic() - started, 1),
        "lines": recorded,
        "stderr_tail": stderr,
    }
    if request is not None:
        report["synth"] = synth
    return report


def diagnose(
    argv: Sequence[str], env: Mapping[str, str], python: str,
    worker_limit_s: float = WORKER_LIMIT_S, import_limit_s: float = IMPORT_LIMIT_S,
    request: Mapping[str, Any] | None = None, synth_limit_s: float = SYNTH_LIMIT_S,
) -> dict[str, Any]:
    return {
        "worker": run_worker(argv, env, worker_limit_s, request, synth_limit_s),
        "import_torch": time_import_torch(python, env, import_limit_s),
    }
