"""Tests for the shared measurement harness."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

PROBES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROBES / "common"))

import harness  # noqa: E402

TEXTS = {
    "texts": [
        {"id": "K1", "language": "ko", "text": "첫 문장입니다."},
        {"id": "E1", "language": "en", "text": "One sentence."},
    ]
}
SAMPLE_RATE = 8000


class StubEngine:
    candidate = "stub"
    speakers = {"ko": "stub-ko", "en": "stub-en"}
    notes = {"backend": "stub"}

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls = 0

    def load(self) -> None:
        if self.mode == "load":
            raise RuntimeError("stub load failure")

    def synthesize(self, text: str, language: str, wav_path: Path) -> dict:
        self.calls += 1
        if self.mode == "synth" or (self.mode == "synth_after_warmup" and self.calls > 1):
            raise RuntimeError("stub synthesis failure")
        frames = int(SAMPLE_RATE * 0.2)
        t = np.arange(frames) / SAMPLE_RATE
        sf.write(str(wav_path), 0.1 * np.sin(2 * np.pi * 220 * t), SAMPLE_RATE, subtype="PCM_16")
        return {"note": language}

    def close(self) -> None:
        pass


class FakeClock:
    """Advance a fixed step on every read so a synthesis budget is deterministic."""

    def __init__(self, step: float = 0.1) -> None:
        self.step = step
        self.now = 0.0

    def __call__(self) -> float:
        self.now += self.step
        return self.now


class HarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "texts.json").write_text(json.dumps(TEXTS, ensure_ascii=False), encoding="utf-8")
        (self.root / "models.json").write_text(json.dumps({"models": []}), encoding="utf-8")
        (self.root / "models").mkdir()

    def run_engine(self, mode: str = "ok", budget: float | None = None) -> tuple[int, dict]:
        out = self.root / "out"
        argv = [
            "--texts",
            str(self.root / "texts.json"),
            "--out",
            str(out),
            "--threads",
            "2",
            "--models",
            str(self.root / "models"),
            "--models-spec",
            str(self.root / "models.json"),
            "--repeats",
            "2",
            "--timeout",
            "30",
        ]
        if budget is not None:
            argv += ["--synth-budget", str(budget)]
        code = harness.run_engine(lambda _threads: StubEngine(mode), argv)
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        return code, result

    def test_measurement_writes_timed_result(self) -> None:
        code, result = self.run_engine()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["failure"])
        self.assertEqual(result["thread"], 2)
        self.assertGreaterEqual(result["cold_start_ms"], 0)
        self.assertIsNotNone(result["first_wav_ms"])
        self.assertGreaterEqual(result["first_wav_ms"], result["cold_start_ms"])
        self.assertGreaterEqual(result["first_wav_ms"], result["warmup_synth_ms"])
        self.assertEqual(result["sample_rate"], SAMPLE_RATE)
        self.assertGreater(result["rtf"], 0)
        self.assertGreater(result["peak_rss_bytes"], 0)
        self.assertEqual([entry["id"] for entry in result["texts"]], ["K1", "E1"])
        for entry in result["texts"]:
            self.assertEqual(entry["speaker"], StubEngine.speakers[entry["language"]])
            self.assertEqual(len(entry["runs"]), 2)
            self.assertAlmostEqual(entry["wav_ms"], 200.0, places=1)
            self.assertGreater(entry["rtf"], 0)
            self.assertTrue((self.root / "out" / entry["wav"]).is_file())
        self.assertTrue((self.root / "out" / "wav" / "K1.warmup.wav").is_file())

    def test_fixed_script_covers_every_planned_text(self) -> None:
        payload = json.loads((PROBES / "texts.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [item["id"] for item in payload["texts"]],
            ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "E1", "E2"],
        )
        languages = {item["id"]: item["language"] for item in payload["texts"]}
        self.assertEqual({languages[f"K{i}"] for i in range(1, 9)}, {"ko"})
        self.assertEqual({languages["E1"], languages["E2"]}, {"en"})

    def test_engine_load_failure_is_a_result(self) -> None:
        code, result = self.run_engine("load")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["stage"], "load")
        self.assertIn("stub load failure", result["failure"]["message"])

    def test_engine_synthesis_failure_is_a_result(self) -> None:
        code, result = self.run_engine("synth")
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["stage"], "synthesize")
        self.assertIn("stub synthesis failure", result["failure"]["message"])

    def test_synth_budget_stops_with_a_partial_result(self) -> None:
        clock = FakeClock()
        with mock.patch.object(harness.time, "perf_counter", clock):
            code, result = self.run_engine(budget=0.25)
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["synth_budget_s"], 0.25)
        self.assertIsNone(result["failure"])
        self.assertEqual(result["stopped_early"]["reason"], "synth_budget")
        self.assertEqual([entry["id"] for entry in result["texts"]], ["K1", "E1"])
        first, second = result["texts"]
        self.assertIsNone(first["failure"])
        self.assertIsNone(first["skipped"])
        self.assertEqual(first["wav"], "wav/K1.wav")
        self.assertTrue((self.root / "out" / first["wav"]).is_file())
        self.assertIsNone(second["failure"])
        self.assertEqual(second["skipped"]["code"], "total_timeout")
        self.assertIsNone(second["wav"])
        self.assertAlmostEqual(result["synth_spent_s"], 0.3, places=1)

    def test_synth_budget_stops_before_the_first_measured_call(self) -> None:
        clock = FakeClock()
        with mock.patch.object(harness.time, "perf_counter", clock):
            code, result = self.run_engine(budget=0.05)
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "failed")
        self.assertEqual([entry["id"] for entry in result["texts"]], ["K1"])
        self.assertEqual(result["failure"]["code"], "total_timeout")
        self.assertEqual(result["texts"][0]["skipped"]["code"], "total_timeout")
        self.assertIsNone(result["texts"][0]["runs"][0]["wall_ms"])
        self.assertTrue((self.root / "out" / "wav" / "K1.warmup.wav").is_file())

    def test_synth_budget_charges_a_failed_attempt(self) -> None:
        clock = FakeClock()
        with mock.patch.object(harness.time, "perf_counter", clock):
            code, result = self.run_engine("synth_after_warmup", budget=0.15)
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "partial")
        self.assertAlmostEqual(result["synth_spent_s"], 0.2, places=1)
        self.assertEqual([entry["id"] for entry in result["texts"]], ["K1", "E1"])
        self.assertEqual(result["texts"][0]["failure"]["code"], "synthesize_failed")
        self.assertEqual(result["texts"][1]["skipped"]["code"], "total_timeout")


if __name__ == "__main__":
    unittest.main()
