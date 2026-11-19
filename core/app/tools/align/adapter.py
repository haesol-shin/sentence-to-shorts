"""Forced alignment adapter boundary.

app.yaml selects the aligner through `providers.adapters.aligner`. The value
`none` means that no aligner is wired for this build, so every call reports
`align_unavailable` and the voice service turns the line into a sentence caption.
The value `whisperx` runs a WhisperX worker in the second environment named by
`APP_ALIGN_PYTHON`, because the Qwen TTS environment pins torch 2.7 and WhisperX
needs torch 2.8. Without that environment, or without the prepared model files,
the line also reports `align_unavailable`.

The worker keeps one language model in memory and answers one line per request.
A line has its own timeout, the larger of ``TIMEOUT_FLOOR_S`` and
``TIMEOUT_FACTOR`` times its speech length. A timeout or a cancel kills the
worker's whole process tree. Word scores and display-to-speech mapping decide
between phrase timing and the sentence-caption failure codes in `mapping`.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import wave
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any

from app.ports import (
    AlignResult,
    AppSettings,
    Cancelled,
    CancelToken,
    canonical_digest,
)
from app.tools.align import mapping
from app.tools.process import KILL_GRACE_S, _JobObject, _kill_tree, build_env

ENGINE_ID = "whisperx"
ENGINE_REVISION = 1
"""Raised whenever this adapter changes the phrases it returns for the same input."""

MODEL_KO_ITEM = "model-align-ko"
MODEL_EN_ITEM = "model-align-en"
NLTK_ITEM = "model-nltk-punkt-tab"

LANGUAGES = ("ko", "en")
PRECISION = "float32"
DEVICE = "cpu"

NONE = "none"
"""The `providers.adapters.aligner` value that selects the unavailable aligner."""
WHISPERX = "whisperx"
"""The `providers.adapters.aligner` value that selects this adapter."""

PYTHON_ENV = "APP_ALIGN_PYTHON"
THREADS_ENV = "APP_ALIGN_THREADS"
MAX_DEFAULT_THREADS = 4

IDLE_S = 120.0
READY_TIMEOUT_S = 120.0
TIMEOUT_FLOOR_S = 120.0
TIMEOUT_FACTOR = 10.0
POLL_S = 0.05
STDERR_TAIL_BYTES = 1024
ENV_TIMEOUT_S = 60.0
WORKER_PATH = Path(__file__).with_name("worker.py")

_ENV_SCRIPT = """
import hashlib
import json
import platform
import sys
from importlib import metadata

wheels = []
for distribution in metadata.distributions():
    record = distribution.read_text("RECORD") or ""
    wheels.append(
        [
            str(distribution.metadata["Name"]),
            distribution.version,
            hashlib.sha256(record.encode("utf-8")).hexdigest(),
        ]
    )
try:
    whisperx = metadata.version("whisperx")
except metadata.PackageNotFoundError:
    whisperx = None
print(
    json.dumps(
        {
            "implementation": sys.implementation.name,
            "python": platform.python_version(),
            "wheels": sorted(wheels),
            "whisperx": whisperx,
        },
        sort_keys=True,
    )
)
"""


def default_threads() -> int:
    """`APP_ALIGN_THREADS` when set, else the CPU count capped at ``MAX_DEFAULT_THREADS``."""
    raw = os.environ.get(THREADS_ENV)
    if raw is None:
        return max(1, min(MAX_DEFAULT_THREADS, os.cpu_count() or 1))
    if not raw.isascii() or not raw.isdecimal() or int(raw) < 1:
        raise RuntimeError(f"{THREADS_ENV} must be a positive integer")
    return int(raw)


def _wav_ms(path: Path) -> int:
    """Duration of a complete mono PCM16 WAV, measured from the file."""
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
            if channels <= 0 or width <= 0 or rate <= 0:
                raise ValueError("wav_format")
            remaining = frames
            while remaining > 0:
                chunk = handle.readframes(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk) // (channels * width)
    except (OSError, EOFError, wave.Error) as error:
        raise ValueError("wav_unreadable") from error
    if (channels, width) != (1, 2) or rate <= 0:
        raise ValueError("wav_format")
    if frames <= 0:
        raise ValueError("wav_empty")
    if remaining:
        raise ValueError("wav_truncated")
    return max(1, frames * 1000 // rate)


class _Worker:
    """One worker process: its pipes, a reader per stream and its process tree."""

    def __init__(self, argv: Sequence[str], env: Mapping[str, str]) -> None:
        kwargs: dict[str, Any] = {
            "env": dict(env),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        self.job: _JobObject | None = None
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            self.job = _JobObject()
        else:
            kwargs["start_new_session"] = True
        try:
            self.process: subprocess.Popen[bytes] = subprocess.Popen(list(argv), **kwargs)
        except BaseException:
            if self.job is not None:
                self.job.close()
            raise
        self.pgid = None if os.name == "nt" else os.getpgid(self.process.pid)
        if self.job is not None:
            try:
                self.job.assign(self.process)
            except OSError:
                self.stop()
                raise
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._stderr = bytearray()
        self._threads = [
            threading.Thread(target=self._read_messages, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _read_messages(self) -> None:
        assert self.process.stdout is not None
        for raw in self.process.stdout:
            try:
                message = json.loads(raw)
            except ValueError:
                message = None
            self.messages.put(
                message if isinstance(message, dict) else {"type": "error", "code": "protocol"}
            )
        self.messages.put(None)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        while chunk := self.process.stderr.read(4096):
            self._stderr += chunk
            del self._stderr[:-STDERR_TAIL_BYTES]

    @property
    def stderr_tail(self) -> str:
        return bytes(self._stderr).decode("utf-8", "replace").strip()

    def alive(self) -> bool:
        return self.process.poll() is None

    def send(self, message: Mapping[str, Any]) -> bool:
        """False when the worker no longer reads, for example after its idle exit."""
        assert self.process.stdin is not None
        line = json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n"
        try:
            self.process.stdin.write(line.encode("ascii"))
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return False
        return True

    def stop(self) -> None:
        """Kill the worker and everything it started, then reap it."""
        _kill_tree(self.process, self.job, self.pgid)
        try:
            self.process.wait(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            _kill_tree(self.process, self.job, self.pgid)
            self.process.wait(timeout=KILL_GRACE_S)
        for thread in getattr(self, "_threads", ()):
            thread.join(timeout=KILL_GRACE_S)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass
        if self.job is not None:
            self.job.close()


class _Unavailable(Exception):
    """The second environment or a prepared model could not start a worker."""


class _LineTimeout(Exception):
    """One line used its full timeout."""


class AlignerAdapter:
    def align(
        self,
        wav: Path,
        speech_text: str,
        display_text: str,
        language: str,
        *,
        cancel: CancelToken,
    ) -> AlignResult:
        raise NotImplementedError


class UnavailableAligner(AlignerAdapter):
    """Reports `align_unavailable` for every line. It never invents a time."""

    def runtime_digest(self) -> str:
        return hashlib.sha256(b"align-unavailable-1").hexdigest()

    def align(
        self,
        wav: Path,
        speech_text: str,
        display_text: str,
        language: str,
        *,
        cancel: CancelToken,
    ) -> AlignResult:
        cancel.raise_if_set()
        return AlignResult(phrases=None, failure=mapping.UNAVAILABLE)


class WhisperXAligner(AlignerAdapter):
    def __init__(
        self,
        *,
        python: Path | None,
        model_files: Sequence[tuple[str, Path, Mapping[str, int]]],
        nltk_data: Path,
        threads: int,
        runtime_digest: str,
        worker_command: Sequence[str] | None = None,
        idle_s: float = IDLE_S,
        ready_timeout_s: float = READY_TIMEOUT_S,
        timeout_floor_s: float = TIMEOUT_FLOOR_S,
        timeout_factor: float = TIMEOUT_FACTOR,
    ) -> None:
        if threads < 1:
            raise ValueError("threads must be positive")
        if len(model_files) < 2:
            raise ValueError("both language model directories are required")
        self._python = python
        self._model_files = [(item, path, dict(files)) for item, path, files in model_files]
        self._nltk_data = nltk_data
        self._threads = threads
        self._runtime_digest = runtime_digest
        self._command = list(
            worker_command or ([str(python), str(WORKER_PATH)] if python is not None else [])
        )
        self._idle_s = idle_s
        self._ready_timeout_s = ready_timeout_s
        self._timeout_floor_s = timeout_floor_s
        self._timeout_factor = timeout_factor
        self._worker: _Worker | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._closed = False

    def runtime_digest(self) -> str:
        return self._runtime_digest

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop_worker()

    def missing(self) -> list[str]:
        """Prepared model items that are absent; empty when every file is there."""
        missing: list[str] = []
        for item, root, files in self._model_files:
            for name, size in files.items():
                path = root / name
                if not path.is_file() or path.stat().st_size != size:
                    missing.append(item)
                    break
        splitter = self._nltk_data / "tokenizers" / "punkt_tab" / "english"
        if not splitter.is_dir():
            missing.append(NLTK_ITEM)
        return missing

    def align(
        self,
        wav: Path,
        speech_text: str,
        display_text: str,
        language: str,
        *,
        cancel: CancelToken,
    ) -> AlignResult:
        cancel.raise_if_set()
        if str(language) not in LANGUAGES or not self._command or self.missing():
            return AlignResult(phrases=None, failure=mapping.UNAVAILABLE)
        try:
            speech_ms = _wav_ms(wav)
        except ValueError:
            return AlignResult(phrases=None, failure=mapping.FAILED)
        timeout_s = max(self._timeout_floor_s, self._timeout_factor * speech_ms / 1000)
        with self._lock:
            if self._closed:
                return AlignResult(phrases=None, failure=mapping.FAILED)
            return self._exchange(
                wav, speech_text, display_text, str(language), speech_ms, timeout_s, cancel
            )

    # --- worker exchange ------------------------------------------------------

    def _exchange(
        self,
        wav: Path,
        speech_text: str,
        display_text: str,
        language: str,
        speech_ms: int,
        timeout_s: float,
        cancel: CancelToken,
    ) -> AlignResult:
        """Send one line and return its phrases or failure; retry one idle exit."""
        for _ in range(2):
            try:
                worker = self._started(cancel)
            except _Unavailable:
                return AlignResult(phrases=None, failure=mapping.UNAVAILABLE)
            self._request_id += 1
            request = {
                "id": self._request_id,
                "wav": str(wav),
                "speech_text": speech_text,
                "language": language,
                "speech_ms": speech_ms,
            }
            if not worker.send(request):
                self._stop_worker()
                continue
            try:
                reply = self._wait(
                    worker, time.monotonic() + timeout_s, cancel, "align"
                )
            except _LineTimeout:
                self._stop_worker()
                return AlignResult(phrases=None, failure=mapping.FAILED)
            if reply is None:
                self._stop_worker()
                return AlignResult(phrases=None, failure=mapping.FAILED)
            if reply.get("type") == "bye":
                self._stop_worker()
                continue
            return self._finish(reply, display_text, speech_text, speech_ms)
        return AlignResult(phrases=None, failure=mapping.FAILED)

    def _finish(
        self, reply: dict[str, Any], display_text: str, speech_text: str, speech_ms: int
    ) -> AlignResult:
        if reply.get("id") != self._request_id:
            self._stop_worker()
            return AlignResult(phrases=None, failure=mapping.FAILED)
        if reply.get("type") != "words":
            code = str(reply.get("code", "protocol"))
            if code in ("model_load", "package_missing"):
                self._stop_worker()
                return AlignResult(phrases=None, failure=mapping.UNAVAILABLE)
            return AlignResult(phrases=None, failure=mapping.FAILED)
        words = reply.get("words")
        if not isinstance(words, list):
            return AlignResult(phrases=None, failure=mapping.FAILED)
        try:
            result = mapping.judge(display_text, speech_text, words, speech_ms)
        except Exception:  # noqa: BLE001 - a broken reply is one failed line
            return AlignResult(phrases=None, failure=mapping.FAILED)
        return AlignResult(phrases=result.phrases, failure=result.failure)

    def _started(self, cancel: CancelToken) -> _Worker:
        worker = self._worker
        if worker is not None and worker.alive():
            return worker
        self._stop_worker()
        argv = [
            *self._command,
            "--model-ko",
            str(self._model_files[0][1]),
            "--model-en",
            str(self._model_files[1][1]),
            "--model-en-file",
            next(iter(self._model_files[1][2])),
            "--nltk-data",
            str(self._nltk_data),
            "--threads",
            str(self._threads),
            "--idle-s",
            str(self._idle_s),
        ]
        threads = str(self._threads)
        env = build_env()
        env.update(
            OMP_NUM_THREADS=threads,
            MKL_NUM_THREADS=threads,
            OPENBLAS_NUM_THREADS=threads,
            TOKENIZERS_PARALLELISM="false",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            PYTHONUTF8="1",
            NLTK_DATA=str(self._nltk_data),
        )
        try:
            worker = _Worker(argv, env)
        except OSError as error:
            raise _Unavailable("worker_start") from error
        self._worker = worker
        try:
            reply = self._wait(worker, time.monotonic() + self._ready_timeout_s, cancel, "load")
        except _LineTimeout:
            self._stop_worker()
            raise _Unavailable("worker_ready") from None
        if reply is None:
            self._stop_worker()
            raise _Unavailable("worker_exited") from None
        if reply.get("type") == "ready":
            return worker
        self._stop_worker()
        raise _Unavailable(str(reply.get("code", "protocol")))

    def _wait(
        self, worker: _Worker, deadline: float, cancel: CancelToken, stage: str
    ) -> dict[str, Any] | None:
        """The next worker message; None when its output ended.

        A set cancel token or an expired deadline kills the worker's process tree
        first, so the caller never leaves a running model behind.
        """
        while True:
            if cancel.is_set():
                self._stop_worker()
                cancel.raise_if_set()
                raise Cancelled(f"cancelled during {stage}")
            left = deadline - time.monotonic()
            if left <= 0:
                raise _LineTimeout(stage)
            try:
                return worker.messages.get(timeout=min(POLL_S, left))
            except queue.Empty:
                continue

    def _stop_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.stop()


def selected_aligner(settings: AppSettings) -> str | None:
    providers = getattr(settings, "providers", None)
    return getattr(providers, "adapters", {}).get("aligner")


def _runtime_item(settings: AppSettings, item_id: str) -> dict[str, Any]:
    items = getattr(getattr(settings, "runtime", None), "items", None) or []
    for item in items:
        value = item.model_dump(mode="python") if hasattr(item, "model_dump") else dict(item)
        if value["id"] == item_id:
            return value
    raise RuntimeError(f"the runtime lock has no {item_id} item")


def _pinned(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "version": item["version"],
        "revision": item["revision"],
        "files": [[entry["file"], entry["sha256"]] for entry in item["files"]],
    }


def _wheels(rows: Any) -> list[list[Any]]:
    if not isinstance(rows, (list, tuple)):
        return []
    return sorted(
        [
            [str(row[0]), str(row[1]), str(row[2])]
            for row in rows
            if isinstance(row, (list, tuple)) and len(row) == 3
        ]
    )


def _main_environment() -> dict[str, Any]:
    """The environment that runs the app: its Python and every installed wheel."""
    return {
        "implementation": sys.implementation.name,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "wheels": _wheels(
            [
                [
                    str(distribution.metadata["Name"]),
                    distribution.version,
                    hashlib.sha256(
                        (distribution.read_text("RECORD") or "").encode("utf-8")
                    ).hexdigest(),
                ]
                for distribution in metadata.distributions()
            ]
        ),
    }


def _environment(python: Path | None) -> dict[str, Any] | None:
    """The second environment's Python, wheels and WhisperX version, or None."""
    if python is None:
        return None
    env = build_env()
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            [str(python), "-c", _ENV_SCRIPT],
            capture_output=True,
            text=True,
            timeout=ENV_TIMEOUT_S,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"unavailable": type(error).__name__}
    if completed.returncode:
        return {"unavailable": f"exit {completed.returncode}"}
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return {"unavailable": "output"}
    if not isinstance(payload, dict):
        return {"unavailable": "output"}
    payload["wheels"] = _wheels(payload.get("wheels"))
    return payload


def create(settings: AppSettings) -> AlignerAdapter:
    """`none` is unavailable, `whisperx` is this adapter, any other value stays unimplemented."""
    selected = selected_aligner(settings)
    if selected == NONE:
        return UnavailableAligner()
    if selected != WHISPERX:
        raise NotImplementedError("tools/align")
    python_raw = os.environ.get(PYTHON_ENV)
    python = Path(python_raw).expanduser() if python_raw else None
    model_ko = _runtime_item(settings, MODEL_KO_ITEM)
    model_en = _runtime_item(settings, MODEL_EN_ITEM)
    nltk = _runtime_item(settings, NLTK_ITEM)
    model_dir = settings.model_dir
    ko_dir = model_dir / model_ko["install_path"]
    en_dir = model_dir / model_en["install_path"]
    nltk_data = model_dir / Path(nltk["install_path"]).parent
    threads = default_threads()
    digest = canonical_digest(
        {
            "device": DEVICE,
            "engine": ENGINE_ID,
            "revision": ENGINE_REVISION,
            "precision": PRECISION,
            "models": [_pinned(model_ko), _pinned(model_en), _pinned(nltk)],
            "main_environment": _main_environment(),
            "aligner_environment": _environment(python),
            "threads": threads,
            "implementation": hashlib.sha256(
                Path(__file__).read_bytes()
                + WORKER_PATH.read_bytes()
                + Path(mapping.__file__).read_bytes()
            ).hexdigest(),
        }
    )
    return WhisperXAligner(
        python=python,
        model_files=[
            (MODEL_KO_ITEM, ko_dir, {entry["file"]: entry["bytes"] for entry in model_ko["files"]}),
            (MODEL_EN_ITEM, en_dir, {entry["file"]: entry["bytes"] for entry in model_en["files"]}),
        ],
        nltk_data=nltk_data,
        threads=threads,
        runtime_digest=digest,
    )


def create_skeleton(settings: AppSettings) -> AlignerAdapter:
    """Fixture-profile placeholder; every call still reports not implemented."""
    return AlignerAdapter()


__all__ = [
    "AlignerAdapter",
    "UnavailableAligner",
    "WhisperXAligner",
    "create",
    "create_skeleton",
    "default_threads",
    "selected_aligner",
]
