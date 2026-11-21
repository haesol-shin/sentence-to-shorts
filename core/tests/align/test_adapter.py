"""The WhisperX adapter over a stand-in worker: mapping, failure codes, cancel, env."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from app.jobs import CancelFlag
from app.ports import Cancelled
from app.tools.align.adapter import (
    WHISPERX,
    WhisperXAligner,
    create,
)
from tests.align.support import (
    FAKE_WORKER,
    WAV_MS,
    align,
    events,
    gone,
    make_adapter,
    prepare_model_files,
    write_wav,
)

K4_DISPLAY = "가격은 12,500원이고, 성공률은 97.3퍼센트입니다."
K4_SPEECH = "가격은 만 이천오백 원이고, 성공률은 구십칠 점 삼 퍼센트입니다."
E2_DISPLAY = "The price is $12.50."
E2_SPEECH = "The price is twelve dollars and fifty cents."
K5_DISPLAY = "CPU와 GPU의 차이를 알고 있나요? Python API로 WAV 파일을 저장해 보세요."
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="process liveness is probed with POSIX signal 0"
)

K5_SPEECH = (
    "씨 피 유와 지 피 유의 차이를 알고 있나요? "
    "파이썬 에이 피 아이로 더블유 에이 브이 파일을 저장해 보세요."
)


def test_15_the_adapter_maps_worker_words_to_display_phrases(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok")
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    finally:
        adapter.close()
    assert result.failure is None
    assert [(span.start_char, span.end_char) for span in result.phrases or []] == [
        (0, 14),
        (15, 31),
    ]


def test_15_the_adapter_keeps_the_currency_span(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok")
    try:
        result = align(adapter, tmp_path, E2_DISPLAY, E2_SPEECH, "en")
    finally:
        adapter.close()
    assert result.failure is None
    assert [(span.start_char, span.end_char) for span in result.phrases or []] == [
        (0, len(E2_DISPLAY))
    ]


def test_15_the_adapter_maps_code_names(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok")
    try:
        result = align(adapter, tmp_path, K5_DISPLAY, K5_SPEECH, ms=6000)
    finally:
        adapter.close()
    assert result.failure is None
    assert len(result.phrases) == 2


def test_15_low_scores_return_align_low_confidence(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "low")
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    finally:
        adapter.close()
    assert (result.phrases, result.failure) == (None, "align_low_confidence")


@pytest.mark.parametrize("mode", ["missing_time", "no_words"])
def test_15_a_broken_word_list_is_a_missing_word(tmp_path: Path, mode: str) -> None:
    adapter = make_adapter(tmp_path, mode)
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    finally:
        adapter.close()
    assert (result.phrases, result.failure) == (None, "align_missing_words")


def test_15_unordered_word_times_are_align_failed(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "unordered")
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    finally:
        adapter.close()
    assert (result.phrases, result.failure) == (None, "align_failed")


@pytest.mark.parametrize("mode", ["align_error", "crash", "protocol", "wrong_id"])
def test_15_a_broken_worker_reply_is_align_failed(tmp_path: Path, mode: str) -> None:
    adapter = make_adapter(tmp_path, mode)
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    finally:
        adapter.close()
    assert (result.phrases, result.failure) == (None, "align_failed")


def test_15_a_startup_model_failure_is_align_unavailable(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "start_error")
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    finally:
        adapter.close()
    assert (result.phrases, result.failure) == (None, "align_unavailable")


def test_15_a_model_failure_during_a_line_is_align_unavailable(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "model_load")
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
        assert (result.phrases, result.failure) == (None, "align_unavailable")
        assert events(tmp_path)[-1]["event"] == "request"
    finally:
        adapter.close()


def test_15_an_unreadable_wav_is_align_failed(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok")
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not a wav")
    try:
        result = adapter.align(broken, K4_SPEECH, K4_DISPLAY, "ko", cancel=CancelFlag())
    finally:
        adapter.close()
    assert (result.phrases, result.failure) == (None, "align_failed")
    assert events(tmp_path) == []


def test_15_an_unsupported_language_is_align_unavailable(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok")
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH, "fr")
    finally:
        adapter.close()
    assert (result.phrases, result.failure) == (None, "align_unavailable")


def test_15_missing_model_files_are_align_unavailable(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok", models=False)
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
        assert (result.phrases, result.failure) == (None, "align_unavailable")
    finally:
        adapter.close()


def test_15_missing_punkt_data_is_align_unavailable(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok", nltk=False)
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
        assert (result.phrases, result.failure) == (None, "align_unavailable")
    finally:
        adapter.close()


def test_15_no_align_python_is_align_unavailable(tmp_path: Path) -> None:
    ko = tmp_path / "ko"
    en = tmp_path / "en"
    ko.mkdir()
    en.mkdir()
    (ko / "weights.bin").write_bytes(b"x")
    (en / "model.pth").write_bytes(b"x")
    nltk_data = tmp_path / "nltk_data"
    (nltk_data / "tokenizers" / "punkt_tab" / "english").mkdir(parents=True)
    adapter = WhisperXAligner(
        python=None,
        model_files=[
            ("model-align-ko", ko, {"weights.bin": 1}),
            ("model-align-en", en, {"model.pth": 1}),
        ],
        nltk_data=nltk_data,
        threads=1,
        runtime_digest="d" * 64,
    )
    result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    assert (result.phrases, result.failure) == (None, "align_unavailable")


def test_15_a_line_timeout_is_align_failed_and_kills_the_worker(tmp_path: Path) -> None:
    adapter = make_adapter(
        tmp_path, "hang", timeout_floor_s=0.3, timeout_factor=0.0
    )
    started = time.monotonic()
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    finally:
        adapter.close()
    assert (result.phrases, result.failure) == (None, "align_failed")
    assert time.monotonic() - started < 3.0
    assert gone(*(event["pid"] for event in events(tmp_path)), within_s=2.0)


def test_15_cancel_stops_the_worker_tree_within_one_second(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "grandchild")
    cancel = CancelFlag()
    outcome: list[BaseException] = []

    def run() -> None:
        try:
            align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH, cancel=cancel)
        except BaseException as error:  # noqa: BLE001 - the test asserts the type
            outcome.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    pids_file = tmp_path / "pids"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not pids_file.exists():
        time.sleep(0.02)
    assert pids_file.exists()
    pids = [int(part) for part in pids_file.read_text().split()]
    cancel.cancel()
    started = time.monotonic()
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert time.monotonic() - started < 1.0
    assert outcome and isinstance(outcome[0], Cancelled)
    assert gone(*pids, within_s=2.0)
    adapter.close()


def test_15_an_idle_exit_restarts_the_worker_once(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "bye_once")
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
    finally:
        adapter.close()
    assert result.failure is None
    assert len({event["pid"] for event in events(tmp_path)}) == 2


def test_15_the_worker_receives_the_thread_and_data_settings(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok", threads=3)
    try:
        result = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH)
        assert result.failure is None
        start = events(tmp_path)[0]
        assert start["threads"] == "3"
        assert start["nltk"] == str(tmp_path / "nltk_data")
    finally:
        adapter.close()


def test_15_runtime_digest_includes_the_align_env_and_threads(
    app_settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepare_model_files(app_settings)
    monkeypatch.setenv("APP_ALIGN_PYTHON", sys.executable)
    monkeypatch.setenv("APP_ALIGN_THREADS", "2")
    app_settings.providers.adapters["aligner"] = WHISPERX
    first = create(app_settings).runtime_digest()
    second = create(app_settings).runtime_digest()
    monkeypatch.setenv("APP_ALIGN_THREADS", "3")
    third = create(app_settings).runtime_digest()
    monkeypatch.delenv("APP_ALIGN_PYTHON")
    fourth = create(app_settings).runtime_digest()
    assert first == second
    assert first != third
    assert first != fourth


@pytest.mark.skipif(sys.platform == "win32", reason="the wrapper is a shell script")
def test_15_the_worker_runs_under_app_align_python(
    app_settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepare_model_files(app_settings)
    log = tmp_path / "wrapper.log"
    wrapper = tmp_path / "align-python"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "-c" ]; then exec {sys.executable} "$@"; fi\n'
        "shift\n"
        f'echo "$@" >> {log}\n'
        f'exec {sys.executable} {FAKE_WORKER} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("APP_ALIGN_PYTHON", str(wrapper))
    monkeypatch.setenv("APP_ALIGN_THREADS", "2")
    app_settings.providers.adapters["aligner"] = "whisperx"
    adapter = create(app_settings)
    wav = write_wav(tmp_path / "line.wav", ms=WAV_MS)
    try:
        result = adapter.align(wav, K4_SPEECH, K4_DISPLAY, "ko", cancel=CancelFlag())
    finally:
        adapter.close()
    assert result.failure is None
    assert "--model-ko" in log.read_text(encoding="utf-8")


def test_21_the_worker_loads_only_the_aligner_packages_the_build_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = tmp_path / "align-site"
    monkeypatch.setenv("APP_ALIGN_SITE", str(site))
    adapter = make_adapter(tmp_path, "ok")
    try:
        assert align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH).failure is None
    finally:
        adapter.close()
    start = events(tmp_path)[0]
    assert start["pythonpath"] == str(site)
    assert start["nousersite"] == "1"


def test_21_a_source_checkout_leaves_the_worker_search_path_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_ALIGN_SITE", raising=False)
    adapter = make_adapter(tmp_path, "ok")
    try:
        assert align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH).failure is None
    finally:
        adapter.close()
    start = events(tmp_path)[0]
    assert start["pythonpath"] is None and start["nousersite"] is None


def test_21_a_korean_line_aligns_without_the_english_model(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "ok")
    (tmp_path / "en" / "model.pth").unlink()
    try:
        assert adapter.missing("ko") == []
        assert adapter.missing("en") == ["model-align-en"]
        assert adapter.missing() == ["model-align-en"]
        korean = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH, "ko")
        english = align(adapter, tmp_path, K4_DISPLAY, K4_SPEECH, "en")
    finally:
        adapter.close()
    assert korean.failure is None
    assert (english.phrases, english.failure) == (None, "align_unavailable")
