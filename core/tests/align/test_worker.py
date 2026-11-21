"""The real worker script over a stand-in WhisperX module and a real WAV reader."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.tools.align.adapter import WORKER_PATH
from tests.align.support import write_wav

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
WHISPERX = '''
import json
import os

import torch


def _log(**entry):
    with open(os.environ["ALIGN_TEST_LOG"], "a", encoding="ascii") as handle:
        handle.write(json.dumps(entry) + "\\n")


class Model:
    def __init__(self, language):
        self.language = language

    def __del__(self):
        _log(event="release", language=self.language)


def load_align_model(
    language_code, device, model_name=None, model_dir=None, model_cache_only=False
):
    _log(
        event="load",
        language=language_code,
        model_name=model_name,
        model_dir=model_dir,
        cache_only=model_cache_only,
        threads=torch.get_num_threads(),
        nltk=os.environ.get("NLTK_DATA"),
    )
    if language_code == "ko" and model_name and not os.path.isdir(model_name):
        raise OSError("missing model")
    return Model(language_code), {"language": language_code, "type": "stub", "dictionary": {}}


def align(segment, model, metadata, audio, device):
    _log(
        event="align",
        language=metadata["language"],
        samples=int(len(audio)),
        device=device,
        text=segment[0]["text"],
    )
    tokens = segment[0]["text"].split()
    return {
        "word_segments": [
            {"word": token, "start": index * 0.25, "end": index * 0.25 + 0.2, "score": 0.9}
            for index, token in enumerate(tokens)
        ]
    }
'''


def start(
    tmp_path: Path, *, idle: float = 120.0, models: bool = True, english: bool = True
) -> tuple[subprocess.Popen, Path]:
    libs = tmp_path / "libs"
    (libs / "whisperx").mkdir(parents=True)
    (libs / "whisperx" / "__init__.py").write_text(WHISPERX, encoding="utf-8")
    log = tmp_path / "calls.jsonl"
    ko = tmp_path / "ko"
    en = tmp_path / "en"
    ko.mkdir(exist_ok=True)
    en.mkdir(exist_ok=True)
    if english:
        (en / "model.pth").write_bytes(b"x")
    nltk = tmp_path / "nltk_data"
    (nltk / "tokenizers" / "punkt_tab" / "english").mkdir(parents=True)
    command = [
        sys.executable,
        "-c",
        RUN_WORKER,
        str(libs),
        str(WORKER_PATH),
        "--model-ko",
        str(ko if models else tmp_path / "missing-ko"),
        "--model-en",
        str(en if models else tmp_path / "missing-en"),
        "--model-en-file",
        "model.pth",
        "--nltk-data",
        str(nltk),
        "--threads",
        "2",
        "--idle-s",
        str(idle),
    ]
    env = dict(os.environ)
    env["ALIGN_TEST_LOG"] = str(log)
    env["PYTHONUTF8"] = "1"
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    return process, log


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def send(process: subprocess.Popen, request: dict) -> dict:
    assert process.stdin is not None
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    return read(process)


def read(process: subprocess.Popen) -> dict:
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, process.stderr.read() if process.stderr else ""
    return json.loads(line)


def calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_15_the_worker_loads_each_language_alone_and_reads_16khz(tmp_path: Path) -> None:
    process, log = start(tmp_path)
    try:
        assert read(process) == {"type": "ready"}
        wav = write_wav(tmp_path / "ko.wav", ms=1000)
        reply = send(
            process,
            {
                "id": 1,
                "wav": str(wav),
                "speech_text": "가격은 만 이천오백 원이고,",
                "language": "ko",
                "speech_ms": 1000,
            },
        )
        assert reply["type"] == "words"
        assert len(reply["words"]) == 4
        first = calls(log)
        assert first[0]["event"] == "load"
        assert first[0]["language"] == "ko"
        assert first[0]["cache_only"] is True
        assert first[0]["threads"] == 2
        assert first[0]["nltk"] == str(tmp_path / "nltk_data")
        assert first[1]["event"] == "align"
        assert first[1]["samples"] == 16000
        assert first[1]["device"] == "cpu"

        reply = send(
            process,
            {
                "id": 2,
                "wav": str(wav),
                "speech_text": "The price is twelve dollars and fifty cents.",
                "language": "en",
                "speech_ms": 1000,
            },
        )
        assert reply["type"] == "words"
        second = calls(log)[len(first) :]
        assert second[0]["event"] == "release"
        assert second[0]["language"] == "ko"
        assert second[1]["event"] == "load"
        assert second[1]["model_name"] == "WAV2VEC2_ASR_BASE_960H"
        assert second[1]["model_dir"] == str(tmp_path / "en")
        assert second[2]["event"] == "align"
        assert second[2]["language"] == "en"
    finally:
        stop(process)


def test_15_the_worker_leaves_after_its_idle_time(tmp_path: Path) -> None:
    process, _ = start(tmp_path, idle=0.2)
    try:
        assert read(process) == {"type": "ready"}
        assert read(process) == {"type": "bye"}
        assert process.wait(timeout=5) == 0
    finally:
        stop(process)


def test_15_a_missing_model_file_is_reported_at_startup(tmp_path: Path) -> None:
    process, _ = start(tmp_path, models=False)
    try:
        reply = read(process)
        assert reply["type"] == "error"
        assert reply["code"] == "package_missing"
        assert process.wait(timeout=5) == 1
    finally:
        stop(process)


def test_15_an_unreadable_wav_is_one_align_error(tmp_path: Path) -> None:
    process, _ = start(tmp_path)
    try:
        assert read(process) == {"type": "ready"}
        reply = send(
            process,
            {
                "id": 1,
                "wav": str(tmp_path / "missing.wav"),
                "speech_text": "네.",
                "language": "ko",
                "speech_ms": 500,
            },
        )
        assert (reply["type"], reply["code"], reply["id"]) == ("error", "align_failed", 1)
    finally:
        stop(process)


def test_15_an_empty_request_text_is_one_error(tmp_path: Path) -> None:
    process, _ = start(tmp_path)
    try:
        assert read(process) == {"type": "ready"}
        reply = send(
            process,
            {
                "id": 1,
                "wav": str(tmp_path / "x.wav"),
                "speech_text": "",
                "language": "ko",
                "speech_ms": 500,
            },
        )
        assert (reply["type"], reply["code"]) == ("error", "empty_text")
    finally:
        stop(process)


def test_21_the_korean_model_alone_starts_the_worker_and_aligns_korean(tmp_path: Path) -> None:
    process, log = start(tmp_path, english=False)
    try:
        assert read(process) == {"type": "ready"}
        wav = write_wav(tmp_path / "ko.wav", ms=1000)
        reply = send(
            process,
            {"id": 1, "wav": str(wav), "speech_text": "가격은 만 이천오백 원이고,",
             "language": "ko", "speech_ms": 1000},
        )
        assert reply["type"] == "words"
        english = send(
            process,
            {"id": 2, "wav": str(wav), "speech_text": "The price is twelve dollars.",
             "language": "en", "speech_ms": 1000},
        )
        assert english["type"] == "error" and english["id"] == 2
        loads = [call["language"] for call in calls(log) if call["event"] == "load"]
        assert loads == ["ko"]
    finally:
        stop(process)
