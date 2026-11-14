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


def write_artifacts(root: Path) -> None:
    alpha = root / "tts-alpha" / "out"
    beta = root / "tts-beta" / "out"
    gamma = root / "tts-gamma" / "out"
    for out, candidate, texts, failed in (
        (alpha, "alpha", ("K1", "E1"), None),
        (beta, "beta", ("K1",), "E1"),
        (gamma, "gamma", (), "K1"),
    ):
        out.mkdir(parents=True)
        entries = []
        for text_id in texts:
            write_tone(out / "wav" / f"{text_id}.wav")
            entries.append(
                {
                    "id": text_id,
                    "language": "ko",
                    "wav": f"wav/{text_id}.wav",
                    "wav_ms": 1200.0,
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
            "status": "ok" if texts else "failed",
            "host": {"os": "Linux"},
            "engine": {"speakers": {"ko": candidate + "-ko"}},
            "texts": entries,
        }
        (out / "result.json").write_text(json.dumps(payload), encoding="utf-8")


class ListeningPackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_artifacts(self.root / "artifacts")

    def build(self, name: str, seed: int) -> dict:
        return make_listening_pack.build(
            self.root / "artifacts",
            self.root / name,
            self.root / f"{name}-key.json",
            seed,
        )

    def test_successful_candidates_are_masked_and_normalised(self) -> None:
        key = self.build("pack", 7)
        self.assertEqual([item["candidate"] for item in key["assignments"]], ["alpha", "beta"])
        self.assertEqual([item["letter"] for item in key["assignments"]], ["A", "B"])
        for item in key["assignments"]:
            for record in item["files"]:
                path = self.root / "pack" / record["out"]
                self.assertTrue(path.is_file())
                data, rate = sf.read(str(path), always_2d=True)
                self.assertEqual(data.shape[1], 1)
                self.assertEqual(rate, SAMPLE_RATE)
                loudness = pyln.Meter(rate).integrated_loudness(data[:, 0])
                self.assertAlmostEqual(loudness, -16.0, delta=0.4)

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


if __name__ == "__main__":
    unittest.main()
