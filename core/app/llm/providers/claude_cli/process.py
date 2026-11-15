"""Run the provider CLI with a private process tree and bounded pipes.

The parent keeps only capped byte buffers for stdout and stderr. A timeout,
cancellation or stdout overflow kills the whole tree: a POSIX process group or a
Windows Job Object with kill-on-close. Stdin is written by a separate thread so a
large prompt cannot block the supervisor.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.ports import CancelToken

KILL_GRACE_S = 5.0
POLL_S = 0.02
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


@dataclass
class _Stops:
    timed_out: bool = False
    cancelled: bool = False
    output_limited: bool = False


@dataclass(frozen=True)
class CliProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    cancelled: bool
    output_limited: bool


class _JobObject:
    """Windows Job Object that kills every descendant when its handle closes."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Job Objects exist only on Windows")
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self._kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = self._job_info()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
            self._handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def _job_info(self):  # type: ignore[no-untyped-def]
        ctypes = self._ctypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        return JOBOBJECT_EXTENDED_LIMIT_INFORMATION()

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        handle = int(process._handle)  # the job API needs the raw handle
        if not self._kernel32.AssignProcessToJobObject(self._handle, handle):
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _drain(
    stream, limit: int, overflow: threading.Event
) -> tuple[bytes, bool]:
    data = bytearray()
    truncated = False
    while True:
        try:
            chunk = stream.read(65536)
        except (OSError, ValueError):
            break
        if not chunk:
            break
        room = limit - len(data)
        if room > 0:
            data.extend(chunk[:room])
        if len(chunk) > max(0, room):
            truncated = True
            overflow.set()
    return bytes(data), truncated


def _write_stdin(stream, data: bytes) -> None:  # type: ignore[no-untyped-def]
    try:
        stream.write(data)
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (BrokenPipeError, OSError, ValueError):
            pass


def _start(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    has_stdin: bool,
) -> tuple[subprocess.Popen[bytes], _JobObject | None, int | None]:
    kwargs: dict[str, object] = {
        "cwd": str(cwd),
        "env": dict(env),
        "stdin": subprocess.PIPE if has_stdin else subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    job = None
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    if sys.platform == "win32":
        job = _JobObject()
    try:
        process = subprocess.Popen(argv, **kwargs)  # type: ignore[arg-type]
    except BaseException:
        if job is not None:
            job.close()
        raise
    pgid = None
    if os.name != "nt":
        try:
            pgid = os.getpgid(process.pid)
        except OSError:
            pgid = None
    if job is not None:
        try:
            job.assign(process)
        except OSError:
            if process.poll() is None:
                process.kill()
                process.wait()
                job.close()
                raise
            # A quick process ended before assignment; there is no live tree.
            job.close()
            job = None
    return process, job, pgid


def _kill_tree(
    process: subprocess.Popen[bytes], job: _JobObject | None, pgid: int | None
) -> None:
    if sys.platform == "win32":
        if job is not None:
            job.close()
        if process.poll() is None:
            process.kill()
        return
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError):
            pass
    if process.poll() is None:
        process.kill()


def _validate_run(
    argv: Sequence[str],
    *,
    timeout_s: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    stdin_data: bytes | None,
) -> None:
    if not argv:
        raise ValueError("argv must contain the program")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if max_stdout_bytes < 1 or max_stderr_bytes < 1:
        raise ValueError("output limits must be positive")
    if stdin_data is not None and not isinstance(stdin_data, bytes):
        raise TypeError("stdin_data must be bytes")


def _supervise(
    process: subprocess.Popen[bytes],
    workers: list[threading.Thread],
    job: _JobObject | None,
    pgid: int | None,
    cancel: CancelToken | None,
    deadline: float,
    stdout_overflow: threading.Event,
) -> _Stops:
    stops = _Stops()
    while process.poll() is None or any(worker.is_alive() for worker in workers):
        if stdout_overflow.is_set():
            stops.output_limited = True
            _kill_tree(process, job, pgid)
            break
        if cancel is not None and cancel.is_set():
            stops.cancelled = True
            _kill_tree(process, job, pgid)
            break
        if time.monotonic() >= deadline:
            stops.timed_out = True
            _kill_tree(process, job, pgid)
            break
        if cancel is not None:
            cancel.wait(POLL_S)
        else:
            time.sleep(POLL_S)
    if stdout_overflow.is_set():
        stops.output_limited = True
    return stops


def _finish(
    process: subprocess.Popen[bytes],
    workers: list[threading.Thread],
    job: _JobObject | None,
    pgid: int | None,
) -> None:
    try:
        process.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        _kill_tree(process, job, pgid)
        process.wait(timeout=KILL_GRACE_S)
    for worker in workers:
        worker.join(timeout=KILL_GRACE_S)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
    if job is not None:
        job.close()


def run(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    cancel: CancelToken | None = None,
    stdin_data: bytes | None = None,
) -> CliProcessResult:
    _validate_run(
        argv,
        timeout_s=timeout_s,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
        stdin_data=stdin_data,
    )
    process, job, pgid = _start(argv, cwd=cwd, env=env, has_stdin=stdin_data is not None)
    captured: dict[str, tuple[bytes, bool]] = {}
    stdout_overflow = threading.Event()
    stderr_overflow = threading.Event()

    def collect(
        name: str, stream, limit: int, overflow: threading.Event
    ) -> None:
        captured[name] = _drain(stream, limit, overflow)

    pending = [
        threading.Thread(
            target=collect,
            args=("stdout", process.stdout, max_stdout_bytes, stdout_overflow),
            daemon=True,
        ),
        threading.Thread(
            target=collect,
            args=("stderr", process.stderr, max_stderr_bytes, stderr_overflow),
            daemon=True,
        ),
    ]
    if stdin_data is not None and process.stdin is not None:
        pending.append(
            threading.Thread(
                target=_write_stdin,
                args=(process.stdin, stdin_data),
                daemon=True,
            )
        )
    workers: list[threading.Thread] = []
    stops = _Stops()
    try:
        for worker in pending:
            worker.start()
            workers.append(worker)
        deadline = time.monotonic() + timeout_s
        stops = _supervise(
            process, workers, job, pgid, cancel, deadline, stdout_overflow
        )
    finally:
        _finish(process, workers, job, pgid)

    stdout, stdout_truncated = captured.get("stdout", (b"", False))
    stderr, stderr_truncated = captured.get("stderr", (b"", False))
    return CliProcessResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        timed_out=stops.timed_out,
        cancelled=stops.cancelled,
        output_limited=stops.output_limited,
    )
