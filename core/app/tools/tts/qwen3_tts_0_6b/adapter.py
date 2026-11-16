"""``TtsPort`` over the Qwen3-TTS 0.6B CustomVoice preset speakers, run on the CPU.

The model lives in a child worker process (``worker.py``) that loads it from the
prepared local folder once and keeps it for the job. The worker leaves after
``IDLE_S`` seconds without a request, and the next call starts a new one. This
adapter never downloads a file: a missing model file or package is
``tts_not_ready``.

A sentence has its own timeout, the larger of ``SENTENCE_TIMEOUT_FLOOR_S`` and
``SENTENCE_TIMEOUT_FACTOR`` times the expected speech length. Timeout, worker
failure and an unusable WAV end the call with ``tts_timeout`` or ``tts_failed``.
Nothing falls back to silence or to another engine. A timeout or a cancel kills
the worker's whole process tree, so a stuck model never outlives its call.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
import wave
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any

from app.ports import (
    AppError,
    AppSettings,
    Cancelled,
    CancelToken,
    SynthResult,
    TtsEngineInfo,
    canonical_digest,
)
from app.schemas.voice_manifest import VoiceManifest

# Tree kill and the Windows Job Object are the one implementation of the other
# adapters; they take a process this adapter starts for itself.
from app.tools.process import KILL_GRACE_S, _JobObject, _kill_tree, build_env

ENGINE_ID = "qwen3-tts-0.6b"
ENGINE_REVISION = 1
"""Raised whenever this adapter changes the audio it produces for the same input."""

MODEL_ITEM = "model-tts-qwen3-0.6b"
PACKAGE_ITEM = "package-qwen-tts"
PACKAGE_NAME = "qwen-tts"

SAMPLE_RATE = 24000
LANGUAGES = {"ko": "Korean", "en": "English"}

IDLE_S = 120.0
LOAD_TIMEOUT_S = 300.0
SENTENCE_TIMEOUT_FLOOR_S = 30.0
SENTENCE_TIMEOUT_FACTOR = 10.0

CHARS_PER_SECOND = {"ko": 5.5, "en": 13.0}
MIN_EXPECTED_MS = 300
"""Start values of the expected speech rate. They match the voice service table,
which this layer cannot import; a test keeps both in step."""

THREADS_ENV = "APP_TTS_THREADS"
MAX_DEFAULT_THREADS = 4
POLL_S = 0.05
STDERR_TAIL_BYTES = 1024
WORKER_PATH = Path(__file__).with_name("worker.py")


def expected_ms(text: str, language: str) -> int:
    """Expected speech length before synthesis, from the characters without spaces."""
    characters = sum(1 for character in text if not character.isspace())
    return max(MIN_EXPECTED_MS, math.ceil(characters * 1000 / CHARS_PER_SECOND[language]))


def default_threads() -> int:
    """`APP_TTS_THREADS` when set, else the CPU count capped at ``MAX_DEFAULT_THREADS``."""
    raw = os.environ.get(THREADS_ENV)
    if raw is None:
        return max(1, min(MAX_DEFAULT_THREADS, os.cpu_count() or 1))
    if not raw.isascii() or not raw.isdecimal() or int(raw) < 1:
        raise RuntimeError(f"{THREADS_ENV} must be a positive integer")
    return int(raw)


def _failed(reason: str, **detail: Any) -> AppError:
    return AppError("tts_failed", detail={"engine": ENGINE_ID, "reason": reason, **detail})


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


def _wav_ms(path: Path) -> int:
    """Duration of a complete mono PCM16 WAV at the engine rate, measured from the file."""
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            shape = (handle.getnchannels(), handle.getsampwidth(), handle.getframerate())
            remaining = frames
            while remaining > 0:
                chunk = handle.readframes(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk) // (shape[0] * shape[1])
    except (OSError, EOFError, wave.Error) as error:
        raise _failed("wav_unreadable") from error
    if shape != (1, 2, SAMPLE_RATE):
        raise _failed("wav_format", channels=shape[0], width=shape[1], rate=shape[2])
    if frames <= 0:
        raise _failed("wav_empty")
    if remaining:
        raise _failed("wav_truncated")
    return max(1, frames * 1000 // SAMPLE_RATE)


class Qwen3TtsAdapter:
    def __init__(
        self,
        *,
        model_dir: Path,
        model_files: Mapping[str, int],
        model_revision: str,
        runtime_digest: str,
        threads: int,
        package_ready: Callable[[], bool],
        worker_command: Sequence[str] | None = None,
        idle_s: float = IDLE_S,
        load_timeout_s: float = LOAD_TIMEOUT_S,
        sentence_floor_s: float = SENTENCE_TIMEOUT_FLOOR_S,
        sentence_factor: float = SENTENCE_TIMEOUT_FACTOR,
    ) -> None:
        if threads < 1:
            raise ValueError("threads must be positive")
        self._model_dir = model_dir
        self._model_files = dict(model_files)
        self._model_revision = model_revision
        self._runtime_digest = runtime_digest
        self._threads = threads
        self._package_ready = package_ready
        self._command = list(worker_command or (sys.executable, str(WORKER_PATH)))
        self._idle_s = idle_s
        self._load_timeout_s = load_timeout_s
        self._sentence_floor_s = sentence_floor_s
        self._sentence_factor = sentence_factor
        self._worker: _Worker | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._closed = False

    def info(self) -> TtsEngineInfo:
        return TtsEngineInfo(
            engine_id=ENGINE_ID,
            runtime_digest=self._runtime_digest,
            sample_rate=SAMPLE_RATE,
            languages=tuple(LANGUAGES),
        )

    def ready(self) -> list[str]:
        missing = []
        for name, size in self._model_files.items():
            path = self._model_dir / name
            if not path.is_file() or path.stat().st_size != size:
                missing.append(MODEL_ITEM)
                break
        if not self._package_ready():
            missing.append(PACKAGE_ITEM)
        return missing

    def sentence_timeout_s(self, text: str, language: str) -> float:
        expected_s = self._sentence_factor * expected_ms(text, language) / 1000
        return max(self._sentence_floor_s, expected_s)

    def synthesize(
        self,
        text: str,
        language: str,
        voice: VoiceManifest,
        *,
        out_dir: Path,
        cancel: CancelToken,
    ) -> SynthResult:
        cancel.raise_if_set()
        self._check(text, language, voice)
        missing = self.ready()
        if missing:
            raise AppError("tts_not_ready", detail={"engine": ENGINE_ID, "missing": missing})
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{uuid.uuid4().hex}.wav"
        request = {
            "text": text,
            "language": LANGUAGES[language],
            "speaker": voice.speaker,
            "seed": voice.settings.seed,
            "speed": voice.settings.speed,
            "out": str(out),
        }
        try:
            with self._lock:
                if self._closed:
                    raise _failed("closed")
                timeout_s = self.sentence_timeout_s(text, language)
                duration_ms = self._exchange(request, timeout_s, cancel)
        except BaseException:
            out.unlink(missing_ok=True)
            Path(f"{out}.part").unlink(missing_ok=True)
            raise
        return SynthResult(wav_path=out, duration_ms=duration_ms)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop_worker()

    # --- request checks -------------------------------------------------------

    def _check(self, text: str, language: str, voice: VoiceManifest) -> None:
        if voice.engine_id != ENGINE_ID:
            raise _failed("voice_engine", voice_engine=voice.engine_id)
        if voice.model is not None and (
            voice.model.runtime_item != MODEL_ITEM or voice.model.revision != self._model_revision
        ):
            raise _failed("voice_model")
        if language not in LANGUAGES or language not in [value.value for value in voice.languages]:
            raise _failed("language", language=language)
        if not text.strip():
            raise _failed("empty_text")

    # --- worker exchange ------------------------------------------------------

    def _exchange(self, request: dict[str, Any], timeout_s: float, cancel: CancelToken) -> int:
        """Send one request and return the measured WAV length.

        A worker that left for idleness between two calls answers with ``bye`` or
        refuses the write; the request then goes to a fresh worker once.
        """
        for _ in range(2):
            worker = self._started(cancel)
            self._request_id += 1
            deadline = time.monotonic() + timeout_s
            if not worker.send({"id": self._request_id, **request}):
                self._stop_worker()
                continue
            reply = self._wait(worker, deadline, cancel, "synthesize")
            if reply is not None and reply.get("type") == "bye":
                self._stop_worker()
                continue
            return self._finish(reply, request)
        raise _failed("worker_idle_exit")

    def _finish(self, reply: dict[str, Any] | None, request: dict[str, Any]) -> int:
        if reply is None:
            raise self._worker_gone()
        if reply.get("id") != self._request_id:
            self._stop_worker()
            raise _failed("protocol")
        if reply.get("type") != "done":
            code = str(reply.get("code", "protocol"))
            name = reply.get("name")
            raise _failed(code, **({"error": name} if isinstance(name, str) else {}))
        if reply.get("sample_rate") != SAMPLE_RATE:
            raise _failed("sample_rate", rate=reply.get("sample_rate"))
        return _wav_ms(Path(request["out"]))

    def _worker_gone(self) -> AppError:
        worker = self._worker
        tail, code = "", None
        if worker is not None:
            try:
                # Output ends before the exit is reaped; the code is worth a short wait.
                code = worker.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            tail = worker.stderr_tail[-300:]
        self._stop_worker()
        return _failed("worker_exited", returncode=code, stderr=tail)

    def _started(self, cancel: CancelToken) -> _Worker:
        worker = self._worker
        if worker is not None and worker.alive():
            return worker
        self._stop_worker()
        argv = [
            *self._command,
            "--model-dir",
            str(self._model_dir),
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
        )
        try:
            worker = _Worker(argv, env)
        except OSError as error:
            raise _failed("worker_start") from error
        self._worker = worker
        reply = self._wait(worker, time.monotonic() + self._load_timeout_s, cancel, "load")
        if reply is None:
            raise self._worker_gone()
        if reply.get("type") == "ready":
            return worker
        code = str(reply.get("code", "protocol"))
        self._stop_worker()
        if code == "package_missing":
            raise AppError("tts_not_ready", detail={"engine": ENGINE_ID, "missing": [PACKAGE_ITEM]})
        raise _failed("model_load" if code == "load_failed" else code)

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
                raise Cancelled("cancelled")
            left = deadline - time.monotonic()
            if left <= 0:
                self._stop_worker()
                raise AppError("tts_timeout", detail={"engine": ENGINE_ID, "stage": stage})
            try:
                return worker.messages.get(timeout=min(POLL_S, left))
            except queue.Empty:
                continue

    def _stop_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.stop()


def _package_matches(version: str) -> bool:
    try:
        return metadata.version(PACKAGE_NAME) == version
    except metadata.PackageNotFoundError:
        return False


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


def _runtime_wheels() -> list[list[str]]:
    """Include installed wheel records, including transitive inference dependencies.

    RECORD identifies wheel contents without incorporating installation paths.
    Development-only package changes may also invalidate the cache; this is safer
    than silently reusing audio after an unlisted inference dependency changes.
    """
    wheels = []
    for distribution in metadata.distributions():
        record = distribution.read_text("RECORD") or ""
        wheels.append([
            distribution.metadata["Name"],
            distribution.version,
            hashlib.sha256(record.encode("utf-8")).hexdigest(),
        ])
    return sorted(wheels)


def create(settings: AppSettings) -> Qwen3TtsAdapter:
    """The adapter for the model and package the runtime lock pins."""
    model = _runtime_item(settings, MODEL_ITEM)
    package = _runtime_item(settings, PACKAGE_ITEM)
    threads = default_threads()
    digest = canonical_digest(
        {
            "engine": ENGINE_ID,
            "revision": ENGINE_REVISION,
            "device": "cpu",
            "dtype": "float32",
            "model": _pinned(model),
            "package": _pinned(package),
            "runtime_wheels": _runtime_wheels(),
            "threads": threads,
            "implementation": hashlib.sha256(
                Path(__file__).read_bytes() + WORKER_PATH.read_bytes()
            ).hexdigest(),
        }
    )
    return Qwen3TtsAdapter(
        model_dir=settings.model_dir / model["install_path"],
        model_files={entry["file"]: entry["bytes"] for entry in model["files"]},
        model_revision=model["revision"],
        runtime_digest=digest,
        threads=threads,
        package_ready=lambda: _package_matches(package["version"]),
    )
