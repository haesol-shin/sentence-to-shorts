#!/usr/bin/env python3
"""Build a blind listening pack from candidate artifacts.

Successful WAV files are normalised to -16 LUFS with a -1 dBFS peak ceiling,
downmixed to mono and copied under a random letter (A, B, ...) per candidate.
Files for each runner OS sit in a subdirectory below the letter. The mapping to
candidate names goes to a separate key file that is uploaded as its own
artifact.

Short clips are measured with a smaller BS.1770 block instead of aborting the
pack. A clip whose peaks cannot be lowered enough to reach the target keeps its
measured output loudness and is marked ``target_met: false`` in the key.
"""

from __future__ import annotations

import argparse
import json
import random
import string
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.ndimage import maximum_filter1d

TARGET_LUFS = -16.0
PEAK_CEILING = 10 ** (-1.0 / 20.0)
MAX_GAIN_DB = 30.0
STANDARD_BLOCK_S = 0.4
MIN_BLOCK_S = 0.05
LIMITER_WINDOW_S = 0.005
MAX_ITERATIONS = 8
TOLERANCE_LU = 0.1


def _os_slug(result: dict[str, Any]) -> str:
    github = result.get("github") or {}
    host = result.get("host") or {}
    raw = str(github.get("runner_os") or host.get("os") or "unknown").lower()
    if "win" in raw:
        return "windows"
    if "linux" in raw:
        return "linux"
    if "mac" in raw or "darwin" in raw:
        return "macos"
    slug = "".join(character if character.isalnum() else "-" for character in raw).strip("-")
    return slug or "unknown"


def _results(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    found = []
    for path in sorted(root.rglob("result.json")):
        try:
            found.append((path.parent, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    return found


def _collect(base: Path, result: dict[str, Any]) -> dict[str, Any] | None:
    candidate = result.get("candidate")
    if not candidate:
        return None
    files = []
    for entry in result.get("texts", []):
        if entry.get("warmup") or entry.get("failure") or not entry.get("wav"):
            continue
        path = base / entry["wav"]
        if not path.is_file():
            continue
        if not entry.get("wav_ms"):
            continue
        files.append((entry["id"], path))
    if not files:
        return None
    return {
        "candidate": candidate,
        "os": _os_slug(result),
        "speakers": (result.get("engine") or {}).get("speakers"),
        "files": files,
    }


def _measure(signal: np.ndarray, rate: int) -> tuple[float | None, float | None]:
    duration = signal.size / float(rate)
    if duration < MIN_BLOCK_S:
        return None, None
    block = min(STANDARD_BLOCK_S, max(MIN_BLOCK_S, duration / 4.0))
    meter = pyln.Meter(rate, block_size=block)
    try:
        value = float(meter.integrated_loudness(signal))
    except ValueError:
        return None, block
    return (value if np.isfinite(value) else None), block


def _limit(signal: np.ndarray, rate: int, ceiling: float) -> np.ndarray:
    """Lower peaks with a smoothed look-ahead gain curve, keeping loudness."""
    window = max(1, int(round(rate * LIMITER_WINDOW_S)))
    envelope = maximum_filter1d(np.abs(signal), size=2 * window + 1, mode="nearest")
    kernel = np.ones(window, dtype=np.float64) / window
    envelope = np.convolve(envelope, kernel, mode="same")
    gain = np.minimum(1.0, ceiling / np.maximum(envelope, 1e-9))
    gain = np.convolve(gain, kernel, mode="same")
    limited = signal * np.minimum(gain, 1.0)
    peak = float(np.max(np.abs(limited))) if limited.size else 0.0
    if peak > ceiling:
        limited = np.clip(limited, -ceiling, ceiling)
    return limited


def _normalise(
    mono: np.ndarray, rate: int
) -> tuple[np.ndarray, float | None, float | None, float, bool, bool, float | None]:
    """Return audio, input LUFS, output LUFS, gain dB, limiter, target met, block seconds."""
    signal = np.asarray(mono, dtype=np.float64)
    sample_count = signal.size
    input_lufs, block = _measure(signal, rate)
    applied_db = 0.0
    limited = False
    current = input_lufs
    if input_lufs is not None:
        for _ in range(MAX_ITERATIONS):
            delta = TARGET_LUFS - current
            if abs(delta) <= TOLERANCE_LU:
                break
            delta = float(np.clip(delta, -MAX_GAIN_DB, MAX_GAIN_DB))
            signal = signal * (10 ** (delta / 20.0))
            applied_db += delta
            if float(np.max(np.abs(signal))) > PEAK_CEILING:
                signal = _limit(signal, rate, PEAK_CEILING)
                limited = True
            current, block = _measure(signal, rate)
            if current is None:
                break
    if input_lufs is None:
        peak = float(np.max(np.abs(signal))) if signal.size else 0.0
        if peak > PEAK_CEILING:
            factor = PEAK_CEILING / peak
            signal = signal * factor
            applied_db = 20.0 * np.log10(factor)
        current, block = _measure(signal, rate)
    if float(np.max(np.abs(signal))) > PEAK_CEILING:
        signal = np.clip(signal, -PEAK_CEILING, PEAK_CEILING)
        limited = True
        current, block = _measure(signal, rate)
    if signal.size != sample_count:
        raise RuntimeError("loudness processing changed the sample count")
    target_met = (
        current is not None
        and abs(current - TARGET_LUFS) <= 0.2
        and float(np.max(np.abs(signal))) <= PEAK_CEILING * 1.0001
    )
    return (
        signal.astype(np.float32),
        input_lufs,
        current,
        applied_db,
        limited,
        target_met,
        block,
    )


def build(root: Path, pack_dir: Path, key_path: Path, seed: int) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for base, result in _results(root):
        item = _collect(base, result)
        if item is None:
            continue
        grouped.setdefault(item["candidate"], {})[item["os"]] = item

    candidates = sorted(grouped)
    random.Random(seed).shuffle(candidates)
    letters = string.ascii_uppercase[: len(candidates)]
    assignments = []
    for letter, candidate in zip(letters, candidates):
        runs = []
        for os_name in sorted(grouped[candidate]):
            item = grouped[candidate][os_name]
            target_dir = pack_dir / letter / os_name
            target_dir.mkdir(parents=True, exist_ok=True)
            records = []
            for text_id, source in item["files"]:
                data, rate = sf.read(str(source), dtype="float64", always_2d=True)
                mono = data.mean(axis=1)
                (
                    audio,
                    lufs_in,
                    lufs_out,
                    gain_db,
                    limited,
                    target_met,
                    block,
                ) = _normalise(mono, rate)
                target = target_dir / f"{text_id}.wav"
                sf.write(str(target), audio, rate, subtype="PCM_16")
                records.append(
                    {
                        "id": text_id,
                        "source": source.name,
                        "input_lufs": None if lufs_in is None else round(lufs_in, 2),
                        "output_lufs": None if lufs_out is None else round(lufs_out, 2),
                        "gain_db": round(gain_db, 2),
                        "limiter": limited,
                        "target_met": target_met,
                        "block_ms": None if block is None else round(block * 1000.0, 1),
                        "out": f"{letter}/{os_name}/{target.name}",
                    }
                )
            runs.append(
                {
                    "os": os_name,
                    "speakers": item["speakers"],
                    "files": records,
                }
            )
        assignments.append(
            {
                "letter": letter,
                "candidate": candidate,
                "runs": runs,
            }
        )
    key = {
        "schema": 2,
        "seed": seed,
        "target_lufs": TARGET_LUFS,
        "peak_ceiling_dbfs": -1.0,
        "assignments": assignments,
    }
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--seed", default=None, type=int)
    args = parser.parse_args(argv)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**31)
    args.out.mkdir(parents=True, exist_ok=True)
    key = build(args.artifacts, args.out, args.key, seed)
    assignments = key["assignments"]
    print(f"listening pack: {len(assignments)} candidate(s), seed {seed}")
    for item in assignments:
        count = sum(len(run["files"]) for run in item["runs"])
        print(f"{item['letter']}: {len(item['runs'])} os, {count} files")
    expected = max(
        (len(run["files"]) for item in assignments for run in item["runs"]), default=0
    )
    missing = [
        item["letter"]
        for item in assignments
        for run in item["runs"]
        if len(run["files"]) < expected
    ]
    if missing:
        print(f"incomplete text sets: {', '.join(sorted(set(missing)))}")
    if not assignments:
        print("no successful candidate produced audio; the pack is empty")
    return 0


if __name__ == "__main__":
    sys.exit(main())
