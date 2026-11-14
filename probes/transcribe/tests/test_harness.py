"""Unit checks for the transcription probe harness.

These checks use a stub transcriber or written fixtures, so they run on a host
without the model packages. They cover the result contract, the measurement
fields, the input contract and the rule that only a known subject error is a
result while a harness fault is not.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import harness  # noqa: E402

AUDIO_DIR = HERE.parent / "audio"


def make_settings(root: Path, **overrides) -> harness.Settings:
    values = dict(
        out=root / "result.json",
        languages=("ko", "en"),
        audio_dir=root / "audio",
        threads=2,
        download_timeout_s=5.0,
    )
    values.update(overrides)
    return harness.Settings(**values)


def write_speech(path: Path, milliseconds: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(16000 * milliseconds / 1000)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * frames)


def install_fixtures(root: Path) -> None:
    write_speech(root / "audio" / "ko.wav")
    write_speech(root / "audio" / "en.wav")


class FakeTranscriber:
    """Return one segment per language, or raise the given failure."""

    def __init__(self, texts: dict[str, str] | None = None, failure: Exception | None = None):
        self.texts = texts or {}
        self.failure = failure

    def __call__(self, settings: harness.Settings) -> harness.LoadedModel:
        def transcribe(wav: Path, language: str) -> tuple[list[dict], dict]:
            if self.failure is not None:
                raise self.failure
            duration = harness.wav_duration_ms(wav)
            text = self.texts.get(language, "")
            return (
                [{"start_ms": 0, "end_ms": duration, "text": text}],
                {"language": language, "language_probability": 0.5},
            )

        info = {
            "name": harness.MODEL_NAME,
            "revision": "test",
            "device": "cpu",
            "compute_type": harness.COMPUTE_TYPE,
            "cpu_threads": settings.threads,
            "num_workers": 1,
            "cache_hit": False,
            "download_ms": 0,
            "load_ms": 0,
            "bytes": 1,
            "file_count": 0,
            "files": [],
            "error": None,
        }
        return harness.LoadedModel(info=info, transcribe=transcribe)


class ResultContractTests(unittest.TestCase):
    def test_result_json_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_fixtures(root)
            settings = make_settings(root)
            code, result = harness.execute(settings, FakeTranscriber())

            self.assertEqual(code, 0)
            stored = json.loads(settings.out.read_text(encoding="utf-8"))
            for key in (
                "schema",
                "probe",
                "created_at",
                "status",
                "mode",
                "settings",
                "environment",
                "runtime",
                "model",
                "runs",
                "peak_rss_bytes",
                "notes",
            ):
                self.assertIn(key, stored)
            self.assertEqual(stored["status"], "ok")
            self.assertEqual([run["language"] for run in stored["runs"]], ["ko", "en"])
            self.assertEqual(result["status"], stored["status"])

    def test_stub_run_marks_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_fixtures(root)
            settings = make_settings(root)
            code, result = harness.execute(settings, harness.open_stub_model)

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["mode"], "stub")
            self.assertEqual(len(result["runs"]), 2)
            self.assertTrue(result["model"]["stub"])
            self.assertTrue(all(run["failure"] is None for run in result["runs"]))

    def test_harness_error_exits_two(self) -> None:
        def broken(settings: harness.Settings) -> harness.LoadedModel:
            raise harness.HarnessError("model package missing")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_fixtures(root)
            settings = make_settings(root)
            code, result = harness.execute(settings, broken)

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "harness_error")
            self.assertIn("model package missing", result["error"]["message"])
            stored = json.loads(settings.out.read_text(encoding="utf-8"))
            self.assertEqual(stored["status"], "harness_error")

    def test_unexpected_error_is_harness_error(self) -> None:
        for failure in (FileExistsError("cache path collision"), KeyError("bookkeeping key")):
            def broken(settings: harness.Settings) -> harness.LoadedModel:
                raise failure

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                install_fixtures(root)
                settings = make_settings(root)
                code, result = harness.execute(settings, broken)

                self.assertEqual(code, 2, failure)
                self.assertEqual(result["status"], "harness_error", failure)
                self.assertIn(type(failure).__name__, result["error"]["message"])

    def test_model_unavailable_is_recorded_as_result(self) -> None:
        def unavailable(settings: harness.Settings) -> harness.LoadedModel:
            raise harness.ModelUnavailable("model_load_failed", "RuntimeError: no int8 kernel")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_fixtures(root)
            settings = make_settings(root)
            code, result = harness.execute(settings, unavailable)

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["model"]["error"]["kind"], "model_load_failed")
            for run in result["runs"]:
                self.assertEqual(run["failure"]["kind"], "model_load_failed")
                self.assertFalse(run["word_error"]["measured"])

    def test_download_timeout_is_recorded_as_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = make_settings(Path(temporary))

            def timed_out(command, timeout_s):
                return None

            with self.assertRaises(harness.ModelUnavailable) as caught:
                harness.download_model(settings, runner=timed_out)
            self.assertEqual(caught.exception.kind, "model_download_timeout")

    def test_download_failure_is_harness_error(self) -> None:
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="connection reset")
        with tempfile.TemporaryDirectory() as temporary:
            settings = make_settings(Path(temporary))
            with self.assertRaises(harness.HarnessError):
                harness.download_model(settings, runner=lambda command, timeout_s: completed)


class MeasurementTests(unittest.TestCase):
    def test_transcription_records_time_and_peak_rss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_fixtures(root)
            settings = make_settings(root)
            _, result = harness.execute(settings, FakeTranscriber({"ko": "가짜 결과", "en": "stub"}))

            for run in result["runs"]:
                self.assertIsNotNone(run["elapsed_ms"])
                self.assertGreaterEqual(run["elapsed_ms"], 0)
                self.assertGreaterEqual(run["audio_ms"], 20000)
                self.assertLessEqual(run["audio_ms"], 40000)
                expected_rtf = round(run["elapsed_ms"] / run["audio_ms"], 4)
                self.assertEqual(run["rtf"], expected_rtf)
                if run["peak_rss_bytes"] is None:
                    self.skipTest("this platform does not report peak RSS")
                self.assertGreater(run["peak_rss_bytes"], 0)
                self.assertIn(run["peak_rss_source"], {"ru_maxrss", "psapi"})

    def test_transcription_failure_is_recorded_as_result(self) -> None:
        failure = RuntimeError("decoder exploded")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_fixtures(root)
            settings = make_settings(root)
            code, result = harness.execute(settings, FakeTranscriber(failure=failure))

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "failed")
            for run in result["runs"]:
                self.assertEqual(run["failure"]["kind"], "transcribe_failed")
                self.assertIn("decoder exploded", run["failure"]["message"])
                self.assertFalse(run["word_error"]["measured"])
                self.assertEqual(run["word_error"]["reason"], "transcription failed")

    def test_word_error_uses_reference_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install_fixtures(root)
            (root / "audio" / "ko.txt").write_text("안녕하세요 오늘 날씨", encoding="utf-8")
            (root / "audio" / "en.txt").write_text("hello there today", encoding="utf-8")
            settings = make_settings(root)
            _, result = harness.execute(
                settings,
                FakeTranscriber({"ko": "안녕하세요 오늘", "en": "hello there today"}),
            )

            by_language = {run["language"]: run for run in result["runs"]}
            korean = by_language["ko"]
            self.assertEqual(korean["fixture"]["kind"], "speech")
            self.assertEqual(korean["fixture"]["expected_text"], "안녕하세요 오늘 날씨")
            self.assertTrue(korean["word_error"]["measured"])
            self.assertEqual(korean["word_error"]["reference_words"], 3)
            self.assertEqual(korean["word_error"]["edits"], 1)
            self.assertAlmostEqual(korean["word_error"]["rate"], 1 / 3, places=4)
            self.assertEqual(by_language["en"]["word_error"]["rate"], 0.0)

    def test_missing_fixture_is_harness_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = make_settings(Path(temporary))
            code, result = harness.execute(settings, harness.open_stub_model)

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "harness_error")
            self.assertIn("missing speech fixture", result["error"]["message"])

    def test_short_fixture_is_harness_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_speech(root / "audio" / "ko.wav", 2000)
            write_speech(root / "audio" / "en.wav")
            settings = make_settings(root)
            code, result = harness.execute(settings, harness.open_stub_model)

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "harness_error")
            self.assertIn("outside", result["error"]["message"])

    def test_speech_fixture_supplies_reference_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_speech(root / "audio" / "ko.wav")
            fixture = harness.prepare_fixture(make_settings(root), "ko")

            self.assertEqual(fixture["meta"]["kind"], "speech")
            self.assertEqual(fixture["meta"]["file"], "ko.wav")
            self.assertIsNone(fixture["meta"]["expected_text"])
            self.assertEqual(fixture["duration_ms"], 24000)

    def test_committed_fixtures_are_ready(self) -> None:
        for language in ("ko", "en"):
            audio = AUDIO_DIR / f"{language}.wav"
            reference = AUDIO_DIR / f"{language}.txt"
            self.assertTrue(audio.is_file(), audio)
            self.assertTrue(reference.is_file(), reference)
            duration = harness.wav_duration_ms(audio)
            self.assertGreaterEqual(duration, 20000)
            self.assertLessEqual(duration, 40000)
            self.assertGreater(len(reference.read_text(encoding="utf-8").strip()), 20)

    def test_command_deadline_kills_the_child(self) -> None:
        started = time.monotonic()
        completed = harness.run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            0.2,
        )
        elapsed = time.monotonic() - started

        self.assertIsNone(completed)
        self.assertLess(elapsed, 10)


if __name__ == "__main__":
    unittest.main()
