#!/usr/bin/env python3
"""Measure faster-whisper small int8 transcription on a CPU.

This is probe code, not product code. It must not join the product
dependencies or the product lockfile.

The thing under test may fail: a model load or a transcription error whose
type is listed in ``SUBJECT_ERRORS``, or a model download that hits a network
or hub error or passes its deadline, is written to the result JSON as a result
and the process still exits 0, so the workflow reports it instead of failing.
Any other exception, a missing or out of range audio fixture, or an unexpected
model download failure is a harness fault: it is written as ``harness_error``
and the process exits 2.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

SCHEMA_VERSION = 1
PROBE_NAME = "transcribe"
MODEL_NAME = "small"
COMPUTE_TYPE = "int8"
BEAM_SIZE = 5
DEFAULT_LANGUAGES = ("ko", "en")
DEFAULT_DOWNLOAD_TIMEOUT_S = 1800.0
DOWNLOAD_SUBCOMMAND = "_download"
MIN_FIXTURE_MS = 20_000
MAX_FIXTURE_MS = 40_000
# Exception types that mean the thing under test failed. Anything else is a
# harness fault, so a bookkeeping error never looks like a probe result.
SUBJECT_ERRORS = (RuntimeError, ValueError)
# Network and hub failures during the model download are an external failure
# of the thing under test. Their modules raise these, and a bare connection or
# timeout error has no module of its own.
EXTERNAL_ERROR_MODULES = {"huggingface_hub", "requests", "urllib3", "httpx", "socket", "ssl", "http"}
NETWORK_ERRORS = (TimeoutError, ConnectionError)
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
    threads: int = 1
    download_timeout_s: float = DEFAULT_DOWNLOAD_TIMEOUT_S

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


def prepare_fixture(settings: Settings, language: str) -> dict:
    """Return the audio fixture for one language and its reference text."""
    speech = settings.audio_dir / f"{language}.wav"
    if not speech.is_file():
        raise HarnessError(
            f"missing speech fixture {speech.name}; see probes/transcribe/audio/README.md"
        )
    reference = settings.audio_dir / f"{language}.txt"
    expected = reference.read_text(encoding="utf-8").strip() if reference.is_file() else None
    try:
        duration = wav_duration_ms(speech)
    except (wave.Error, EOFError, OSError) as exc:
        raise HarnessError(f"{speech.name}: not a readable WAV ({exc})") from exc
    if not MIN_FIXTURE_MS <= duration <= MAX_FIXTURE_MS:
        raise HarnessError(
            f"{speech.name}: {duration / 1000:.1f} s is outside "
            f"{MIN_FIXTURE_MS // 1000} to {MAX_FIXTURE_MS // 1000} s"
        )
    meta = {
        "kind": "speech",
        "file": speech.name,
        "duration_ms": duration,
        "expected_text": expected,
    }
    return {"path": speech, "duration_ms": duration, "meta": meta}


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


def run_command(command: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess | None:
    """Run a command and kill it when the deadline passes.

    The child is a separate process, so a library that joins its own worker
    threads at interpreter exit cannot hold this process open.
    """
    try:
        return subprocess.run(command, timeout=timeout_s, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return None


def is_external_download_error(error: BaseException) -> bool:
    """Return True for a network or hub failure, which is an external result."""
    if isinstance(error, NETWORK_ERRORS):
        return True
    module = (type(error).__module__ or "").split(".")[0]
    return module in EXTERNAL_ERROR_MODULES


def download_model_to_cache(cache_dir: Path) -> int:
    """Download the model in this process; the parent runs this as a child.

    A known network or hub failure prints one JSON line and exits 0 so the
    parent can record it as a result. Any other error propagates and exits 1,
    which the parent reports as a harness fault.
    """
    try:
        import faster_whisper
    except ImportError as exc:
        print(f"faster-whisper is not installed ({exc})", file=sys.stderr)
        return 2
    try:
        path = faster_whisper.download_model(MODEL_NAME, cache_dir=str(cache_dir))
    except Exception as error:  # noqa: BLE001 - classified below
        if not is_external_download_error(error):
            raise
        print(
            json.dumps(
                {
                    "status": "failed",
                    "kind": "model_download_failed",
                    "message": f"{type(error).__name__}: {error}"[:400],
                }
            )
        )
        return 0
    print(json.dumps({"status": "ok", "path": str(path)}))
    return 0


def _last_json_object(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None
    return None


def download_model(
    settings: Settings,
    runner: Callable[[Sequence[str], float], subprocess.CompletedProcess | None] = run_command,
) -> tuple[Path, int]:
    """Download the model under a hard deadline and return (path, elapsed ms)."""
    cache_dir = settings.work_dir / "model-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        DOWNLOAD_SUBCOMMAND,
        "--cache-dir",
        str(cache_dir),
    ]
    started = time.monotonic()
    completed = runner(command, settings.download_timeout_s)
    elapsed_ms = _elapsed_ms(started)
    if completed is None:
        raise ModelUnavailable(
            "model_download_timeout",
            f"download did not finish within {settings.download_timeout_s:.0f} s",
        )
    if completed.returncode != 0:
        raise HarnessError(
            f"model download failed with exit code {completed.returncode}: "
            f"{(completed.stderr or '').strip()[-300:]}"
        )
    payload = _last_json_object(completed.stdout or "")
    if payload is None:
        raise HarnessError("model download printed no result")
    if payload.get("status") != "ok":
        kind = str(payload.get("kind") or "model_download_failed")
        message = str(payload.get("message") or "")[:400]
        raise ModelUnavailable(kind, message)
    path = payload.get("path")
    if not isinstance(path, str) or not path:
        raise HarnessError("model download printed no path")
    return Path(path), elapsed_ms


def open_whisper_model(settings: Settings) -> LoadedModel:
    """Download and load the model. Raise HarnessError only for harness faults."""
    try:
        import faster_whisper
    except ImportError as exc:
        raise HarnessError(f"faster-whisper is not installed ({exc})") from exc

    cache_dir = settings.work_dir / "model-cache"
    cache_hit = any(cache_dir.glob("models--*/snapshots/*"))
    model_path, download_ms = download_model(settings)
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
            compute_type=COMPUTE_TYPE,
            cpu_threads=settings.threads,
            num_workers=1,
            local_files_only=True,
        )
    except SUBJECT_ERRORS as exc:
        raise ModelUnavailable(
            "model_load_failed",
            f"{type(exc).__name__}: {exc}"[:400],
        ) from exc
    load_ms = _elapsed_ms(load_started)

    def transcribe(wav: Path, language: str) -> tuple[list[dict], dict]:
        segments, info = model.transcribe(
            str(wav),
            language=language,
            beam_size=BEAM_SIZE,
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
        "name": MODEL_NAME,
        "revision": revision,
        "device": "cpu",
        "compute_type": COMPUTE_TYPE,
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
        "name": MODEL_NAME,
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
    except SUBJECT_ERRORS as exc:
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
        notes.append("word error is not measured: a reference text file is missing")
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
            "model": MODEL_NAME,
            "device": "cpu",
            "compute_type": COMPUTE_TYPE,
            "cpu_threads": settings.threads,
            "num_workers": 1,
            "beam_size": BEAM_SIZE,
            "vad_filter": False,
            "condition_on_previous_text": False,
            "word_timestamps": False,
        },
        "environment": environment(),
        "runtime": installed_versions(),
        "model": model.info if model is not None else {
            "name": MODEL_NAME,
            "revision": None,
            "device": "cpu",
            "compute_type": COMPUTE_TYPE,
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
    run.add_argument("--threads", type=int, default=0, help="CPU threads; 0 uses os.cpu_count()")
    run.add_argument(
        "--download-timeout",
        type=float,
        default=DEFAULT_DOWNLOAD_TIMEOUT_S,
        help="seconds allowed for the model download",
    )
    run.add_argument(
        "--stub",
        action="store_true",
        help="use a stub transcriber for a local dry run; the workflow never sets this",
    )
    download = subcommands.add_parser(DOWNLOAD_SUBCOMMAND, help=argparse.SUPPRESS)
    download.add_argument("--cache-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == DOWNLOAD_SUBCOMMAND:
        return download_model_to_cache(args.cache_dir)
    threads = args.threads if args.threads > 0 else int(os.cpu_count() or 1)
    settings = Settings(
        out=args.out,
        languages=tuple(args.languages),
        audio_dir=args.audio_dir,
        threads=threads,
        download_timeout_s=args.download_timeout,
    )
    opener = open_stub_model if args.stub else open_whisper_model
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
