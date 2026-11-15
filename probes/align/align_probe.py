#!/usr/bin/env python3
"""Run WhisperX forced alignment on the probe script and judge every line.

The transcript is the known speech text, so no speech recognition runs here. A
line that the aligner cannot map keeps a failure reason from the contract and
loses only its phrase spans, which is the sentence-caption fallback.

Audio files are not part of the repository. The README describes how to
synthesize them with the ONNX text-to-speech probe before this script runs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import statistics
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mapping  # noqa: E402

FAILURES = (
    "align_failed",
    "align_low_confidence",
    "align_missing_words",
    "align_unavailable",
)


def load_texts(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    lines = payload["texts"]
    seen: set[str] = set()
    for line in lines:
        for key in ("id", "language", "text", "display_text"):
            if not line.get(key):
                raise SystemExit(f"texts entry misses {key}: {line!r}")
        if line["id"] in seen:
            raise SystemExit(f"duplicate text id: {line['id']}")
        seen.add(line["id"])
    if not lines:
        raise SystemExit("texts file has no texts")
    return lines


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as source:
        return math.ceil(source.getnframes() * 1000 / source.getframerate())


def audio_edges_ms(path: Path, frame_ms: int = 10, floor: float = 0.005, ratio: float = 0.02) -> dict:
    """Leading and trailing silence, measured from the WAV itself.

    The threshold is 2 percent of the loudest frame, never below -46 dBFS.
    Frame energy is RMS over 10 ms windows.
    """
    import numpy as np

    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    width = max(1, int(rate * frame_ms / 1000))
    frames = len(samples) // width
    if frames == 0:
        return {"leading_ms": 0, "trailing_ms": 0}
    rms = np.sqrt((samples[: frames * width].reshape(frames, width) ** 2).mean(axis=1))
    threshold = max(floor, float(rms.max()) * ratio)
    voiced = np.nonzero(rms > threshold)[0]
    if voiced.size == 0:
        return {"leading_ms": 0, "trailing_ms": 0}
    duration_ms = round(len(samples) * 1000 / rate)
    return {
        "leading_ms": int(voiced[0]) * frame_ms,
        "trailing_ms": duration_ms - (int(voiced[-1]) + 1) * frame_ms,
    }


def _regular_files(root: Path) -> dict[str, int]:
    files: dict[str, int] = {}
    if not root.exists():
        return files
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if not (Path(current) / name).is_symlink()]
        for name in names:
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            files[str(path)] = path.stat().st_size
    return files


def _cache_roots() -> list[Path]:
    roots = []
    hf_home = os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    roots.append(Path(hf_home))
    torch_home = os.environ.get("TORCH_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "torch")
    roots.append(Path(torch_home))
    return roots


def _cache_files() -> dict[str, int]:
    files: dict[str, int] = {}
    for root in _cache_roots():
        files.update(_regular_files(root))
    return files


def peak_rss_bytes() -> int:
    """Peak resident set size of this process.

    Linux reports kilobytes and macOS reports bytes through getrusage. Windows
    reads PeakWorkingSetSize because getrusage is unavailable there.
    """
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
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

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
        return 0
    import resource

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform.startswith("linux") else value


def _sanitize(text: str) -> str:
    """Keep failure text readable without machine paths."""
    text = re.sub(r"(?<![\w.:/])/(?:[^\s'\"]+)", "<path>", text)
    return re.sub(r"\s+", " ", text).strip()


def _align_model_name(language: str, metadata: dict) -> str | None:
    from whisperx import alignment as whisperx_alignment

    if metadata.get("type") == "torchaudio":
        return whisperx_alignment.DEFAULT_ALIGN_MODELS_TORCH.get(language)
    return whisperx_alignment.DEFAULT_ALIGN_MODELS_HF.get(language)


def _dist_version(name: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _score_summary(words: list[dict]) -> dict:
    scores = [float(word["score"]) for word in words if isinstance(word.get("score"), (int, float))]
    if not scores:
        return {"count": 0}
    return {"count": len(scores), "min": round(min(scores), 3), "median": round(statistics.median(scores), 3)}


def _stable(first: list[dict], second: list[dict]) -> bool:
    if len(first) != len(second):
        return False
    for left, right in zip(first, second):
        if (left.get("start"), left.get("end")) != (right.get("start"), right.get("end")):
            return False
    return True


def _line_result(line: dict, wav: Path, words: list[dict], speech_ms: int, align_ms: float, repeat_stable: bool) -> dict:
    outcome = mapping.judge(line["display_text"], line["text"], words, speech_ms)
    return {
        "id": line["id"],
        "language": line["language"],
        "display_text": line["display_text"],
        "speech_text": line["text"],
        "speech_ms": speech_ms,
        "align_ms": round(align_ms, 1),
        "repeat_stable": repeat_stable,
        "verdict": outcome.failure or "ok",
        "reasons": [_sanitize(reason) for reason in outcome.reasons],
        "display_phrases": outcome.display_phrases,
        "speech_phrases": outcome.speech_phrases,
        "scores": _score_summary(words),
        "silence_ms": audio_edges_ms(wav),
        "first_word_ms": round(min(word["start"] for word in words) * 1000) if words and all(
            isinstance(word.get("start"), (int, float)) for word in words
        ) else None,
        "last_word_ms": round(max(word["end"] for word in words) * 1000) if words and all(
            isinstance(word.get("end"), (int, float)) for word in words
        ) else None,
        "phrases": [
            {
                "start_char": span.start_char,
                "end_char": span.end_char,
                "start_ms": span.start_ms,
                "end_ms": span.end_ms,
                "display": line["display_text"][span.start_char : span.end_char],
            }
            for span in outcome.phrases or []
        ],
        "words": [
            {
                "word": word.get("word", ""),
                "start": word.get("start"),
                "end": word.get("end"),
                "score": word.get("score"),
            }
            for word in words
        ],
        "wav": wav.name,
    }


def _unavailable_result(line: dict, wav: Path, speech_ms: int, reason: str) -> dict:
    return {
        "id": line["id"],
        "language": line["language"],
        "display_text": line["display_text"],
        "speech_text": line["text"],
        "speech_ms": speech_ms,
        "verdict": "align_unavailable",
        "reasons": [_sanitize(reason)],
        "scores": {"count": 0},
        "silence_ms": audio_edges_ms(wav),
        "first_word_ms": None,
        "last_word_ms": None,
        "words": [],
        "phrases": [],
        "wav": wav.name,
    }


def _align_line(line: dict, wav: Path, speech_ms: int, align, model, metadata: dict, device: str, repeats: int) -> dict:
    segment = [{"text": line["text"], "start": 0.0, "end": speech_ms / 1000}]
    words: list[dict] = []
    stable = True
    align_ms = 0.0
    try:
        for attempt in range(max(1, repeats)):
            before = time.perf_counter()
            aligned = align(segment, model, metadata, str(wav), device)
            align_ms += (time.perf_counter() - before) * 1000
            current = aligned.get("word_segments") or []
            if attempt and not _stable(words, current):
                stable = False
            words = current
        return _line_result(line, wav, words, speech_ms, align_ms, stable)
    except Exception as exc:  # noqa: BLE001 - recorded as the probe result
        return {
            "id": line["id"],
            "language": line["language"],
            "display_text": line["display_text"],
            "speech_text": line["text"],
            "speech_ms": speech_ms,
            "align_ms": round(align_ms, 1),
            "repeat_stable": stable,
            "verdict": "align_failed",
            "reasons": [_sanitize(f"{type(exc).__name__}: {exc}")],
            "words": [],
            "phrases": [],
            "wav": wav.name,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--texts", default=Path(__file__).resolve().with_name("texts.json"), type=Path)
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--repeats", default=1, type=int, help="align each line this many times and compare word times")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    lines = load_texts(args.texts)
    missing = [line["id"] for line in lines if not (args.audio_dir / f"{line['id']}.wav").is_file()]
    if missing:
        print(f"missing audio files: {', '.join(missing)}", file=sys.stderr)
        return 2
    started = time.perf_counter()
    import whisperx

    cache_at_start = _cache_files()
    results_by_id: dict[str, dict] = {}
    model_records: list[dict] = []
    for language in sorted({line["language"] for line in lines}):
        language_lines = [line for line in lines if line["language"] == language]
        try:
            before = time.perf_counter()
            model, metadata = whisperx.load_align_model(language_code=language, device=args.device)
            load_ms = round((time.perf_counter() - before) * 1000, 1)
        except Exception as exc:  # noqa: BLE001 - recorded as the probe result
            reason = f"{type(exc).__name__}: {exc}"
            model_records.append(
                {
                    "language": language,
                    "model": None,
                    "kind": "unavailable",
                    "load_ms": None,
                    "downloaded_bytes": 0,
                    "error": _sanitize(reason),
                }
            )
            for line in language_lines:
                wav = args.audio_dir / f"{line['id']}.wav"
                results_by_id[line["id"]] = _unavailable_result(line, wav, wav_duration_ms(wav), reason)
            continue
        cache_at_end = _cache_files()
        model_records.append(
            {
                "language": language,
                "model": _align_model_name(language, metadata),
                "kind": metadata.get("type"),
                "load_ms": load_ms,
                "downloaded_bytes": sum(size for path, size in cache_at_end.items() if path not in cache_at_start),
            }
        )
        cache_at_start = cache_at_end
        for line in language_lines:
            wav = args.audio_dir / f"{line['id']}.wav"
            results_by_id[line["id"]] = _align_line(
                line,
                wav,
                wav_duration_ms(wav),
                whisperx.align,
                model,
                metadata,
                args.device,
                args.repeats,
            )
        del model
        import gc

        gc.collect()
    results = [results_by_id[line["id"]] for line in lines]
    peak_bytes = peak_rss_bytes()
    summary: dict[str, dict] = {}
    for language in sorted({line["language"] for line in lines}):
        language_lines = [item for item in results if item["language"] == language]
        failures = [item["verdict"] for item in language_lines if item["verdict"] != "ok"]
        summary[language] = {
            "lines": len(language_lines),
            "ok": len(language_lines) - len(failures),
            "failures": {reason: failures.count(reason) for reason in FAILURES if reason in failures},
            "align_ms": round(sum(item.get("align_ms", 0) for item in language_lines), 1),
            "model_load_ms": next(
                (record["load_ms"] for record in model_records if record["language"] == language), None
            ),
        }
    payload = {
        "schema": 1,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "processors": os.cpu_count(),
        },
        "tool": {
            "whisperx": _dist_version("whisperx"),
            "torch": _dist_version("torch"),
            "transformers": _dist_version("transformers"),
            "numpy": _dist_version("numpy"),
        },
        "audio": {"sample_rate_hz": 16000, "directory": args.audio_dir.name},
        "models": model_records,
        "model_download_bytes": sum(record["downloaded_bytes"] for record in model_records),
        "peak_rss_bytes": peak_bytes,
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "gate": "pass" if all(item["verdict"] == "ok" for item in results) else "fail",
        "summary": summary,
        "lines": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": payload["gate"], "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
