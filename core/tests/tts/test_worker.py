"""The real worker script and adapter over a stand-in model library.

A stand-in `qwen_tts` module records how the worker loads the model and what it asks
for. torch, numpy, soundfile and librosa are the real packages, so the thread limit,
the seed, the WAV the worker writes and the speed change are the real ones.
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import pytest

from app.ports import AppError
from app.tools.device import DeviceSelection
from app.tools.tts.qwen3_tts_0_6b.adapter import WORKER_PATH
from tests.tts.support import events, make_adapter, make_voice, synth

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the real worker does not report ready within the load budget on the Windows runner",
)

RUN_WORKER = (
    "import runpy, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "script = sys.argv[2]\n"
    "sys.argv = [script, *sys.argv[3:]]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)
QWEN_TTS = '''
import json
import os
import numpy
import torch

def _log(**entry):
    with open({log!r}, "a", encoding="ascii") as handle:
        handle.write(json.dumps(entry) + "\\n")

class Qwen3TTSModel:
    @classmethod
    def from_pretrained(cls, path, **kwargs):
        _log(
            call="load",
            path=path,
            offline=os.environ.get("HF_HUB_OFFLINE"),
            cuda_visible=os.environ.get("CUDA_VISIBLE_DEVICES"),
            cuda_order=os.environ.get("CUDA_DEVICE_ORDER"),
            options={{key: repr(value) for key, value in kwargs.items()}},
        )
        return cls()

    def get_supported_speakers(self):
        return ["sohee", "ryan"]

    def generate_custom_voice(self, text, language, speaker, **kwargs):
        _log(
            call="generate",
            text=text,
            language=language,
            speaker=speaker,
            threads=torch.get_num_threads(),
            interop=torch.get_num_interop_threads(),
            seed=torch.initial_seed(),
        )
        if text == "stereo":
            return [numpy.zeros((24000, 2), dtype="float32")], 24000
        t = numpy.arange(24000) / 24000
        return [(0.3 * numpy.sin(2 * numpy.pi * 220 * t)).astype("float32")], 24000
'''


@pytest.fixture
def engine(tmp_path: Path):
    libs = tmp_path / "libs"
    libs.mkdir()
    log = tmp_path / "calls.jsonl"
    (libs / "qwen_tts.py").write_text(QWEN_TTS.format(log=str(log)), encoding="utf-8")
    command = [sys.executable, "-c", RUN_WORKER, str(libs), str(WORKER_PATH)]
    adapter = make_adapter(tmp_path, command=command, threads=3, load_timeout_s=240.0)

    def calls() -> list[dict]:
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    yield adapter, calls
    adapter.close()


def frames(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes()


def test_28_worker_loads_only_the_local_model_with_the_configured_threads(
    engine, tmp_path: Path
) -> None:
    adapter, calls = engine
    result = synth(adapter, tmp_path, "안녕하세요")
    load = next(call for call in calls() if call["call"] == "load")
    assert load["path"] == str(tmp_path / "model")
    assert load["offline"] == "1"
    assert load["options"]["trust_remote_code"] == "False"
    assert load["options"]["local_files_only"] == "True"
    assert load["options"]["device_map"] == "'cpu'"
    generate = next(call for call in calls() if call["call"] == "generate")
    assert (generate["threads"], generate["interop"]) == (3, 1)
    assert result.duration_ms == 1000
    assert frames(result.wav_path) == 24000


def test_28_worker_passes_speaker_language_and_seed_to_the_model(engine, tmp_path: Path) -> None:
    adapter, calls = engine
    synth(adapter, tmp_path, "안녕하세요", voice=make_voice(settings={"speed": 1.0, "seed": 42}))
    log = calls()
    assert next(call for call in log if call["call"] == "generate")["seed"] == 42
    generate = next(call for call in log if call["call"] == "generate")
    assert (generate["text"], generate["language"], generate["speaker"]) == (
        "안녕하세요",
        "Korean",
        "Sohee",
    )


@pytest.mark.parametrize(("speed", "expected_ms"), [(1.25, 800), (0.8, 1250)])
def test_28_speed_changes_the_length_of_the_audio(
    engine, tmp_path: Path, speed: float, expected_ms: int
) -> None:
    adapter, _ = engine
    result = synth(
        adapter, tmp_path, "안녕하세요", voice=make_voice(settings={"speed": speed, "seed": 0})
    )
    assert result.duration_ms == pytest.approx(expected_ms, abs=40)


def test_27_a_speaker_the_model_does_not_have_is_tts_failed(engine, tmp_path: Path) -> None:
    adapter, _ = engine
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path, voice=make_voice(speaker="Nobody"))
    failure = raised.value
    assert (failure.code, failure.detail["reason"]) == ("tts_failed", "speaker_unsupported")
    assert not list((tmp_path / "out").glob("*"))
    # The worker survives a refused request.
    assert synth(adapter, tmp_path).duration_ms == 1000


def test_28_multichannel_output_is_not_flattened_into_mono(engine, tmp_path: Path) -> None:
    adapter, _ = engine
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path, "stereo")
    assert (raised.value.code, raised.value.detail["reason"]) == ("tts_failed", "invalid_waveform")
    assert not list((tmp_path / "out").glob("*"))


QWEN_TTS_FAILS_ON_CUDA = '''
import json
import numpy


def _log(**entry):
    with open({log!r}, "a", encoding="ascii") as handle:
        handle.write(json.dumps(entry) + "\\n")


class Qwen3TTSModel:
    @classmethod
    def from_pretrained(cls, path, **kwargs):
        _log(call="load", device=kwargs["device_map"])
        if kwargs["device_map"] == "cuda":
            import sys
            print("/secret/model/path", file=sys.stderr)
            raise RuntimeError("no cuda device")
        return cls()

    def get_supported_speakers(self):
        return ["sohee"]

    def generate_custom_voice(self, text, language, speaker, **kwargs):
        t = numpy.arange(24000) / 24000
        return [(0.3 * numpy.sin(2 * numpy.pi * 220 * t)).astype("float32")], 24000
'''


def test_device_auto_steps_down_to_the_cpu_once_after_a_failed_cuda_load(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    libs = tmp_path / "libs"
    libs.mkdir()
    log = tmp_path / "device_calls.jsonl"
    (libs / "qwen_tts.py").write_text(
        QWEN_TTS_FAILS_ON_CUDA.format(log=str(log)), encoding="utf-8"
    )
    command = [sys.executable, "-c", RUN_WORKER, str(libs), str(WORKER_PATH)]
    adapter = make_adapter(
        tmp_path,
        command=command,
        selection=DeviceSelection(requested="auto", device="cuda", reason="detected"),
        runtime_digest_for=lambda device: f"{device}-digest",
    )

    def loads() -> list[str]:
        return [json.loads(line)["device"] for line in log.read_text().splitlines()]

    try:
        assert synth(adapter, tmp_path).duration_ms == 1000
        assert (adapter.device, adapter.device_reason) == ("cpu", "load_failed")
        assert adapter.info().runtime_digest == "cpu-digest"
        assert loads() == ["cuda", "cpu"]
        assert "RuntimeError" in caplog.text
        assert "/secret/model/path" not in caplog.text
        # The CPU worker stays loaded for the next sentence.
        assert synth(adapter, tmp_path).duration_ms == 1000
        assert loads() == ["cuda", "cpu"]
    finally:
        adapter.close()


def test_device_auto_steps_down_to_the_cpu_once_after_a_cuda_load_timeout(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    adapter = make_adapter(
        tmp_path,
        mode="slow_load_on_cuda",
        selection=DeviceSelection(requested="auto", device="cuda", reason="detected"),
        load_timeout_s=2.0,
    )
    try:
        assert synth(adapter, tmp_path).duration_ms == 500
        assert (adapter.device, adapter.device_reason) == ("cpu", "load_failed")
        starts = [event for event in events(tmp_path) if event["event"] == "start"]
        assert [event["device"] for event in starts] == ["cuda", "cpu"]
        assert "tts_timeout at load" in caplog.text
    finally:
        adapter.close()


def test_device_worker_keeps_the_host_cuda_device_assignment(
    engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    adapter, calls = engine
    assert synth(adapter, tmp_path).duration_ms == 1000
    load = next(call for call in calls() if call["call"] == "load")
    assert (load["cuda_visible"], load["cuda_order"]) == ("1", "PCI_BUS_ID")


def test_device_auto_steps_down_to_the_cpu_once_after_a_worker_exit_before_ready(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    adapter = make_adapter(
        tmp_path,
        mode="crash_on_cuda",
        selection=DeviceSelection(requested="auto", device="cuda", reason="detected"),
    )
    try:
        assert synth(adapter, tmp_path).duration_ms == 500
        assert (adapter.device, adapter.device_reason) == ("cpu", "load_failed")
        starts = [event for event in events(tmp_path) if event["event"] == "start"]
        assert [event["device"] for event in starts] == ["cuda", "cpu"]
        assert "worker_exited" in caplog.text
    finally:
        adapter.close()


def test_device_auto_retries_the_first_cuda_synthesis_on_the_cpu(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    adapter = make_adapter(
        tmp_path,
        mode="synth_error_on_cuda",
        selection=DeviceSelection(requested="auto", device="cuda", reason="detected"),
    )
    try:
        assert synth(adapter, tmp_path).duration_ms == 500
        assert (adapter.device, adapter.device_reason) == ("cpu", "load_failed")
        starts = [event for event in events(tmp_path) if event["event"] == "start"]
        assert [event["device"] for event in starts] == ["cuda", "cpu"]
        assert "synth_failed" in caplog.text
    finally:
        adapter.close()
