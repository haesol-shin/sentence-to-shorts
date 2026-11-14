"""Process runner: argv, env allowlist, limits, cancel and tree kill."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from app.jobs import CancelFlag
from app.tools.process import build_env, run

PYTHON = sys.executable


def _alive(pid: int) -> bool:
    if sys.platform.startswith("linux"):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return False
        if stat.rsplit(")", 1)[1].split()[0] == "Z":
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_arguments_are_passed_as_an_array() -> None:
    result = run(
        [
            PYTHON,
            "-c",
            "import sys; sys.stdout.buffer.write(sys.argv[1].encode() + b'\\n')",
            "a b",
        ],
        timeout_s=30,
    )
    assert result.returncode == 0
    assert result.stdout == b"a b\n"
    assert result.ok


def test_disallowed_environment_variable_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_env({"NOT_ALLOWED": "x"})


def test_allowed_environment_variable_reaches_the_child() -> None:
    env = build_env({"LANG": "C.UTF-8"})
    result = run(
        [
            PYTHON,
            "-c",
            "import os, sys; "
            "sys.stdout.buffer.write(os.environ['LANG'].encode() + b'\\n')",
        ],
        env=env,
        timeout_s=30,
    )
    assert result.returncode == 0
    assert result.stdout == b"C.UTF-8\n"


def test_stdout_limit_truncates_without_blocking() -> None:
    result = run(
        [PYTHON, "-c", "print('x' * 100000)"],
        timeout_s=30,
        max_stdout_bytes=1000,
    )
    assert result.returncode == 0
    assert len(result.stdout) == 1000
    assert result.stdout_truncated


def test_stderr_limit_truncates() -> None:
    result = run(
        [PYTHON, "-c", "import sys; sys.stderr.write('y' * 5000)"],
        timeout_s=30,
        max_stderr_bytes=100,
    )
    assert len(result.stderr) == 100
    assert result.stderr_truncated


def test_wall_timeout_kills_the_process_tree() -> None:
    result = run([PYTHON, "-c", "import time; time.sleep(30)"], timeout_s=1)
    assert result.timed_out
    assert result.duration_ms < 10000


def test_timeout_kills_grandchildren() -> None:
    if sys.platform == "win32":
        pytest.skip("grandchild check uses the POSIX process table")
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    result = run([PYTHON, "-c", script], timeout_s=1)
    assert result.timed_out
    pid = int(result.stdout.split()[0])
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(pid)


def test_cancel_token_stops_the_process() -> None:
    token = CancelFlag()
    timer = threading.Timer(0.3, token.cancel)
    timer.start()
    try:
        result = run([PYTHON, "-c", "import time; time.sleep(30)"], cancel=token)
    finally:
        timer.cancel()
    assert result.cancelled
    assert result.duration_ms < 5000


def test_stdin_bytes_are_written_then_closed() -> None:
    result = run(
        [PYTHON, "-c", "import sys; sys.stdout.write(sys.stdin.read()[::-1])"],
        stdin_data=b"abc",
        timeout_s=30,
    )
    assert result.returncode == 0
    assert result.stdout == b"cba"


def test_stdin_chunks_are_written_in_order() -> None:
    result = run(
        [PYTHON, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()[::-1])"],
        stdin_data=(chunk for chunk in (b"abc", b"def")),
        timeout_s=30,
    )
    assert result.returncode == 0
    assert result.stdout == b"fedcba"


def test_blocked_stdin_write_still_times_out() -> None:
    result = run(
        [PYTHON, "-c", "import time; time.sleep(30)"],
        stdin_data=b"x" * (1024 * 1024),
        timeout_s=0.2,
    )
    assert result.timed_out
    assert result.duration_ms < 1000


def test_streaming_stdin_cancels_when_the_child_stops_reading() -> None:
    token = CancelFlag()
    timer = threading.Timer(0.3, token.cancel)
    timer.start()
    try:
        result = run(
            [
                PYTHON,
                "-c",
                "import sys, time; sys.stdin.buffer.read(1); time.sleep(30)",
            ],
            stdin_data=(b"x" * 65536 for _ in range(1024)),
            cancel=token,
            timeout_s=30,
        )
    finally:
        timer.cancel()
    assert result.cancelled
    assert not result.timed_out
    assert result.duration_ms < 5000


def test_streaming_stdin_times_out_when_the_child_stops_reading() -> None:
    result = run(
        [PYTHON, "-c", "import time; time.sleep(30)"],
        stdin_data=(b"x" * 65536 for _ in range(1024)),
        timeout_s=0.3,
    )
    assert result.timed_out
    assert not result.cancelled
    assert result.duration_ms < 5000


def test_stdin_producer_error_fails_the_run() -> None:
    def chunks():  # type: ignore[no-untyped-def]
        yield b"abc"
        raise ValueError("synthetic producer failure")

    with pytest.raises(ValueError, match="synthetic producer failure"):
        run(
            [PYTHON, "-c", "import sys; sys.stdin.buffer.read()"],
            stdin_data=chunks(),
            timeout_s=30,
        )


def test_stdin_iterator_initialization_error_fails_the_run() -> None:
    class BrokenSource:
        def __iter__(self):  # type: ignore[no-untyped-def]
            raise OSError("synthetic iterator failure")

    with pytest.raises(OSError, match="synthetic iterator failure"):
        run(
            [PYTHON, "-c", "import sys; sys.stdin.buffer.read()"],
            stdin_data=BrokenSource(),
            timeout_s=30,
        )


def test_timeout_applies_after_the_parent_exits() -> None:
    script = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
    )
    result = run([PYTHON, "-c", script], timeout_s=0.3)
    assert result.timed_out
    assert result.duration_ms < 5000


def test_explicit_environment_is_still_allowlisted() -> None:
    with pytest.raises(ValueError):
        run(
            [PYTHON, "-c", "print('unreachable')"],
            env={"SECRET_TOKEN": "synthetic"},
            timeout_s=30,
        )
    result = run(
        [
            PYTHON,
            "-c",
            "import os, sys; "
            "sys.stdout.buffer.write(os.environ.get('LANG', 'absent').encode() + b'\\n')",
        ],
        env={"LANG": "C"},
        timeout_s=30,
    )
    assert result.stdout == b"C\n"


def test_empty_explicit_environment_stays_empty() -> None:
    result = run(
        [
            PYTHON,
            "-c",
            "import os, sys; "
            "sys.stdout.buffer.write("
            "os.environ.get('LANG', 'absent').encode() + b'\\n'"
            " + os.environ.get('SECRET_TOKEN', 'absent').encode() + b'\\n')",
        ],
        env={},
        timeout_s=30,
    )
    assert result.stdout == b"absent\nabsent\n"


def test_nonzero_exit_is_reported() -> None:
    result = run([PYTHON, "-c", "raise SystemExit(3)"], timeout_s=30)
    assert result.returncode == 3
    assert not result.ok
