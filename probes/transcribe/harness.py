#!/usr/bin/env python3
"""Measure faster-whisper small int8 transcription on a CPU.

This is probe code, not product code. It must not join the product
dependencies or the product lockfile.

The thing under test may fail. A model download, a model load or a
transcription error is written to the result JSON as a result and the process
still exits 0, so the workflow reports it instead of failing. Only a harness
error writes status ``harness_error`` and exits 2.
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import platform
import random
import re
import sys
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

SCHEMA_VERSION = 1
PROBE_NAME = "transcribe"
DEFAULT_LANGUAGES = ("ko", "en")
DEFAULT_MODEL = "small"
DEFAULT_COMPUTE_TYPE = "int8"
DEFAULT_FIXTURE_SECONDS = 24.0
MIN_FIXTURE_SECONDS = 20.0
MAX_FIXTURE_SECONDS = 40.0
DEFAULT_DOWNLOAD_TIMEOUT_S = 1800.0
SAMPLE_RATE = 16000
LANGUAGE_SEEDS = {"ko": 20260101, "en": 20260102}
VERSION_PACKAGES = (
    "faster-whisper",
    "ctranslate2",
    "av",
    "onnxruntime",
    "tokenizers",
    "huggingface-hub",
    "numpy",
    "tqdm",
)
STUB_TEXT = {"ko": "stub ko transcript", "en": "stub en transcript"}
WORD_SEPARATORS = re.compile(r"[^\w']+", re.UNICODE)


class HarnessError(Exception):
    """The harness itself cannot run; this is not a result about the subject."""


class ModelUnavailable(Exception):
    """The thing under test could not be prepared; this is a result."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class Settings:
    out: Path
    languages: tuple[str, ...] = DEFAULT_LANGUAGES
    audio_dir: Path = Path("probes/transcribe/audio")
    fixture_seconds: float = DEFAULT_FIXTURE_SECONDS
    model: str = DEFAULT_MODEL
    compute_type: str = DEFAULT_COMPUTE_TYPE
    threads: int = 1
    download_timeout_s: float = DEFAULT_DOWNLOAD_TIMEOUT_S
    beam_size: int = 5
    stub: bool = False

    @property
    def work_dir(self) -> Path:
        return self.out.parent


@dataclass
class LoadedModel:
    info: dict
    transcribe: Callable[[Path, str], tuple[list[dict], dict]]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _elapsed_ms(started: float) -> int:
    return int(round((time.monotonic() - started) * 1000))


def _seconds(value: float | int | None) -> float | None:
    return None if value is None else round(float(value) / 1000.0, 2)


def _mb(value: float | int | None) -> float | None:
    return None if value is None else round(float(value) / (1024.0 * 1024.0), 1)


def read_peak_rss_bytes() -> tuple[int | None, str | None]:
    """Return the peak resident set size of this process, if measurable."""
    if sys.platform == "win32":
        try:
            return _windows_peak_rss()
        except Exception:
            return None, None
    try:
        import resource
    except ImportError:
        return None, None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS reports bytes.
    scale = 1 if sys.platform == "darwin" else 1024
    return int(usage) * scale, "ru_maxrss"


def _windows_peak_rss() -> tuple[int | None, str | None]:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    process = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        return None, None
    return int(counters.PeakWorkingSetSize), "psapi"


def total_ram_bytes() -> int | None:
    """Return the physical memory of the host, if measurable."""
    if sys.platform == "win32":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:
            return None
        return None
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, ValueError, OSError):
        return None


def installed_versions() -> dict[str, str | None]:
    from importlib.metadata import PackageNotFoundError, version

    found: dict[str, str | None] = {}
    for name in VERSION_PACKAGES:
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            found[name] = None
    return found


def environment() -> dict:
    return {
        "os": platform.system(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "total_ram_bytes": total_ram_bytes(),
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
        "runner_image": os.environ.get("ImageOS"),
        "event": os.environ.get("GITHUB_EVENT_NAME"),
        "commit": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
    }


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    if rate <= 0:
        raise HarnessError(f"{path.name}: WAV header has no sample rate")
    return int(round(frames * 1000.0 / rate))


def _clip(value: float) -> int:
    return max(-32767, min(32767, int(value)))


def _formant_weight(frequency: float, f1: float, f2: float) -> float:
    first = 1.2 / (1.0 + ((frequency - f1) / 200.0) ** 2)
    second = 0.8 / (1.0 + ((frequency - f2) / 320.0) ** 2)
    third = 0.1 / (1.0 + (frequency / 4000.0) ** 2)
    return first + second + third


def _syllable_table(f0: float, f1: float, f2: float) -> list[float]:
    length = max(16, int(round(SAMPLE_RATE / f0)))
    table = []
    for index in range(length):
        phase = 2.0 * math.pi * index / length
        value = 0.0
        for harmonic in range(1, 9):
            value += _formant_weight(f0 * harmonic, f1, f2) * math.sin(harmonic * phase)
        table.append(value)
    peak = max(abs(value) for value in table) or 1.0
    return [value / peak for value in table]


def _render_syllable(
    samples: array.array,
    offset: int,
    count: int,
    rng: random.Random,
    f0: float,
    f1: float,
    f2: float,
) -> None:
    table = _syllable_table(f0, f1, f2)
    length = len(table)
    attack = max(1, count // 5)
    release = max(1, count // 3)
    start_f0 = f0 * rng.uniform(0.92, 0.98)
    end_f0 = f0 * rng.uniform(1.02, 1.12)
    gain = rng.uniform(0.22, 0.36)
    cursor = 0.0
    for index in range(count):
        progress = index / count
        step = (start_f0 + (end_f0 - start_f0) * progress) / f0
        cursor = (cursor + step) % length
        position = int(cursor)
        fraction = cursor - position
        first = table[position]
        second = table[(position + 1) % length]
        value = first + (second - first) * fraction
        envelope = min(1.0, index / attack, (count - index) / release)
        noise = rng.uniform(-1.0, 1.0) * 0.04 if progress < 0.1 else 0.0
        samples[offset + index] = _clip(32767.0 * gain * (value + noise) * envelope)


def synthesize_tone(path: Path, *, seconds: float, seed: int) -> None:
    """Write a deterministic speech shaped waveform.

    It has syllables, pauses and formant like harmonics, but no words, so it
    exercises the audio path and the model without claiming accuracy.
    """
    rng = random.Random(seed)
    total = int(round(seconds * SAMPLE_RATE))
    samples = array.array("h", bytes(2 * total))
    position = int(0.4 * SAMPLE_RATE)
    while position < total - 1:
        utterance = int(rng.uniform(1.2, 2.2) * SAMPLE_RATE)
        f0 = rng.uniform(95.0, 210.0)
        f1 = rng.uniform(300.0, 780.0)
        f2 = rng.uniform(900.0, 2100.0)
        cursor = 0
        while cursor < utterance - 1:
            count = int(rng.uniform(0.10, 0.24) * SAMPLE_RATE)
            room = min(utterance - cursor, total - position - cursor)
            count = min(count, room)
            if count <= 0:
                break
            _render_syllable(samples, position + cursor, count, rng, f0, f1, f2)
            cursor += count + int(rng.uniform(0.0, 0.04) * SAMPLE_RATE)
        position += utterance + int(rng.uniform(0.25, 0.55) * SAMPLE_RATE)
    write_wav(path, samples)


def write_wav(path: Path, samples: array.array) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.byteorder == "big":
        samples = array.array("h", samples)
        samples.byteswap()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(samples.tobytes())


def prepare_fixture(settings: Settings, language: str) -> dict:
    """Return the audio fixture for one language and its expected text."""
    speech = settings.audio_dir / f"{language}.wav"
    if speech.is_file():
        reference = settings.audio_dir / f"{language}.txt"
        expected = reference.read_text(encoding="utf-8").strip() if reference.is_file() else None
        try:
            duration = wav_duration_ms(speech)
        except (wave.Error, EOFError, OSError) as exc:
            raise HarnessError(f"{speech.name}: not a readable WAV ({exc})") from exc
        meta = {
            "kind": "speech",
            "source": "file",
            "file": speech.name,
            "duration_ms": duration,
            "expected_text": expected,
        }
        return {"path": speech, "duration_ms": duration, "meta": meta}

    generated = settings.work_dir / "fixtures" / f"{language}.wav"
    synthesize_tone(
        generated,
        seconds=settings.fixture_seconds,
        seed=LANGUAGE_SEEDS.get(language, 0),
    )
    duration = wav_duration_ms(generated)
    meta = {
        "kind": "synthetic_tone",
        "source": "generated",
        "file": generated.name,
        "duration_ms": duration,
        "expected_text": None,
    }
    return {"path": generated, "duration_ms": duration, "meta": meta}


def normalize_words(text: str) -> list[str]:
    cleaned = WORD_SEPARATORS.sub(" ", text.lower())
    return [word for word in cleaned.split() if word]


def edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row, token in enumerate(reference, 1):
        current = [row]
        for column, other in enumerate(hypothesis, 1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (token != other),
                )
            )
        previous = current
    return previous[-1]


def unmeasured_word_error(reason: str) -> dict:
    return {
        "measured": False,
        "reason": reason,
        "reference_words": None,
        "hypothesis_words": 0,
        "edits": None,
        "rate": None,
    }


def word_error(reference_text: str | None, transcript: str) -> dict:
    hypothesis = normalize_words(transcript)
    if reference_text is None:
        result = unmeasured_word_error("reference text missing")
        result["hypothesis_words"] = len(hypothesis)
        return result
    reference = normalize_words(reference_text)
    edits = edit_distance(reference, hypothesis)
    return {
        "measured": True,
        "reason": None,
        "reference_words": len(reference),
        "hypothesis_words": len(hypothesis),
        "edits": edits,
        "rate": round(edits / len(reference), 4) if reference else None,
    }


def _walk_model_files(root: Path) -> tuple[int, int, list[dict]]:
    """Return total bytes, file count and per file sizes; shared blobs count once."""
    seen: set[Path] = set()
    total = 0
    entries: list[dict] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        name = candidate.relative_to(root).as_posix()
        if resolved in seen:
            entries.append({"name": name, "bytes": 0, "shared": True})
            continue
        seen.add(resolved)
        size = resolved.stat().st_size
        total += size
        entries.append({"name": name, "bytes": size})
    return total, len(seen), entries


def open_whisper_model(settings: Settings) -> LoadedModel:
    """Download and load the model. Raise HarnessError only for harness faults."""
    try:
        import faster_whisper
    except ImportError as exc:
        raise HarnessError(f"faster-whisper is not installed ({exc})") from exc

    cache_dir = settings.work_dir / "model-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_hit = any(cache_dir.glob("models--*/snapshots/*"))
    holder: dict[str, object] = {}

    def download() -> None:
        try:
            holder["path"] = faster_whisper.download_model(settings.model, cache_dir=str(cache_dir))
        except BaseException as exc:  # noqa: BLE001 - reported as a result
            holder["error"] = exc

    download_started = time.monotonic()
    thread = threading.Thread(target=download, name="model-download", daemon=True)
    thread.start()
    thread.join(settings.download_timeout_s)
    if thread.is_alive():
        raise ModelUnavailable(
            "model_download_timeout",
            f"download did not finish within {settings.download_timeout_s:.0f} s",
        )
    download_ms = _elapsed_ms(download_started)
    if "error" in holder:
        error = holder["error"]
        raise ModelUnavailable(
            "model_download_failed",
            f"{type(error).__name__}: {error}"[:400],
        )

    model_path = Path(str(holder["path"]))
    revision = model_path.name if model_path.is_dir() else None
    try:
        model_bytes, file_count, files = _walk_model_files(model_path)
    except OSError as exc:
        raise HarnessError(f"cannot measure the model files ({exc})") from exc

    load_started = time.monotonic()
    try:
        model = faster_whisper.WhisperModel(
            str(model_path),
            device="cpu",
            compute_type=settings.compute_type,
            cpu_threads=settings.threads,
            num_workers=1,
            local_files_only=True,
        )
    except Exception as exc:
        raise ModelUnavailable(
            "model_load_failed",
            f"{type(exc).__name__}: {exc}"[:400],
        ) from exc
    load_ms = _elapsed_ms(load_started)

    def transcribe(wav: Path, language: str) -> tuple[list[dict], dict]:
        segments, info = model.transcribe(
            str(wav),
            language=language,
            beam_size=settings.beam_size,
            vad_filter=False,
            condition_on_previous_text=False,
            word_timestamps=False,
        )
        collected = [
            {
                "start_ms": int(round(segment.start * 1000)),
                "end_ms": int(round(segment.end * 1000)),
                "text": (segment.text or "").strip(),
            }
            for segment in segments
        ]
        detected = {
            "language": getattr(info, "language", None),
            "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        }
        return collected, detected

    info = {
        "name": settings.model,
        "revision": revision,
        "device": "cpu",
        "compute_type": settings.compute_type,
        "cpu_threads": settings.threads,
        "num_workers": 1,
        "cache_hit": cache_hit,
        "download_ms": download_ms,
        "load_ms": load_ms,
        "bytes": model_bytes,
        "file_count": file_count,
        "files": files,
        "error": None,
    }
    return LoadedModel(info=info, transcribe=transcribe)


def open_stub_model(settings: Settings) -> LoadedModel:
    """Return a stub transcriber for a local dry run. Never used in the workflow."""

    def transcribe(wav: Path, language: str) -> tuple[list[dict], dict]:
        duration = wav_duration_ms(wav)
        text = STUB_TEXT.get(language, "stub transcript")
        return (
            [{"start_ms": 0, "end_ms": duration, "text": text}],
            {"language": language, "language_probability": 1.0},
        )

    info = {
        "name": settings.model,
        "revision": None,
        "device": "cpu",
        "compute_type": "stub",
        "cpu_threads": settings.threads,
        "num_workers": 1,
        "cache_hit": False,
        "download_ms": 0,
        "load_ms": 0,
        "bytes": None,
        "file_count": 0,
        "files": [],
        "error": None,
        "stub": True,
    }
    return LoadedModel(info=info, transcribe=transcribe)


def _run_one(
    settings: Settings,
    model: LoadedModel | None,
    fixture: dict,
    language: str,
    model_error: dict | None,
) -> dict:
    run = {
        "language": language,
        "fixture": fixture["meta"],
        "audio_ms": fixture["duration_ms"],
        "elapsed_ms": None,
        "rtf": None,
        "segments": [],
        "transcript": "",
        "word_count": 0,
        "detected_language": None,
        "language_probability": None,
        "word_error": None,
        "peak_rss_bytes": None,
        "peak_rss_source": None,
        "failure": model_error,
    }
    if model_error is not None:
        run["word_error"] = unmeasured_word_error("model unavailable")
        run["peak_rss_bytes"], run["peak_rss_source"] = read_peak_rss_bytes()
        return run

    started = time.monotonic()
    try:
        segments, detected = model.transcribe(fixture["path"], language)
    except Exception as exc:  # noqa: BLE001 - a subject failure is a result
        run["elapsed_ms"] = _elapsed_ms(started)
        run["failure"] = {
            "kind": "transcribe_failed",
            "message": f"{type(exc).__name__}: {exc}"[:400],
        }
        run["word_error"] = unmeasured_word_error("transcription failed")
        run["peak_rss_bytes"], run["peak_rss_source"] = read_peak_rss_bytes()
        return run

    run["elapsed_ms"] = _elapsed_ms(started)
    run["rtf"] = round(run["elapsed_ms"] / run["audio_ms"], 4) if run["audio_ms"] else None
    run["segments"] = segments
    run["transcript"] = " ".join(segment["text"] for segment in segments).strip()
    run["word_count"] = len(normalize_words(run["transcript"]))
    run["detected_language"] = detected.get("language")
    run["language_probability"] = detected.get("language_probability")
    run["word_error"] = word_error(fixture["meta"]["expected_text"], run["transcript"])
    run["peak_rss_bytes"], run["peak_rss_source"] = read_peak_rss_bytes()
    return run


def collect(settings: Settings, opener: Callable[[Settings], LoadedModel]) -> dict:
    """Run the probe and return the result mapping. No file is written here."""
    fixtures = {language: prepare_fixture(settings, language) for language in settings.languages}
    model: LoadedModel | None = None
    model_error: dict | None = None
    try:
        model = opener(settings)
    except ModelUnavailable as exc:
        model_error = {"kind": exc.kind, "message": exc.message}
    except HarnessError:
        raise
    except Exception as exc:  # noqa: BLE001 - a subject failure is a result
        model_error = {
            "kind": "model_unavailable",
            "message": f"{type(exc).__name__}: {exc}"[:400],
        }

    runs = [
        _run_one(settings, model, fixtures[language], language, model_error)
        for language in settings.languages
    ]
    peak_rss_bytes, peak_rss_source = read_peak_rss_bytes()
    stub_mode = bool(model is not None and model.info.get("stub"))
    failures = [run for run in runs if run["failure"]]
    if stub_mode:
        status = "dry_run"
    elif not failures:
        status = "ok"
    elif len(failures) == len(runs):
        status = "failed"
    else:
        status = "partial"

    notes = []
    if any(fixture["meta"]["expected_text"] is None for fixture in fixtures.values()):
        notes.append(
            "word error is not measured: add probes/transcribe/audio/<language>.wav "
            "and <language>.txt to measure it"
        )
    notes.append(
        "peak RSS is the process peak so far, so a later run does not report less than an earlier run"
    )

    return {
        "schema": SCHEMA_VERSION,
        "probe": PROBE_NAME,
        "created_at": utc_now(),
        "status": status,
        "mode": "stub" if stub_mode else "whisper",
        "settings": {
            "languages": list(settings.languages),
            "model": settings.model,
            "device": "cpu",
            "compute_type": settings.compute_type,
            "cpu_threads": settings.threads,
            "num_workers": 1,
            "beam_size": settings.beam_size,
            "vad_filter": False,
            "condition_on_previous_text": False,
            "word_timestamps": False,
            "fixture_seconds": settings.fixture_seconds,
        },
        "environment": environment(),
        "runtime": installed_versions(),
        "model": model.info if model is not None else {
            "name": settings.model,
            "revision": None,
            "device": "cpu",
            "compute_type": settings.compute_type,
            "cpu_threads": settings.threads,
            "num_workers": 1,
            "cache_hit": None,
            "download_ms": None,
            "load_ms": None,
            "bytes": None,
            "file_count": None,
            "files": [],
            "error": dict(model_error or {}),
        },
        "runs": runs,
        "peak_rss_bytes": peak_rss_bytes,
        "peak_rss_source": peak_rss_source,
        "notes": notes,
    }


def harness_error_result(error: BaseException) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "probe": PROBE_NAME,
        "created_at": utc_now(),
        "status": "harness_error",
        "mode": None,
        "settings": None,
        "environment": environment(),
        "runtime": installed_versions(),
        "model": None,
        "runs": [],
        "peak_rss_bytes": None,
        "peak_rss_source": None,
        "notes": [],
        "error": {
            "kind": "harness_error",
            "message": f"{type(error).__name__}: {error}"[:400],
        },
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def execute(settings: Settings, opener: Callable[[Settings], LoadedModel]) -> tuple[int, dict]:
    """Collect the result, write it and return (exit code, result)."""
    try:
        result = collect(settings, opener)
        code = 0
    except HarnessError as exc:
        result = harness_error_result(exc)
        code = 2
    except Exception as exc:  # noqa: BLE001 - any crash is a harness fault
        result = harness_error_result(exc)
        code = 2
    write_json(settings.out, result)
    return code, result


def _cell(value: object) -> str:
    if value is None:
        return "-"
    return str(value).replace("|", "/").replace("\n", " ")


def summary_markdown(result: dict) -> str:
    environment_info = result.get("environment") or {}
    model = result.get("model") or {}
    lines = ["### Transcription probe", ""]
    lines.append(f"- status: {_cell(result.get('status'))}")
    lines.append(
        "- runner: "
        + f"{_cell(environment_info.get('os'))} {_cell(environment_info.get('machine'))}, "
        + f"python {_cell(environment_info.get('python'))}"
    )
    if model.get("bytes"):
        lines.append(
            f"- model: {_cell(model.get('name'))} {_cell(model.get('compute_type'))}, "
            f"{_mb(model.get('bytes'))} MB, download {_cell(model.get('download_ms'))} ms, "
            f"load {_cell(model.get('load_ms'))} ms"
        )
    elif model.get("error"):
        lines.append(f"- model: unavailable, {_cell(model['error'].get('kind'))}")
    lines.append("")
    lines.append(
        "| language | audio (s) | elapsed (s) | RTF | peak RSS (MB) | words | word error | failure |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for run in result.get("runs") or []:
        measured = (run.get("word_error") or {}).get("rate")
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(run.get("language")),
                    _cell(_seconds(run.get("audio_ms"))),
                    _cell(_seconds(run.get("elapsed_ms"))),
                    _cell(run.get("rtf")),
                    _cell(_mb(run.get("peak_rss_bytes"))),
                    _cell(run.get("word_count")),
                    _cell(measured) if measured is not None else "not measured",
                    _cell((run.get("failure") or {}).get("kind")),
                ]
            )
            + " |"
        )
    notes = result.get("notes") or []
    if notes:
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def append_step_summary(summary: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    try:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(summary)
            if not summary.endswith("\n"):
                handle.write("\n")
    except OSError as exc:
        print(f"warning: cannot write the step summary ({exc})", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="measure transcription and write the result JSON")
    run.add_argument("--out", type=Path, required=True, help="path of the result JSON")
    run.add_argument(
        "--languages",
        nargs="+",
        default=list(DEFAULT_LANGUAGES),
        choices=list(DEFAULT_LANGUAGES),
        help="languages to transcribe",
    )
    run.add_argument(
        "--audio-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "audio",
        help="directory holding <language>.wav and optional <language>.txt",
    )
    run.add_argument("--fixture-seconds", type=float, default=DEFAULT_FIXTURE_SECONDS)
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--compute-type", default=DEFAULT_COMPUTE_TYPE)
    run.add_argument("--threads", type=int, default=0, help="CPU threads; 0 uses os.cpu_count()")
    run.add_argument(
        "--download-timeout",
        type=float,
        default=DEFAULT_DOWNLOAD_TIMEOUT_S,
        help="seconds allowed for the model download",
    )
    run.add_argument("--beam-size", type=int, default=5)
    run.add_argument(
        "--stub",
        action="store_true",
        help="use a stub transcriber for a local dry run; the workflow never sets this",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not MIN_FIXTURE_SECONDS <= args.fixture_seconds <= MAX_FIXTURE_SECONDS:
        parser.error(
            f"--fixture-seconds must be between {MIN_FIXTURE_SECONDS:.0f} and "
            f"{MAX_FIXTURE_SECONDS:.0f}"
        )
    threads = args.threads if args.threads > 0 else int(os.cpu_count() or 1)
    settings = Settings(
        out=args.out,
        languages=tuple(args.languages),
        audio_dir=args.audio_dir,
        fixture_seconds=args.fixture_seconds,
        model=args.model,
        compute_type=args.compute_type,
        threads=threads,
        download_timeout_s=args.download_timeout,
        beam_size=args.beam_size,
        stub=args.stub,
    )
    opener = open_stub_model if settings.stub else open_whisper_model
    try:
        code, result = execute(settings, opener)
    except OSError as exc:
        print(f"harness error: cannot write the result ({exc})", file=sys.stderr)
        return 2
    summary = summary_markdown(result)
    print(summary)
    append_step_summary(summary)
    if code != 0:
        print(f"harness error: {result['error']['message']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
