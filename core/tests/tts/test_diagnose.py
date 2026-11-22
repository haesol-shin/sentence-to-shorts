"""The CI-only worker diagnosis: it starts the worker the way the adapter does and keeps
what the adapter drops."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from app.ports import AppError
from app.tools.device import DeviceSelection
from app.tools.tts.qwen3_tts_0_6b import diagnose
from app.tools.tts.qwen3_tts_0_6b.adapter import ENGINE_ID, WORKER_PATH
from tests.tts.support import FAKE_WORKER, make_adapter, synth

IMPORT_TIME = """\
import time: self [us] | cumulative | imported package
import time:       100 |        100 |   _io
import time:      9000 |      12000 |     torch._C
import time:       300 |      12300 |   torch
import time:      5000 |       5000 |   numpy
import time:        50 |         50 |   abc
import time:       700 |        700 |   json
import time:      2500 |       2500 |   typing
import time:        10 |         10 |   re
not an import line
"""


def worker_command(tmp_path: Path, mode: str) -> list[str]:
    return [sys.executable, str(FAKE_WORKER), "--mode", mode, "--log", str(tmp_path / "log")]


def test_diagnose_importtime_totals_and_lists_the_five_slowest_by_own_time() -> None:
    report = diagnose.parse_importtime(IMPORT_TIME)
    assert report["total_ms"] == 17.7
    assert [row["module"] for row in report["slowest"]] == [
        "torch._C", "numpy", "typing", "json", "torch",
    ]
    assert report["slowest"][0] == {"module": "torch._C", "self_us": 9000, "cumulative_us": 12000}


def test_diagnose_a_worker_that_reaches_ready_is_reported_with_its_protocol_lines(
    tmp_path: Path,
) -> None:
    argv = [*worker_command(tmp_path, "phased_load"), "--device", "cpu"]
    report = diagnose.run_worker(argv, dict(os.environ), limit_s=60)
    assert report["ready"] and not report["timed_out"]
    texts = [line["text"] for line in report["lines"]]
    assert texts[0].count("import_torch") == 1 and texts[-1] == '{"type": "ready"}'


def test_diagnose_a_worker_that_exits_before_ready_shows_its_status_and_stderr(
    tmp_path: Path,
) -> None:
    code = "import sys; sys.stderr.write('boom ' * 2000); sys.exit(7)"
    report = diagnose.run_worker([sys.executable, "-c", code], dict(os.environ), limit_s=60)
    assert (report["ready"], report["timed_out"], report["returncode"]) == (False, False, 7)
    assert report["lines"] == []
    assert report["stderr_tail"].endswith("boom ")
    assert len(report["stderr_tail"]) <= diagnose.STDERR_TAIL_BYTES


def test_diagnose_a_worker_without_any_phase_is_killed_at_the_limit(tmp_path: Path) -> None:
    argv = [*worker_command(tmp_path, "slow_load"), "--device", "cpu"]
    report = diagnose.run_worker(argv, dict(os.environ), limit_s=1.0)
    assert (report["ready"], report["timed_out"], report["returncode"]) == (False, True, None)
    assert report["lines"] == []


def test_diagnose_import_timing_runs_the_given_interpreter() -> None:
    report = diagnose.time_import_torch(sys.executable, dict(os.environ), limit_s=120)
    assert report["timed_out"] is False
    assert report["total_ms"] > 0 and 0 < len(report["slowest"]) <= diagnose.SLOWEST


def test_diagnose_the_launch_is_the_one_the_adapter_starts(tmp_path: Path) -> None:
    adapter = make_adapter(
        tmp_path, command=[sys.executable, str(WORKER_PATH)], threads=3,
        selection=DeviceSelection("cpu", "cpu", "configured"),
    )
    argv, env = adapter.worker_launch()
    assert argv[:2] == [sys.executable, str(WORKER_PATH)]
    assert argv[argv.index("--threads") + 1] == "3"
    assert argv[argv.index("--device") + 1] == "cpu"
    assert env["HF_HUB_OFFLINE"] == "1" and env["OMP_NUM_THREADS"] == "3"
    assert "APP_TTS_THREADS" not in env


def test_27_a_worker_that_exits_before_ready_is_tts_failed_with_the_status(
    tmp_path: Path,
) -> None:
    adapter = make_adapter(
        tmp_path,
        "crash_on_cuda",
        selection=DeviceSelection(requested="cuda", device="cuda", reason="configured"),
    )
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path)
    error = raised.value
    assert error.code == "tts_failed"
    assert error.detail == {
        "engine": ENGINE_ID, "reason": "worker_exited", "stage": "load", "returncode": 3,
    }
