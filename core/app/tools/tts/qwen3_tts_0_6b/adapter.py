"""``TtsPort`` over the Qwen3-TTS 0.6B CustomVoice preset speakers.

The device is picked once when the adapter is built. `auto` takes CUDA when torch
reports one, and a failed CUDA load steps down to the CPU once; an explicit `cuda`
that cannot load stays an error. The chosen device and the reason go to the
runtime status, and the device is part of the engine digest so CPU and GPU audio
never share a cache entry.

The model lives in a child worker process (``worker.py``) that loads it from the
prepared local folder once and keeps it for the job. The worker leaves after
``IDLE_S`` seconds without a request, and the next call starts a new one. This
adapter never downloads a file: a missing model file or package is
``tts_not_ready``.

A sentence has its own timeout, the larger of ``SENTENCE_TIMEOUT_FLOOR_S`` and
``SENTENCE_TIMEOUT_FACTOR`` times the expected speech length. Timeout, worker
failure and an unusable WAV end the call with ``tts_timeout`` or ``tts_failed``. The
worker answers each request with a ``received`` notice before it synthesizes; a timeout
detail says whether it arrived, and the sentence log line says how long the answer took.

The worker reports each load step as a ``phase`` message. A load may take as long
as ``LOAD_TIMEOUT_S`` in all, but each step has ``PHASE_TIMEOUT_S`` from the previous
message, so a slow step on a slow disk finishes while a silent worker still times
out. The adapter logs the fixed step names with their seconds, and a load timeout
names the last finished step in its detail: the hang is in the step after it.
Nothing falls back to silence or to another engine. A timeout or a cancel kills
the worker's whole process tree, so a stuck model never outlives its call.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
from app.tools.device import DeviceSelection

# Tree kill and the Windows Job Object are the one implementation of the other
# adapters; they take a process this adapter starts for itself.
from app.tools.process import KILL_GRACE_S, _JobObject, _kill_tree, build_env
from app.tools.tts.qwen3_tts_0_6b.worker import LOAD_PHASES

ENGINE_ID = "qwen3-tts-0.6b"
ENGINE_REVISION = 1
"""Raised whenever this adapter changes the audio it produces for the same input."""

MODEL_ITEM = "model-tts-qwen3-0.6b"
PACKAGE_ITEM = "package-qwen-tts"
PACKAGE_NAME = "qwen-tts"

SAMPLE_RATE = 24000
LANGUAGES = {"ko": "Korean", "en": "English"}

IDLE_S = 120.0
PHASE_TIMEOUT_S = 300.0
"""How long a load step may stay silent: the limit restarts on every phase message."""
LOAD_TIMEOUT_S = 1200.0
"""The whole load, first start on a cold disk included, however many steps report."""
SENTENCE_TIMEOUT_FLOOR_S = 30.0
SENTENCE_TIMEOUT_FACTOR = 10.0

CHARS_PER_SECOND = {"ko": 5.5, "en": 13.0}
MIN_EXPECTED_MS = 300
"""Start values of the expected speech rate. They match the voice service table,
which this layer cannot import; a test keeps both in step."""

THREADS_ENV = "APP_TTS_THREADS"
MAX_DEFAULT_THREADS = 4
POLL_S = 0.05
WORKER_PATH = Path(__file__).with_name("worker.py")
CUDA_ENV = ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER")
"""Host GPU assignment of this process. The worker must see the same devices."""
SITE_ENV = "APP_MAIN_SITE"

logger = logging.getLogger(__name__)


def _site_env() -> dict[str, str]:
    """`PYTHONPATH` of the app's packages, when an installed build names them.

    The app finds its packages through `sys.path`, which the worker, a new process of the
    same interpreter, does not inherit. User site packages stay out of it.
    """
    site = os.environ.get(SITE_ENV)
    return {"PYTHONPATH": site, "PYTHONNOUSERSITE": "1"} if site else {}


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


def cuda_available() -> bool:
    """True when torch sees a CUDA device; the CPU wheel always says False."""
    import torch

    return bool(torch.cuda.is_available())


def cuda_runs() -> bool:
    """True when torch can execute an operation on the CUDA device it reports.

    `is_available` only detects a device. A driver or architecture mismatch fails
    on the first real kernel, so an explicit `cuda` checks here before startup ends.
    """
    import torch

    try:
        torch.zeros(1, device="cuda")
        torch.cuda.synchronize()
    except (AssertionError, RuntimeError):
        return False
    return True


def cuda_problem() -> str | None:
    """None when one CUDA operation completes, else the reason startup must stop."""
    if cuda_runs():
        return None
    return "torch cannot run an operation on a CUDA device"


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
        # Drain the pipe so a chatty child never blocks, but keep no text: the
        # adapter logs only exception types and error codes, never raw stderr.
        assert self.process.stderr is not None
        while self.process.stderr.read(4096):
            pass

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
        selection: DeviceSelection | None = None,
        runtime_digest_for: Callable[[str], str] | None = None,
        worker_command: Sequence[str] | None = None,
        idle_s: float = IDLE_S,
        load_timeout_s: float = LOAD_TIMEOUT_S,
        phase_timeout_s: float = PHASE_TIMEOUT_S,
        sentence_floor_s: float = SENTENCE_TIMEOUT_FLOOR_S,
        sentence_factor: float = SENTENCE_TIMEOUT_FACTOR,
    ) -> None:
        if threads < 1:
            raise ValueError("threads must be positive")
        self._selection = selection or DeviceSelection("cpu", "cpu", "configured")
        self._model_dir = model_dir
        self._model_files = dict(model_files)
        self._model_revision = model_revision
        self._runtime_digest = runtime_digest
        self._runtime_digest_for = runtime_digest_for
        self._threads = threads
        self._package_ready = package_ready
        self._command = list(worker_command or (sys.executable, str(WORKER_PATH)))
        self._idle_s = idle_s
        self._load_timeout_s = load_timeout_s
        self._phase_timeout_s = phase_timeout_s
        self._sentence_floor_s = sentence_floor_s
        self._sentence_factor = sentence_factor
        self._worker: _Worker | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._closed = False
        self._synthesized = False

    @property
    def device(self) -> str:
        """The device the worker loads on, after a possible CPU step-down."""
        return self._selection.snapshot()[0]

    @property
    def device_reason(self) -> str:
        """Why that device was chosen: configured, detected, unavailable, load_failed."""
        return self._selection.snapshot()[1]

    def device_status(self) -> tuple[str, str]:
        """The device and reason from one state, for the runtime status."""
        return self._selection.snapshot()

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
                try:
                    duration_ms = self._exchange(request, timeout_s, cancel)
                except AppError as error:
                    if not self._can_retry_synth(error):
                        raise
                    logger.warning(
                        "tts cuda synth failed (%s); retrying on cpu",
                        error.detail.get("reason") or error.code,
                    )
                    self._step_down()
                    self._stop_worker()
                    duration_ms = self._exchange(request, timeout_s, cancel)
                self._synthesized = True
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
            reply = self._wait_reply(worker, deadline, cancel, timeout_s)
            if reply is not None and reply.get("type") == "bye":
                self._stop_worker()
                continue
            return self._finish(reply, request)
        raise _failed("worker_idle_exit")

    def _wait_reply(
        self, worker: _Worker, deadline: float, cancel: CancelToken, timeout_s: float
    ) -> dict[str, Any] | None:
        """The worker's answer to the request, after its `received` notice.

        The notice tells a request that never crossed the pipe from a synthesis that is
        only slow; the timeout error and the log carry which of the two it was.
        """
        started = time.monotonic()
        received_s: float | None = None
        try:
            reply = self._wait(worker, deadline, cancel, "synthesize")
            while reply is not None and reply.get("type") == "received":
                received_s = time.monotonic() - started
                reply = self._wait(worker, deadline, cancel, "synthesize")
        except AppError as error:
            if error.code == "tts_timeout":
                error.detail["received"] = received_s is not None
                logger.warning(
                    "tts sentence timed out after %.0fs (limit %.0fs); the worker %s the request",
                    time.monotonic() - started,
                    timeout_s,
                    "received" if received_s is not None else "never received",
                )
            raise
        if reply is not None and reply.get("type") == "done":
            seconds = reply.get("seconds")
            logger.info(
                "tts sentence done in %.1fs (limit %.0fs); the worker took %ss",
                time.monotonic() - started,
                timeout_s,
                seconds if isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
                else "?",
            )
        return reply

    def _finish(self, reply: dict[str, Any] | None, request: dict[str, Any]) -> int:
        if reply is None:
            raise self._worker_gone("synthesize")
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

    def _worker_gone(self, stage: str) -> AppError:
        worker = self._worker
        code = None
        if worker is not None:
            try:
                # Output ends before the exit is reaped; the code is worth a short wait.
                code = worker.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        self._stop_worker()
        return _failed("worker_exited", stage=stage, returncode=code)

    def _started(self, cancel: CancelToken) -> _Worker:
        worker = self._worker
        if worker is not None and worker.alive():
            return worker
        self._stop_worker()
        while True:
            try:
                reply = self._spawn(cancel)
            except AppError as error:
                if not self._can_retry_on_cpu(error):
                    raise
                logger.warning(
                    "tts cuda load failed (%s at %s); retrying on cpu",
                    error.detail.get("reason") or error.code,
                    error.detail.get("stage"),
                )
                self._step_down()
                continue
            if reply.get("type") == "ready":
                assert self._worker is not None
                return self._worker
            code = str(reply.get("code", "protocol"))
            self._stop_worker()
            if code == "load_failed" and self._selection.may_fall_back:
                logger.warning(
                    "tts cuda load failed (%s); retrying on cpu",
                    reply.get("name", "unknown"),
                )
                self._step_down()
                continue
            if code == "package_missing":
                raise AppError(
                    "tts_not_ready", detail={"engine": ENGINE_ID, "missing": [PACKAGE_ITEM]}
                )
            raise _failed("model_load" if code == "load_failed" else code)

    def _can_retry_synth(self, error: AppError) -> bool:
        """The first inference on an auto GPU may retry once on the CPU."""
        if self._synthesized or not self._selection.may_fall_back:
            return False
        if error.code == "tts_timeout":
            return True
        return error.code == "tts_failed" and error.detail.get("reason") in {
            "synth_failed",
            "worker_exited",
        }

    def _can_retry_on_cpu(self, error: AppError) -> bool:
        """A load timeout or a worker that exits before ready may retry once on the CPU."""
        if not self._selection.may_fall_back:
            return False
        if error.code == "tts_timeout":
            return error.detail.get("stage") == "load"
        return (
            error.code == "tts_failed"
            and error.detail.get("reason") == "worker_exited"
            and error.detail.get("stage") == "load"
        )

    def worker_launch(self) -> tuple[list[str], dict[str, str]]:
        """The argv and environment of a worker on the current device.

        The only place that builds them, so the release smoke can start the same worker
        by hand and see what the adapter drops: the worker's exit status and stderr.
        """
        argv = [
            *self._command,
            "--model-dir",
            str(self._model_dir),
            "--device",
            self._selection.device,
            "--threads",
            str(self._threads),
            "--idle-s",
            str(self._idle_s),
        ]
        threads = str(self._threads)
        env = build_env()
        env.update(_site_env())
        env.update(
            OMP_NUM_THREADS=threads,
            MKL_NUM_THREADS=threads,
            OPENBLAS_NUM_THREADS=threads,
            TOKENIZERS_PARALLELISM="false",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            PYTHONUTF8="1",
        )
        for name in CUDA_ENV:
            if name in os.environ:
                env[name] = os.environ[name]
        return argv, env

    def _spawn(self, cancel: CancelToken) -> dict[str, Any]:
        """Start a worker on the current device and return its first reply."""
        argv, env = self.worker_launch()
        try:
            worker = _Worker(argv, env)
        except OSError as error:
            raise _failed("worker_start") from error
        self._worker = worker
        reply = self._wait_loaded(worker, cancel)
        if reply is None:
            raise self._worker_gone("load")
        return reply

    def _wait_loaded(self, worker: _Worker, cancel: CancelToken) -> dict[str, Any] | None:
        """The first reply that is not a phase report, within the phase and total limits."""
        started = time.monotonic()
        total_end = started + self._load_timeout_s
        phase_end = started + self._phase_timeout_s
        last_phase: str | None = None
        while True:
            try:
                reply = self._wait(worker, min(total_end, phase_end), cancel, "load")
            except AppError as error:
                if error.code == "tts_timeout":
                    limit = "total" if time.monotonic() >= total_end else "phase"
                    error.detail.update(last_phase=last_phase, limit=limit)
                    logger.warning(
                        "tts load timed out (%s limit, %.0fs in); last finished phase: %s",
                        limit,
                        time.monotonic() - started,
                        last_phase or "none",
                    )
                raise
            if reply is None or reply.get("type") != "phase":
                return reply
            name, seconds = reply.get("name"), reply.get("seconds")
            if name not in LOAD_PHASES or isinstance(seconds, bool):
                continue
            if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
                continue
            last_phase = name
            phase_end = time.monotonic() + self._phase_timeout_s
            logger.info("tts load phase %s took %.1fs", name, seconds)

    def _step_down(self) -> None:
        """Use the CPU after one failed CUDA load, and move the digest with it."""
        self._selection.step_down()
        if self._runtime_digest_for is not None:
            self._runtime_digest = self._runtime_digest_for(self._selection.device)

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
        wheels.append(
            [
                distribution.metadata["Name"],
                distribution.version,
                hashlib.sha256(record.encode("utf-8")).hexdigest(),
            ]
        )
    return sorted(wheels)


def create(settings: AppSettings) -> Qwen3TtsAdapter:
    """The adapter for the model and package the runtime lock pins."""
    model = _runtime_item(settings, MODEL_ITEM)
    package = _runtime_item(settings, PACKAGE_ITEM)
    threads = default_threads()
    requested = str(getattr(settings, "device", "auto"))
    selection = DeviceSelection.resolve(
        requested,
        detect=cuda_available,
        verify=cuda_problem,
        verify_auto=False,
        backend="torch",
    )
    wheels = _runtime_wheels()
    implementation = hashlib.sha256(
        Path(__file__).read_bytes() + WORKER_PATH.read_bytes()
    ).hexdigest()

    def digest_for(device: str) -> str:
        return canonical_digest(
            {
                "engine": ENGINE_ID,
                "revision": ENGINE_REVISION,
                "device": device,
                "dtype": "float32",
                "model": _pinned(model),
                "package": _pinned(package),
                "runtime_wheels": wheels,
                "threads": threads,
                "implementation": implementation,
            }
        )

    return Qwen3TtsAdapter(
        model_dir=settings.model_dir / model["install_path"],
        model_files={entry["file"]: entry["bytes"] for entry in model["files"]},
        model_revision=model["revision"],
        runtime_digest=digest_for(selection.device),
        runtime_digest_for=digest_for,
        threads=threads,
        selection=selection,
        package_ready=lambda: _package_matches(package["version"]),
    )
