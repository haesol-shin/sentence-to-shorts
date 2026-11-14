"""Tests for the blind listening pack builder."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

PROBES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROBES))

import make_listening_pack  # noqa: E402

SAMPLE_RATE = 24000


def write_tone(path: Path, seconds: float = 1.2, channels: int = 1) -> None:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    tone = 0.05 * np.sin(2 * np.pi * 330 * t)
    data = np.stack([tone] * channels, axis=1) if channels > 1 else tone
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, SAMPLE_RATE, subtype="PCM_16")


def write_high_crest(path: Path) -> None:
    seconds = 2.0
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    signal = 0.03 * np.sin(2 * np.pi * 300 * t)
    for start in np.arange(0, seconds, 0.25):
        index = int(start * SAMPLE_RATE)
        end = min(index + int(0.01 * SAMPLE_RATE), signal.size)
        signal[index:end] += 0.8
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), signal, SAMPLE_RATE, subtype="PCM_16")


def write_result(
    root: Path,
    name: str,
    candidate: str,
    runner_os: str,
    wavs: dict[str, Path],
    failed: str | None = None,
) -> None:
    out = root / name / "probe-out"
    out.mkdir(parents=True)
    entries = []
    for text_id, source in wavs.items():
        target = out / "wav" / f"{text_id}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        entries.append(
            {
                "id": text_id,
                "language": "ko",
                "wav": f"wav/{text_id}.wav",
                "wav_ms": sf.info(str(target)).duration * 1000.0,
                "failure": None,
            }
        )
    if failed is not None:
        entries.append(
            {
                "id": failed,
                "language": "en",
                "wav": None,
                "wav_ms": None,
                "failure": {"stage": "synthesize", "code": "synthesize_failed"},
            }
        )
    payload = {
        "candidate": candidate,
        "status": "ok" if wavs else "failed",
        "host": {"os": "Linux" if runner_os == "Linux" else "Windows"},
        "github": {"runner_os": runner_os},
        "engine": {"speakers": {"ko": candidate + "-ko"}},
        "texts": entries,
    }
    (out / "result.json").write_text(json.dumps(payload), encoding="utf-8")


class ListeningPackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "artifacts"
        tones = self.root / "tones"
        write_tone(tones / "K1.wav")
        write_tone(tones / "E1.wav")
        write_result(
            self.artifacts, "tts-alpha-linux", "alpha", "Linux", {"K1": tones / "K1.wav", "E1": tones / "E1.wav"}
        )
        write_result(
            self.artifacts, "tts-alpha-windows", "alpha", "Windows", {"K1": tones / "K1.wav"}
        )
        write_result(
            self.artifacts, "tts-beta-linux", "beta", "Linux", {"K1": tones / "K1.wav"}, failed="E1"
        )
        write_result(self.artifacts, "tts-gamma-linux", "gamma", "Linux", {}, failed="K1")

    def build(self, name: str, seed: int) -> dict:
        return make_listening_pack.build(
            self.artifacts,
            self.root / name,
            self.root / f"{name}-key.json",
            seed,
        )

    def test_letter_is_assigned_once_per_candidate(self) -> None:
        key = self.build("pack", 7)
        self.assertEqual([item["candidate"] for item in key["assignments"]], ["alpha", "beta"])
        self.assertEqual([item["letter"] for item in key["assignments"]], ["A", "B"])
        alpha = key["assignments"][0]
        self.assertEqual([run["os"] for run in alpha["runs"]], ["linux", "windows"])
        self.assertTrue((self.root / "pack" / "A" / "linux" / "K1.wav").is_file())
        self.assertTrue((self.root / "pack" / "A" / "windows" / "K1.wav").is_file())

    def test_successful_candidates_are_normalised(self) -> None:
        key = self.build("pack", 7)
        for item in key["assignments"]:
            for run in item["runs"]:
                for record in run["files"]:
                    path = self.root / "pack" / record["out"]
                    data, rate = sf.read(str(path), always_2d=True)
                    self.assertEqual(data.shape[1], 1)
                    self.assertEqual(rate, SAMPLE_RATE)
                    loudness = pyln.Meter(rate).integrated_loudness(data[:, 0])
                    self.assertAlmostEqual(loudness, -16.0, delta=0.4)
                    self.assertTrue(record["target_met"])

    def test_failed_candidate_is_skipped(self) -> None:
        key = self.build("pack", 11)
        self.assertNotIn("gamma", [item["candidate"] for item in key["assignments"]])

    def test_same_seed_maps_the_same_way(self) -> None:
        first = self.build("one", 42)
        second = self.build("two", 42)
        self.assertEqual(
            [(item["letter"], item["candidate"]) for item in first["assignments"]],
            [(item["letter"], item["candidate"]) for item in second["assignments"]],
        )
        self.assertEqual(
            sorted(path.name for path in (self.root / "one").iterdir()),
            sorted(path.name for path in (self.root / "two").iterdir()),
        )

    def test_pack_does_not_contain_candidate_names(self) -> None:
        self.build("pack", 3)
        names = {path.name for path in (self.root / "pack").rglob("*")}
        for candidate in ("alpha", "beta"):
            self.assertNotIn(candidate, names)


class ShortAndLoudAudioTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifacts = self.root / "artifacts"

    def test_short_clip_does_not_stop_other_candidates(self) -> None:
        tones = self.root / "tones"
        write_tone(tones / "K1.wav", seconds=1.2)
        write_tone(tones / "K7.wav", seconds=0.2)
        write_result(self.artifacts, "tts-short", "short", "Linux", {"K1": tones / "K1.wav", "K7": tones / "K7.wav"})
        write_result(self.artifacts, "tts-long", "long", "Linux", {"K1": tones / "K1.wav"})
        key = make_listening_pack.build(
            self.artifacts, self.root / "pack", self.root / "key.json", 5
        )
        self.assertEqual(len(key["assignments"]), 2)
        short = next(item for item in key["assignments"] if item["candidate"] == "short")
        files = {record["id"]: record for record in short["runs"][0]["files"]}
        self.assertIsNotNone(files["K7"]["block_ms"])
        self.assertLessEqual(files["K7"]["block_ms"], 50.0)
        data, _rate = sf.read(str(self.root / "pack" / files["K7"]["out"]))
        self.assertAlmostEqual(data.size, int(0.2 * SAMPLE_RATE), delta=2)
        self.assertTrue((self.root / "key.json").is_file())

    def test_peak_limited_clip_keeps_target_loudness(self) -> None:
        tones = self.root / "tones"
        write_high_crest(tones / "K1.wav")
        write_result(self.artifacts, "tts-loud", "loud", "Linux", {"K1": tones / "K1.wav"})
        key = make_listening_pack.build(
            self.artifacts, self.root / "pack", self.root / "key.json", 9
        )
        record = key["assignments"][0]["runs"][0]["files"][0]
        self.assertTrue(record["limiter"])
        self.assertTrue(record["target_met"])
        data, rate = sf.read(str(self.root / "pack" / record["out"]))
        self.assertLessEqual(float(np.max(np.abs(data))), 0.893)
        self.assertAlmostEqual(pyln.Meter(rate).integrated_loudness(data), -16.0, delta=0.3)


if __name__ == "__main__":
    unittest.main()
