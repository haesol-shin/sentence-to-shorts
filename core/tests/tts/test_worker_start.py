"""The worker script starts and reports on every platform, with the pipes the adapter uses.

A worker that hangs before its first load step shows nothing: no phase, no error, no
stderr. These tests start the real script, so the Windows runner catches that hang.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from app.tools.tts.qwen3_tts_0_6b.adapter import WORKER_PATH

FIRST_MESSAGE_LIMIT_S = 120.0
FAKE_QWEN_TTS = """
class Qwen3TTSModel:
    @classmethod
    def from_pretrained(cls, path, **kwargs):
        return cls()
"""

STAND_IN_MODULES = {
    "torch": (
        "float32 = 'float32'\n"
        "def set_num_threads(n): pass\n"
        "def set_num_interop_threads(n): pass\n"
        "def manual_seed(n): pass\n"
    ),
    "numpy": (
        "float32 = 'float32'\n"
        "class Wave:\n"
        "    ndim = 1\n"
        "    size = 3\n"
        "    def all(self): return True\n"
        "def zeros(n, dtype=None): return Wave()\n"
        "def asarray(x, dtype=None): return Wave()\n"
        "def isfinite(x): return x\n"
    ),
    "soundfile": (
        "def write(path, wave, rate, format=None, subtype=None):\n"
        "    open(path, 'wb').write(b'RIFF')\n"
    ),
    "librosa": (
        "class effects:\n"
        "    @staticmethod\n"
        "    def time_stretch(wave, rate): return wave\n"
    ),
    "qwen_tts": (
        "class Qwen3TTSModel:\n"
        "    @classmethod\n"
        "    def from_pretrained(cls, path, **kwargs): return cls()\n"
        "    def get_supported_speakers(self): return ['sohee']\n"
        "    def generate_custom_voice(self, text, language, speaker):\n"
        "        return [[0.0]], 24000\n"
    ),
}
RUN_WITH_LIBS = (
    "import runpy, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "script = sys.argv[2]\n"
    "sys.argv = [script, *sys.argv[3:]]\n"
    "runpy.run_path(script, run_name='__main__')\n"
)


def _argv(model_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(WORKER_PATH),
        "--model-dir",
        str(model_dir),
        "--device",
        "cpu",
        "--threads",
        "1",
        "--idle-s",
        "30",
    ]


def _first_message(worker: subprocess.Popen[str]) -> dict[str, Any]:
    """The first protocol line, or a failure when the worker says nothing in time."""
    assert worker.stdout is not None
    lines: list[str] = []
    reader = threading.Thread(target=lambda: lines.append(worker.stdout.readline()), daemon=True)  # type: ignore[union-attr]
    reader.start()
    reader.join(FIRST_MESSAGE_LIMIT_S)
    assert lines and lines[0], f"no protocol line within {FIRST_MESSAGE_LIMIT_S}s"
    return json.loads(lines[0])


def test_worker_start_reports_a_phase_or_an_error_with_the_stdin_pipe_still_open(
    tmp_path: Path,
) -> None:
    worker = subprocess.Popen(
        _argv(tmp_path / "missing-model"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        message = _first_message(worker)
        assert (
            message["type"] == "phase"
            and message["name"] == "import_torch"
            or (
                message["type"] == "error" and message["code"] in ("package_missing", "load_failed")
            )
        ), message
    finally:
        worker.kill()
        for pipe in (worker.stdin, worker.stdout):
            if pipe is not None:
                pipe.close()
        worker.wait()


def _load_worker_module() -> Any:
    spec = importlib.util.spec_from_file_location("tts_worker_under_test", WORKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(sys.platform == "win32", reason="the ordering is checked on Linux")
def test_worker_start_reads_stdin_only_after_the_load(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _load_worker_module()
    order: list[str] = []

    class Reader:
        def __init__(self, target: Any, args: tuple[Any, ...], daemon: bool) -> None:
            order.append("reader created")

        def start(self) -> None:
            order.append("reader started")

    def load(*_args: Any) -> Any:
        order.append("load")
        return object()

    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(worker, "_reply_stream", lambda: None)
    monkeypatch.setattr(worker, "_send", lambda _stream, message: sent.append(message))
    monkeypatch.setattr(worker, "_load", load)
    monkeypatch.setattr(worker, "threading", types.SimpleNamespace(Thread=Reader))
    # The idle wait ends the serve loop: nothing ever arrives on the queue.
    assert worker.serve("model", 1, 0.01, "cpu") == 0
    assert order == ["load", "reader created", "reader started"]
    assert [message["type"] for message in sent] == ["ready", "bye"]


@pytest.mark.skipif(
    sys.platform == "win32", reason="the stand-in model library needs no Windows run"
)
def test_worker_start_exits_after_the_load_when_stdin_closed_during_it(tmp_path: Path) -> None:
    libs = tmp_path / "libs"
    libs.mkdir()
    (libs / "qwen_tts.py").write_text(FAKE_QWEN_TTS, encoding="utf-8")
    code = (
        "import runpy, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "script = sys.argv[2]\n"
        "sys.argv = [script, *sys.argv[3:]]\n"
        "runpy.run_path(script, run_name='__main__')\n"
    )
    argv = [sys.executable, "-c", code, str(libs), *_argv(tmp_path / "model")[1:]]
    worker = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    assert worker.stdin is not None and worker.stdout is not None
    worker.stdin.close()
    try:
        assert worker.wait(timeout=FIRST_MESSAGE_LIMIT_S) == 0
        types = [json.loads(line)["type"] for line in worker.stdout.read().splitlines()]
        assert types[-1] == "ready"
    finally:
        worker.kill()
        worker.stdout.close()
        worker.wait()


def test_worker_start_answers_a_request_written_after_ready_on_every_os(tmp_path: Path) -> None:
    """The model-free request path: a request written to the open stdin pipe after `ready`
    reaches the worker's reader thread and is answered, on Linux and on the Windows runner.
    The stand-in libraries replace torch and the model, so a hang here is the pipe."""
    libs = tmp_path / "libs"
    libs.mkdir()
    for name, source in STAND_IN_MODULES.items():
        (libs / f"{name}.py").write_text(source, encoding="utf-8")
    argv = [sys.executable, "-c", RUN_WITH_LIBS, str(libs), *_argv(tmp_path / "model")[1:]]
    worker = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    assert worker.stdin is not None and worker.stdout is not None
    try:
        seen = [_first_message(worker) for _ in range(5)]
        assert seen[-1] == {"type": "ready"}, seen
        out = tmp_path / "out.wav"
        request = {
            "id": 7, "text": "t", "language": "Korean", "speaker": "Sohee", "seed": 1,
            "speed": 1.0, "out": str(out),
        }
        worker.stdin.write(json.dumps(request) + "\n")
        worker.stdin.flush()
        received, answer = _first_message(worker), _first_message(worker)
        assert received == {"type": "received", "id": 7}
        assert (answer["type"], answer["id"], answer["sample_rate"]) == ("done", 7, 24000)
        assert answer["seconds"] >= 0 and out.read_bytes() == b"RIFF"
    finally:
        worker.kill()
        worker.stdin.close()
        worker.stdout.close()
        worker.wait()
