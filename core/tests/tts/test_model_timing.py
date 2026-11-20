"""Opt-in pytest plugin for timing real synthesis in the model suite."""

from __future__ import annotations

import os
from functools import wraps
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import pytest

from app.tools.tts.qwen3_tts_0_6b.adapter import Qwen3TtsAdapter


def _timed(synthesize, summary: Path):
    call = 0

    @wraps(synthesize)
    def wrapped(self, text, language, voice, *, out_dir, cancel):
        nonlocal call
        call += 1
        started = perf_counter()
        status = "failed"
        try:
            result = synthesize(self, text, language, voice, out_dir=out_dir, cancel=cancel)
            status = "ok"
            return result
        finally:
            elapsed = perf_counter() - started
            with summary.open("a", encoding="utf-8") as out:
                out.write(f"| {call} | {language} | {elapsed:.3f} | {status} |\n")

    return wrapped


class _RequiredModelTests:
    """A missing model or skipped real test cannot make the scheduled run green."""

    skipped = False

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.skipped |= report.skipped

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.skipped and exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_configure(config: pytest.Config) -> None:
    summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
    with summary.open("a", encoding="utf-8") as out:
        out.write("## TTS synthesis wall time\n\n")
        out.write("One row per adapter call, including model startup when needed.\n\n")
        out.write("| Sentence call | Language | Seconds | Outcome |\n|---:|---|---:|---|\n")
    instrument = patch.object(
        Qwen3TtsAdapter, "synthesize", _timed(Qwen3TtsAdapter.synthesize, summary)
    )
    instrument.start()
    config.add_cleanup(instrument.stop)
    config.pluginmanager.register(_RequiredModelTests())


def test_model_timing_records_failed_call_without_its_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    ticks = iter((10.0, 10.25))
    monkeypatch.setitem(_timed.__globals__, "perf_counter", lambda: next(ticks))

    def fail(*args, **kwargs):
        raise RuntimeError("secret sentence")

    wrapped = _timed(fail, summary)
    with pytest.raises(RuntimeError, match="secret sentence"):
        wrapped(None, "secret sentence", "en", None, out_dir=tmp_path, cancel=None)
    assert summary.read_text(encoding="utf-8") == "| 1 | en | 0.250 | failed |\n"
