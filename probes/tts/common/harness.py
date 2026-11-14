"""Measure one TTS candidate: cold start, first WAV, RTF, peak RSS and sizes.

The candidate scripts under ``probes/tts/<candidate>/`` implement an Engine and
call ``main`` from here. The measured facts land in ``result.json`` next to the
WAV files. A failure of the engine under test is a result; a bug in this file is
a harness error.

Exit codes:
    0  every planned text was attempted, whatever the engine did
    3  a stage exceeded its timeout; ``result.json`` holds the timeout failure
    any other non-zero value is a harness error; no usable result
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import threading
import time
import traceback
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = 1
DEFAULT_REPEATS = 3
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_LOAD_TIMEOUT_S = 900.0
RSS_INTERVAL_S = 0.05


class Engine(Protocol):
    """A candidate adapter. One instance per process."""

    candidate: str
    speakers: dict[str, str]
    notes: dict[str, Any]

    def load(self) -> None:
        """Load the model and leave the engine ready for the first call."""

    def synthesize(self, text: str, language: str, wav_path: Path) -> dict[str, Any] | None:
        """Write a mono PCM16 WAV and return optional extra facts."""

    def close(self) -> None:
        """Release the model. Called once, also after a failure."""


def model_notes(engine: Engine) -> dict[str, Any]:
    """Return engine facts that are JSON serialisable."""
    notes = dict(getattr(engine, "notes", {}) or {})
    notes.setdefault("speakers", dict(engine.speakers))
    return notes


def dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def wav_duration_ms(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
        if rate <= 0:
            return 0.0
        return frames * 1000.0 / rate


def wav_facts(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as handle:
        return {
            "sample_rate": handle.getframerate(),
            "channels": handle.getnchannels(),
            "sample_width": handle.getsampwidth(),
            "frames": handle.getnframes(),
            "bytes": path.stat().st_size,
        }


def _read_first(path: str, key: str, separator: str) -> str | None:
    """Read the first matching ``key`` line from a Linux style text file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                name, sep, value = line.partition(separator)
                if sep and name.strip() == key:
                    return value.strip()
    except OSError:
        return None
    return None


def cpu_model() -> str:
    if platform.system() == "Linux":
        for key in ("model name", "Processor", "Hardware", "cpu model"):
            value = _read_first("/proc/cpuinfo", key, ":")
            if value:
                return value
    return (
        os.environ.get("PROCESSOR_IDENTIFIER")
        or platform.processor()
        or platform.machine()
        or "unknown"
    )


def os_name() -> str:
    if platform.system() == "Linux":
        value = _read_first("/etc/os-release", "PRETTY_NAME", "=")
        if value:
            return value.strip('"')
    return platform.system()


def os_version() -> str:
    return platform.version()


def ram_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:
        return None


def cpu_count() -> int | None:
    return os.cpu_count()


def host_info() -> dict[str, Any]:
    return {
        "os": os_name(),
        "os_family": platform.system(),
        "os_version": os_version(),
        "machine": platform.machine(),
        "cpu": cpu_model(),
        "cpus": cpu_count(),
        "ram_bytes": ram_bytes(),
        "python": platform.python_version(),
    }


def package_versions(names: Sequence[str]) -> dict[str, str]:
    from importlib import metadata

    found: dict[str, str] = {}
    for name in names:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return found


_WRITE_LOCK = threading.Lock()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with _WRITE_LOCK:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)


class RssSampler:
    """Sample the RSS of this process and its children until stopped."""

    def __init__(self, interval_s: float = RSS_INTERVAL_S) -> None:
        self.interval_s = interval_s
        self.peak_bytes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process = None

    def _run(self) -> None:
        import psutil

        process = self._process
        while True:
            total = 0
            try:
                total += process.memory_info().rss
                for child in process.children(recursive=True):
                    try:
                        total += child.memory_info().rss
                    except psutil.Error:
                        continue
            except psutil.Error:
                pass
            if total > self.peak_bytes:
                self.peak_bytes = total
            if self._stop.wait(self.interval_s):
                break

    def start(self) -> None:
        import psutil

        self._process = psutil.Process()
        self._thread = threading.Thread(target=self._run, name="rss-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> int:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return self.peak_bytes


class Watchdog:
    """End the process when a stage overruns, after writing the failure."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._deadline: float | None = None
        self._stage = ""
        self._handler: Callable[[str, float], None] | None = None
        self._fired = False
        self._thread = threading.Thread(target=self._run, name="watchdog", daemon=True)
        self._thread.start()

    def on_timeout(self, handler: Callable[[str, float], None]) -> None:
        self._handler = handler

    def arm(self, seconds: float, stage: str) -> None:
        with self._lock:
            self._deadline = time.monotonic() + seconds
            self._stage = stage
            self._fired = False

    def disarm(self) -> None:
        with self._lock:
            self._deadline = None
            self._stage = ""

    def _run(self) -> None:
        while True:
            time.sleep(0.05)
            with self._lock:
                deadline = self._deadline
                stage = self._stage
                fired = self._fired
            if deadline is None or fired:
                continue
            if time.monotonic() < deadline:
                continue
            with self._lock:
                self._fired = True
            if self._handler is not None:
                self._handler(stage, deadline)
            os._exit(3)


def load_texts(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload["texts"]
    seen: set[str] = set()
    for item in items:
        for key in ("id", "language", "text"):
            if not item.get(key):
                raise SystemExit(f"texts file entry misses {key}: {item!r}")
        if item["id"] in seen:
            raise SystemExit(f"duplicate text id: {item['id']}")
        seen.add(item["id"])
    if not items:
        raise SystemExit("texts file has no texts")
    return items


def load_models(spec_path: Path, root: Path) -> list[dict[str, Any]]:
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    models = []
    for entry in payload["models"]:
        local = root / entry["local_dir"]
        models.append(
            {
                "repo_id": entry["repo_id"],
                "revision": entry["revision"],
                "local_dir": entry["local_dir"],
                "present": local.is_dir(),
                "bytes": dir_size_bytes(local) if local.is_dir() else 0,
            }
        )
    return models


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--texts", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--threads", required=True, type=int)
    parser.add_argument(
        "--models",
        default=os.environ.get("PROBE_MODELS_DIR", ".local/probe/models"),
        type=Path,
        help="directory holding the downloaded model snapshots",
    )
    parser.add_argument(
        "--models-spec",
        default=None,
        type=Path,
        help="candidate models.json; defaults to the sibling of the calling script",
    )
    parser.add_argument("--repeats", default=DEFAULT_REPEATS, type=int)
    parser.add_argument("--timeout", default=DEFAULT_TIMEOUT_S, type=float)
    parser.add_argument("--load-timeout", default=DEFAULT_LOAD_TIMEOUT_S, type=float)
    parser.add_argument("--result", default=None, type=Path)
    return parser.parse_args(argv)


def _start_ms() -> tuple[float, str]:
    raw = os.environ.get("PROBE_START_MS")
    now_ms = time.time() * 1000.0
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = None
        if value is not None and 0 <= now_ms - value <= 6 * 3600 * 1000:
            return value, "process_start"
    return now_ms, "script_start"


def run_engine(
    engine_factory: Callable[[int], Engine],
    argv: Sequence[str] | None = None,
    package_names: Sequence[str] = (),
) -> int:
    """Run one candidate and write ``result.json``. See the module exit codes."""
    args = parse_args(argv)
    out_dir: Path = args.out
    wav_dir = out_dir / "wav"
    scratch_dir = out_dir / "tmp"
    wav_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.result or (out_dir / "result.json")
    models_spec = args.models_spec or Path(sys.argv[0]).resolve().with_name("models.json")

    started_at_ms, start_source = _start_ms()
    texts = load_texts(args.texts)
    engine = engine_factory(args.threads)

    result: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "candidate": engine.candidate,
        "status": "running",
        "failure": None,
        "host": host_info(),
        "thread": args.threads,
        "repeats": args.repeats,
        "timeout_s": args.timeout,
        "revision": None,
        "models": load_models(models_spec, args.models),
        "model_bytes": 0,
        "env_bytes": dir_size_bytes(Path(sys.prefix)),
        "engine": model_notes(engine),
        "packages": package_versions(package_names),
        "cold_start_ms": None,
        "first_wav_ms": None,
        "sample_rate": None,
        "rtf": None,
        "peak_rss_bytes": None,
        "texts": [],
        "started_at_ms": round(started_at_ms),
        "cold_start_source": start_source,
        "github": {
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "runner_os": os.environ.get("RUNNER_OS"),
            "runner_name": os.environ.get("RUNNER_NAME"),
            "event": os.environ.get("GITHUB_EVENT_NAME"),
        },
    }
    if result["models"]:
        result["revision"] = result["models"][0]["revision"]
        result["model_bytes"] = sum(item["bytes"] for item in result["models"])

    sampler = RssSampler()
    watchdog = Watchdog()
    finished = threading.Lock()

    def finish(failure: dict[str, Any] | None = None) -> None:
        with finished:
            if result["status"] != "running":
                return
            if failure is not None:
                result["failure"] = failure
            measured = [entry for entry in result["texts"] if not entry.get("warmup")]
            failures = [entry for entry in measured if entry["failure"] is not None]
            if result["failure"] is not None or result["texts"] and not measured:
                result["status"] = "failed"
            elif failures and len(failures) == len(measured):
                result["status"] = "failed"
                result["failure"] = failures[0]["failure"]
            elif failures:
                result["status"] = "partial"
                result["failure"] = failures[0]["failure"]
            else:
                result["status"] = "ok"
            result["peak_rss_bytes"] = sampler.stop()
            _write_json(result_path, result)

    def timed_out(stage: str, _deadline: float) -> None:
        finish(
            {
                "stage": stage,
                "code": "timeout",
                "message": f"{stage} exceeded its timeout",
                "timeout_s": result["timeout_s"] if stage == "synthesize" else args.load_timeout,
            }
        )

    watchdog.on_timeout(timed_out)
    sampler.start()

    def record(stage: str, exc: BaseException) -> dict[str, Any]:
        return {
            "stage": stage,
            "code": f"{stage}_failed",
            "type": type(exc).__name__,
            "message": str(exc)[:2000],
            "traceback": traceback.format_exc(limit=8)[-4000:],
        }

    try:
        watchdog.arm(args.load_timeout, "load")
        engine.load()
        watchdog.disarm()
    except BaseException as exc:  # noqa: BLE001 - engine failures are results
        watchdog.disarm()
        finish(record("load", exc))
        try:
            engine.close()
        except Exception:
            pass
        return 0
    result["cold_start_ms"] = round(time.time() * 1000.0 - started_at_ms, 1)
    _write_json(result_path, result)

    first = texts[0]
    warmup_path = wav_dir / f"{first['id']}.warmup.wav"
    try:
        watchdog.arm(args.timeout, "synthesize")
        started = time.perf_counter()
        engine.synthesize(first["text"], first["language"], warmup_path)
        result["warmup_synth_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        result["first_wav_ms"] = round(time.time() * 1000.0 - started_at_ms, 1)
        result["sample_rate"] = wav_facts(warmup_path)["sample_rate"]
        watchdog.disarm()
    except BaseException as exc:  # noqa: BLE001 - engine failures are results
        watchdog.disarm()
        failure = record("synthesize", exc)
        result["texts"].append(
            {
                "id": first["id"],
                "language": first["language"],
                "speaker": engine.speakers.get(first["language"]),
                "warmup": True,
                "failure": failure,
            }
        )
        finish(failure)
        try:
            engine.close()
        except Exception:
            pass
        return 0
    _write_json(result_path, result)

    total_wall = 0.0
    total_audio = 0.0
    for item in texts:
        entry: dict[str, Any] = {
            "id": item["id"],
            "language": item["language"],
            "speaker": engine.speakers.get(item["language"]),
            "text": item["text"],
            "wav": None,
            "wav_ms": None,
            "runs": [],
            "rtf": None,
            "failure": None,
        }
        for repeat in range(1, args.repeats + 1):
            keep = repeat == 1
            target = wav_dir / f"{item['id']}.wav" if keep else scratch_dir / f"{item['id']}-{repeat}.wav"
            run: dict[str, Any] = {"repeat": repeat, "wall_ms": None, "wav_ms": None, "rtf": None}
            try:
                watchdog.arm(args.timeout, "synthesize")
                started = time.perf_counter()
                extra = engine.synthesize(item["text"], item["language"], target)
                wall_ms = (time.perf_counter() - started) * 1000.0
                watchdog.disarm()
                duration_ms = wav_duration_ms(target)
                run["wall_ms"] = round(wall_ms, 1)
                run["wav_ms"] = round(duration_ms, 1)
                run["rtf"] = round(wall_ms / duration_ms, 4) if duration_ms > 0 else None
                if extra:
                    run["engine"] = extra
                total_wall += wall_ms
                total_audio += duration_ms
                if keep:
                    facts = wav_facts(target)
                    entry["wav"] = f"wav/{target.name}"
                    entry["wav_ms"] = run["wav_ms"]
                    entry["sample_rate"] = facts["sample_rate"]
                    entry["channels"] = facts["channels"]
                    entry["wav_bytes"] = facts["bytes"]
                else:
                    target.unlink(missing_ok=True)
            except BaseException as exc:  # noqa: BLE001 - engine failures are results
                watchdog.disarm()
                run["failure"] = record("synthesize", exc)
                entry["failure"] = run["failure"]
                target.unlink(missing_ok=True)
            entry["runs"].append(run)
            _write_json(result_path, result)
            if entry["failure"] is not None:
                break
        successful = [run for run in entry["runs"] if run["rtf"] is not None]
        if successful:
            entry["rtf"] = round(
                sum(run["wall_ms"] for run in successful)
                / sum(run["wav_ms"] for run in successful),
                4,
            )
        result["texts"].append(entry)
        _write_json(result_path, result)

    if total_audio > 0:
        result["rtf"] = round(total_wall / total_audio, 4)
    try:
        engine.close()
    except Exception as exc:  # noqa: BLE001 - close failures do not invalidate measurements
        result["close_failure"] = record("close", exc)
    finish()
    return 0


def main(
    engine_factory: Callable[[int], Engine],
    package_names: Sequence[str] = (),
) -> int:
    return run_engine(engine_factory, sys.argv[1:], package_names)
