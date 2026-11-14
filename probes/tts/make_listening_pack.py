#!/usr/bin/env python3
"""Build a blind listening pack from candidate artifacts.

Successful WAV files are normalised to -16 LUFS, downmixed to mono and copied
under a random letter (A, B, ...). The mapping to candidate names goes to a
separate key file that is uploaded as its own artifact.
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

TARGET_LUFS = -16.0
PEAK_CEILING = 10 ** (-1.0 / 20.0)
MAX_GAIN_DB = 30.0


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
        "os": result.get("host", {}).get("os"),
        "speakers": result.get("engine", {}).get("speakers"),
        "files": files,
    }


def _normalise(path: Path) -> tuple[np.ndarray, int, float | None, float, bool]:
    data, rate = sf.read(str(path), dtype="float64", always_2d=True)
    mono = data.mean(axis=1)
    meter = pyln.Meter(rate)
    loudness = None
    gain_db = 0.0
    if mono.size:
        measured = float(meter.integrated_loudness(mono))
        if np.isfinite(measured):
            loudness = measured
            gain_db = TARGET_LUFS - measured
    gain_db = float(np.clip(gain_db, -MAX_GAIN_DB, MAX_GAIN_DB))
    scaled = mono * (10 ** (gain_db / 20.0))
    peak = float(np.max(np.abs(scaled))) if scaled.size else 0.0
    limited = peak > PEAK_CEILING
    if limited:
        scaled = scaled * (PEAK_CEILING / peak)
        gain_db -= 20.0 * np.log10(peak / PEAK_CEILING)
    return scaled.astype(np.float32), rate, loudness, gain_db, limited


def build(root: Path, pack_dir: Path, key_path: Path, seed: int) -> dict[str, Any]:
    collected = []
    for base, result in _results(root):
        item = _collect(base, result)
        if item is not None:
            collected.append(item)
    collected.sort(key=lambda item: item["candidate"])
    random.Random(seed).shuffle(collected)
    letters = string.ascii_uppercase[: len(collected)]
    assignments = []
    for letter, item in zip(letters, collected):
        target_dir = pack_dir / letter
        target_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for text_id, source in item["files"]:
            audio, rate, loudness, gain_db, limited = _normalise(source)
            target = target_dir / f"{text_id}.wav"
            sf.write(str(target), audio, rate, subtype="PCM_16")
            records.append(
                {
                    "id": text_id,
                    "source": source.name,
                    "input_lufs": None if loudness is None else round(loudness, 2),
                    "gain_db": round(gain_db, 2),
                    "peak_limited": limited,
                    "out": f"{letter}/{target.name}",
                }
            )
        assignments.append(
            {
                "letter": letter,
                "candidate": item["candidate"],
                "os": item["os"],
                "speakers": item["speakers"],
                "files": records,
            }
        )
    key = {
        "schema": 1,
        "seed": seed,
        "target_lufs": TARGET_LUFS,
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
        print(f"{item['letter']}: {len(item['files'])} files")
    expected = max((len(item["files"]) for item in assignments), default=0)
    missing = [
        item["letter"] for item in assignments if len(item["files"]) < expected
    ]
    if missing:
        print(f"incomplete text sets: {', '.join(missing)}")
    if not assignments:
        print("no successful candidate produced audio; the pack is empty")
    return 0


if __name__ == "__main__":
    sys.exit(main())
