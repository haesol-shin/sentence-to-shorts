"""The CI-only worker diagnosis: it starts the worker the way the adapter does and keeps
what the adapter drops."""

from __future__ import annotations

import importlib.util
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


def synth_report(tmp_path: Path, mode: str, limit_s: float = 60) -> dict:
    argv = [*worker_command(tmp_path, mode), "--device", "cpu"]
    request = {
        "text": "t", "language": "Korean", "speaker": "Sohee", "seed": 0, "speed": 1.0,
        "out": str(tmp_path / "out.wav"),
    }
    report = diagnose.run_worker(
        argv, dict(os.environ), limit_s=60, request=request, synth_limit_s=limit_s
    )
    return report["synth"]


def test_diagnose_a_request_after_ready_is_timed_from_write_to_answer(tmp_path: Path) -> None:
    synth = synth_report(tmp_path, "ok")
    assert synth["sent"] and synth["answered"] and not synth["timed_out"]
    assert synth["written_at"] <= synth["first_reply_at"] <= synth["done_at"]
    assert synth["received_at"] is not None
    assert '"type": "done"' in synth["answer"]
    assert (tmp_path / "out.wav").is_file()


def test_diagnose_a_request_the_worker_never_reads_has_no_first_reply(tmp_path: Path) -> None:
    synth = synth_report(tmp_path, "deaf", limit_s=1.0)
    assert synth["sent"] and synth["timed_out"] and not synth["answered"]
    assert synth["first_reply_at"] is None and synth["received_at"] is None


def test_diagnose_a_request_stuck_in_the_model_is_received_but_not_answered(
    tmp_path: Path,
) -> None:
    synth = synth_report(tmp_path, "hang", limit_s=1.0)
    assert synth["timed_out"] and not synth["answered"]
    assert synth["received_at"] is not None and synth["done_at"] is None


def test_diagnose_a_worker_that_dies_on_the_request_is_not_called_a_timeout(
    tmp_path: Path,
) -> None:
    synth = synth_report(tmp_path, "crash")
    assert synth["worker_exited"] and not synth["timed_out"] and not synth["answered"]


def test_diagnose_without_a_request_the_report_has_no_synth_part(tmp_path: Path) -> None:
    argv = [*worker_command(tmp_path, "ok"), "--device", "cpu"]
    assert "synth" not in diagnose.run_worker(argv, dict(os.environ), limit_s=60)


def test_diagnose_the_request_carries_the_voice_of_the_installed_manifest(
    tmp_path: Path,
) -> None:
    manifest = Path(diagnose.__file__).parents[3] / "plugins/voices/sohee_ko/manifest.json"
    request = diagnose.synth_request(manifest, tmp_path / "a.wav")
    assert request == {
        "text": diagnose.SENTENCE, "language": "Korean", "speaker": "Sohee", "seed": 0,
        "speed": 1.0, "out": str(tmp_path / "a.wav"),
    }


def test_diagnose_the_sentence_is_the_line_of_the_installed_voice_probe() -> None:
    path = Path(__file__).resolve().parents[3] / "packaging" / "voice_probe.py"
    spec = importlib.util.spec_from_file_location("voice_probe_under_test", path)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    assert diagnose.SENTENCE == probe.LINE


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
