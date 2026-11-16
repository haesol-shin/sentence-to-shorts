"""Qwen3-TTS adapter against a fake worker process: timeout, cancel, failure codes, reuse."""

from __future__ import annotations

import sys
import threading
import time
import wave
from pathlib import Path

import pytest

from app.jobs import CancelFlag
from app.ports import AppError, Cancelled
from app.services.voice.service import CHARS_PER_SECOND, MIN_ESTIMATE_MS
from app.tools.tts.qwen3_tts_0_6b import adapter as engine
from app.tools.tts.qwen3_tts_0_6b.adapter import MODEL_ITEM, PACKAGE_ITEM
from tests.tts.support import alive, events, gone, make_adapter, make_voice, synth

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="process liveness is probed with POSIX signal 0"
)


def test_28_synthesis_returns_a_measured_mono_wav(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    try:
        result = synth(adapter, tmp_path)
    finally:
        adapter.close()
    with wave.open(str(result.wav_path), "rb") as handle:
        shape = (handle.getnchannels(), handle.getsampwidth(), handle.getframerate())
        assert shape == (1, 2, 24000)
        assert result.duration_ms == handle.getnframes() * 1000 // 24000 == 500
    assert result.wav_path.parent == tmp_path / "out"
    request = [event for event in events(tmp_path) if event["event"] == "request"][0]
    assert (request["speaker"], request["seed"]) == ("Sohee", 0)


def test_11_one_worker_serves_every_call_until_it_leaves_for_idleness(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, idle_s=0.5)
    try:
        synth(adapter, tmp_path, "하나")
        synth(adapter, tmp_path, "둘")
        time.sleep(1.2)
        synth(adapter, tmp_path, "셋")
    finally:
        adapter.close()
    log = events(tmp_path)
    starts = [event["pid"] for event in log if event["event"] == "start"]
    assert len(starts) == 2
    assert [event["pid"] for event in log if event["event"] == "request"] == [
        starts[0],
        starts[0],
        starts[1],
    ]
    assert [event["event"] for event in log].count("idle_exit") == 1


def test_11_request_after_a_worker_idle_exit_goes_to_a_new_worker(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "bye_once")
    try:
        result = synth(adapter, tmp_path)
    finally:
        adapter.close()
    assert result.duration_ms == 500
    assert len({event["pid"] for event in events(tmp_path) if event["event"] == "start"}) == 2


def test_27_sentence_timeout_is_the_larger_of_thirty_seconds_and_ten_times_the_length(
    tmp_path: Path,
) -> None:
    adapter = make_adapter(tmp_path)
    short = adapter.sentence_timeout_s("안녕하세요", "ko")
    long = adapter.sentence_timeout_s("가" * 800, "ko")
    assert short == 30.0
    assert long == 10 * engine.expected_ms("가" * 800, "ko") / 1000
    assert long > 30.0


def test_27_expected_length_table_matches_the_voice_service() -> None:
    assert engine.CHARS_PER_SECOND == CHARS_PER_SECOND
    assert engine.MIN_EXPECTED_MS == MIN_ESTIMATE_MS


def test_27_timeout_kills_the_worker_and_leaves_no_file(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "hang", sentence_floor_s=0.5, sentence_factor=0.0)
    started = time.monotonic()
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path)
    assert raised.value.code == "tts_timeout"
    assert raised.value.detail["stage"] == "synthesize"
    assert time.monotonic() - started < 10
    (pid,) = {event["pid"] for event in events(tmp_path)}
    assert gone(pid)
    assert not list((tmp_path / "out").glob("*"))
    adapter.close()


def test_27_load_timeout_is_tts_timeout(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "slow_load", load_timeout_s=0.5)
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path)
    assert (raised.value.code, raised.value.detail["stage"]) == ("tts_timeout", "load")
    (pid,) = {event["pid"] for event in events(tmp_path)}
    assert gone(pid)


def test_27_cancel_kills_the_whole_process_tree(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "grandchild")
    cancel = CancelFlag()
    pids = tmp_path / "pids"

    def cancel_when_stuck() -> None:
        while not pids.exists():
            time.sleep(0.02)
        time.sleep(0.2)
        cancel.cancel()

    threading.Thread(target=cancel_when_stuck, daemon=True).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        synth(adapter, tmp_path, cancel=cancel)
    assert time.monotonic() - started < 10
    worker, grandchild = map(int, pids.read_text().split())
    assert gone(worker, grandchild)
    assert not list((tmp_path / "out").glob("*"))


def test_27_cancel_before_the_call_starts_no_worker(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    cancel = CancelFlag()
    cancel.cancel()
    with pytest.raises(Cancelled):
        synth(adapter, tmp_path, cancel=cancel)
    assert events(tmp_path) == []


def test_27_worker_crash_is_tts_failed_and_the_next_call_starts_a_new_worker(
    tmp_path: Path,
) -> None:
    adapter = make_adapter(tmp_path, "crash")
    for _ in range(2):
        with pytest.raises(AppError) as raised:
            synth(adapter, tmp_path)
        assert raised.value.code == "tts_failed"
        assert raised.value.detail["reason"] == "worker_exited"
        assert raised.value.detail["returncode"] == 3
    assert len({event["pid"] for event in events(tmp_path) if event["event"] == "start"}) == 2
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("*"))


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("synth_error", "synth_failed"),
        ("truncated", "wav_truncated"),
        ("wrong_rate", "sample_rate"),
        ("load_error", "model_load"),
    ],
)
def test_27_engine_and_wav_failures_are_tts_failed_without_a_substitute(
    tmp_path: Path, mode: str, reason: str
) -> None:
    adapter = make_adapter(tmp_path, mode)
    try:
        with pytest.raises(AppError) as raised:
            synth(adapter, tmp_path)
    finally:
        adapter.close()
    assert raised.value.code == "tts_failed"
    assert raised.value.detail["reason"] == reason
    assert not list((tmp_path / "out").glob("*"))


def test_27_missing_model_file_is_tts_not_ready_and_starts_nothing(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    (tmp_path / "model" / "weights.bin").write_bytes(b"short")
    assert adapter.ready() == [MODEL_ITEM]
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path)
    assert raised.value.code == "tts_not_ready"
    assert raised.value.detail["missing"] == [MODEL_ITEM]
    assert events(tmp_path) == []


def test_27_missing_package_is_tts_not_ready(tmp_path: Path) -> None:
    assert make_adapter(tmp_path, package=False).ready() == [PACKAGE_ITEM]
    adapter = make_adapter(tmp_path, "no_package")
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path)
    assert raised.value.code == "tts_not_ready"
    assert raised.value.detail["missing"] == [PACKAGE_ITEM]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"engine_id": "fixed_wav"}, "voice_engine"),
        ({"languages": ["en"]}, "language"),
        (
            {"model": {"runtime_item": MODEL_ITEM, "repo": "Qwen/Synthetic", "revision": "b" * 40}},
            "voice_model",
        ),
    ],
)
def test_9_a_voice_of_another_engine_or_language_is_refused(
    tmp_path: Path, changes: dict, reason: str
) -> None:
    adapter = make_adapter(tmp_path)
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path, voice=make_voice(**changes))
    assert (raised.value.code, raised.value.detail["reason"]) == ("tts_failed", reason)
    assert events(tmp_path) == []


def test_9_unsupported_language_and_blank_text_are_refused(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    with pytest.raises(AppError) as raised:
        adapter.synthesize(
            "hola", "es", make_voice(), out_dir=tmp_path / "out", cancel=CancelFlag()
        )
    assert raised.value.detail["reason"] == "language"
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path, "  ")
    assert raised.value.detail["reason"] == "empty_text"
    assert events(tmp_path) == []


def test_27_close_stops_the_worker(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    synth(adapter, tmp_path)
    (pid,) = {event["pid"] for event in events(tmp_path)}
    assert alive(pid)
    adapter.close()
    assert gone(pid)
    adapter.close()


def test_27_extra_wav_chunks_do_not_hide_truncated_audio(tmp_path: Path) -> None:
    from tests.tts.fake_worker import tone

    path = tmp_path / "truncated.wav"
    tone(str(path))
    wav = path.read_bytes()
    junk = b"JUNK" + (32000).to_bytes(4, "little") + bytes(32000)
    broken = wav[:36] + junk + wav[36:-2000]
    broken = broken[:4] + (len(broken) - 8).to_bytes(4, "little") + broken[8:]
    path.write_bytes(broken)
    with pytest.raises(AppError) as raised:
        engine._wav_ms(path)
    assert (raised.value.code, raised.value.detail["reason"]) == ("tts_failed", "wav_truncated")


@pytest.mark.parametrize(
    ("mode", "reason"),
    [("no_write_after_one", "wav_unreadable"), ("fail_after_one", "synth_failed")],
)
def test_27_failed_repeat_keeps_the_previous_successful_wav(
    tmp_path: Path, mode: str, reason: str
) -> None:
    adapter = make_adapter(tmp_path, mode)
    try:
        first = synth(adapter, tmp_path)
        original = first.wav_path.read_bytes()
        with pytest.raises(AppError) as raised:
            synth(adapter, tmp_path)
        assert (raised.value.code, raised.value.detail["reason"]) == ("tts_failed", reason)
        assert first.wav_path.read_bytes() == original
        assert list((tmp_path / "out").glob("*.wav")) == [first.wav_path]
    finally:
        adapter.close()


def test_27_closed_adapter_never_starts_a_new_worker(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    synth(adapter, tmp_path)
    adapter.close()
    with pytest.raises(AppError) as raised:
        synth(adapter, tmp_path)
    assert (raised.value.code, raised.value.detail["reason"]) == ("tts_failed", "closed")
    assert len([event for event in events(tmp_path) if event["event"] == "start"]) == 1
