"""The aligner worker script starts and reports on every platform, with the pipes the adapter uses.

A worker that hangs before its load shows nothing: no `ready`, no error, no stderr. These
tests start the real script over stand-in libraries, so the Windows runner catches that hang
without loading torch or a model.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from app.tools.align.adapter import WORKER_PATH
from tests.align.support import write_wav

FIRST_MESSAGE_LIMIT_S = 60.0
STAND_IN_MODULES = {
    "torch": (
        "def set_num_threads(n): pass\n"
        "def set_num_interop_threads(n): pass\n"
        "def get_num_threads(): return 1\n"
    ),
    "torchaudio": "",
    "numpy": (
        "float32 = 'float32'\n"
        "class Wave:\n"
        "    def astype(self, dtype): return self\n"
        "    def __truediv__(self, divisor): return self\n"
        "    def __len__(self): return 16000\n"
        "def frombuffer(data, dtype=None): return Wave()\n"
    ),
    "whisperx/__init__": (
        "def load_align_model(language_code, device, **kwargs):\n"
        "    return object(), {'language': language_code}\n"
        "def align(segment, model, metadata, audio, device):\n"
        "    tokens = segment[0]['text'].split()\n"
        "    return {'word_segments': [\n"
        "        {'word': t, 'start': i * 0.25, 'end': i * 0.25 + 0.2, 'score': 0.9}\n"
        "        for i, t in enumerate(tokens)]}\n"
    ),
}
RUN_WITH_LIBS = (
    "import runpy, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "script = sys.argv[2]\n"
    "sys.argv = [script, *sys.argv[3:]]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)


def _prepare(tmp_path: Path, *, with_data: bool = True) -> list[str]:
    libs = tmp_path / "libs"
    for name, source in STAND_IN_MODULES.items():
        path = libs / f"{name}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    ko = tmp_path / "ko"
    ko.mkdir()
    nltk = tmp_path / "nltk_data"
    if with_data:
        (nltk / "tokenizers" / "punkt_tab" / "english").mkdir(parents=True)
    return [
        sys.executable,
        "-c",
        RUN_WITH_LIBS,
        str(libs),
        str(WORKER_PATH),
        "--model-ko",
        str(ko),
        "--model-en",
        str(tmp_path / "en"),
        "--model-en-file",
        "model.pth",
        "--nltk-data",
        str(nltk),
        "--threads",
        "1",
        "--idle-s",
        "30",
    ]


def _first_message(worker: subprocess.Popen[str]) -> dict[str, Any]:
    """The next protocol line, or a failure when the worker says nothing in time."""
    assert worker.stdout is not None
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.append(worker.stdout.readline()), daemon=True)  # type: ignore[union-attr]
    reader.start()
    reader.join(FIRST_MESSAGE_LIMIT_S)
    assert lines and lines[0], f"no protocol line within {FIRST_MESSAGE_LIMIT_S}s"
    return json.loads(lines[0])


def _start(argv: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )


def _stop(worker: subprocess.Popen[str]) -> None:
    worker.kill()
    for pipe in (worker.stdin, worker.stdout):
        if pipe is not None:
            pipe.close()
    worker.wait()


def test_worker_start_reports_ready_then_answers_a_request_with_the_stdin_pipe_open(
    tmp_path: Path,
) -> None:
    worker = _start(_prepare(tmp_path))
    assert worker.stdin is not None
    try:
        assert _first_message(worker) == {"type": "ready"}
        wav = write_wav(tmp_path / "ko.wav", ms=1000, rate=16000)
        request = {
            "id": 7,
            "wav": str(wav),
            "speech_text": "가격은 만 원이고,",
            "language": "ko",
            "speech_ms": 1000,
        }
        worker.stdin.write(json.dumps(request) + "\n")
        worker.stdin.flush()
        answer = _first_message(worker)
        assert answer.get("type") == "words", answer
        assert (answer["id"], len(answer["words"])) == (7, 3)
    finally:
        _stop(worker)


def test_worker_start_reports_an_error_when_the_prepared_data_is_missing(tmp_path: Path) -> None:
    worker = _start(_prepare(tmp_path, with_data=False))
    try:
        message = _first_message(worker)
        assert message["type"] == "error" and message["code"] == "package_missing", message
        assert worker.wait(timeout=FIRST_MESSAGE_LIMIT_S) == 1
    finally:
        _stop(worker)


@pytest.mark.skipif(
    sys.platform == "win32", reason="the stand-in libraries need no Windows run for this path"
)
def test_worker_start_exits_after_the_load_when_stdin_closed_during_it(tmp_path: Path) -> None:
    worker = _start(_prepare(tmp_path))
    assert worker.stdin is not None and worker.stdout is not None
    worker.stdin.close()
    try:
        assert worker.wait(timeout=FIRST_MESSAGE_LIMIT_S) == 0
        types = [json.loads(line)["type"] for line in worker.stdout.read().splitlines()]
        assert types == ["ready"]
    finally:
        _stop(worker)
