"""Process supervisor limits used by the sandbox: stdout kill and the memory cap."""

from __future__ import annotations

import sys

import pytest

from app.tools.process import memory_cap_status, run

PYTHON = sys.executable
MEMORY_LIMIT = 128 * 1024 * 1024


def test_17_stdout_flood_kills_the_tree_at_the_limit() -> None:
    result = run(
        [PYTHON, "-c", "import sys\nwhile True: sys.stdout.buffer.write(b'x' * 65536)"],
        env={},
        timeout_s=30,
        max_stdout_bytes=1024 * 1024,
        kill_on_stdout_limit=True,
    )
    assert result.output_limited
    assert not result.timed_out
    assert not result.ok
    assert len(result.stdout) == 1024 * 1024
    assert result.duration_ms < 10000


def test_17_stdout_over_the_limit_counts_after_a_fast_exit() -> None:
    result = run(
        [PYTHON, "-c", "import sys; sys.stdout.buffer.write(b'x' * 300000)"],
        env={},
        timeout_s=30,
        max_stdout_bytes=1024,
        kill_on_stdout_limit=True,
    )
    assert result.output_limited
    assert not result.ok


def test_17_memory_cap_status_names_a_mechanism_or_a_reason() -> None:
    status = memory_cap_status(MEMORY_LIMIT)
    assert status.limit_bytes == MEMORY_LIMIT
    if sys.platform == "win32":
        assert (status.applied, status.mechanism) == (True, "job_object")
    elif status.applied:
        assert status.mechanism == "cgroup_v2"
    else:
        assert status.mechanism == "none"
        assert status.reason


def test_17_memory_cap_stops_a_tree_over_the_limit() -> None:
    if not memory_cap_status(MEMORY_LIMIT).applied:
        pytest.skip("this host cannot apply a hard memory cap")
    result = run(
        [PYTHON, "-c", "chunks = [bytearray(32 * 1024 * 1024) for _ in range(16)]"],
        env={},
        timeout_s=60,
        memory_limit_bytes=MEMORY_LIMIT,
    )
    assert result.memory_limited
    assert not result.ok


def test_17_capped_child_sees_only_the_given_environment() -> None:
    status = memory_cap_status(MEMORY_LIMIT)
    if not status.applied:
        pytest.skip("this host cannot apply a hard memory cap")
    result = run(
        [PYTHON, "-c", "import os, sys; sys.stdout.write(','.join(sorted(os.environ)))"],
        env={"NO_COLOR": "1"},
        timeout_s=60,
        memory_limit_bytes=MEMORY_LIMIT,
    )
    assert result.returncode == 0
    names = set(result.stdout.decode().split(","))
    if sys.platform == "win32":
        assert "NO_COLOR" in names
    else:
        assert names - {"LC_CTYPE"} == {"NO_COLOR"}
    assert not result.memory_limited
