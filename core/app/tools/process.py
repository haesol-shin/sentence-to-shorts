"""Run an external program with an argument array, an env allowlist and hard limits.

The process tree is killed on timeout or cancel: a process group on POSIX and a
kill-on-close Job Object on Windows. Output beyond the byte caps is read and
discarded so the child never blocks on a full pipe.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.ports import CancelToken

ALLOWED_ENV = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    }
)
DEFAULT_STDOUT_BYTES = 48 * 1024 * 1024
DEFAULT_STDERR_BYTES = 64 * 1024
KILL_GRACE_S = 5.0
POLL_S = 0.02


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    cancelled: bool
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.cancelled


def build_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy only allowlisted variables from the parent and the caller's extras."""
    env = {key: value for key, value in os.environ.items() if key in ALLOWED_ENV}
    if extra:
        for key, value in extra.items():
            if key not in ALLOWED_ENV:
                raise ValueError(f"environment variable {key} is not allowlisted")
            env[key] = value
    return env


class _JobObject:
    """Windows Job Object with kill-on-close, so grandchildren die with the job."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Job Objects exist only on Windows")
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = self._job_info()
        size = ctypes.sizeof(info)
        if not self._kernel32.SetInformationJobObject(
            self._handle, 9, ctypes.byref(info), size
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        self._wintypes = wintypes

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

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        return info

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        if not self._kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):  # noqa: SLF001
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _start_process(
    argv: Sequence[str],
    *,
    cwd: Path | None,
    env: Mapping[str, str],
    has_stdin: bool,
) -> tuple[subprocess.Popen[bytes], _JobObject | None, int | None]:
    kwargs: dict[str, object] = {
        "cwd": str(cwd) if cwd is not None else None,
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
    process = subprocess.Popen(list(argv), **kwargs)  # type: ignore[arg-type]
    pgid = None if os.name == "nt" else os.getpgid(process.pid)
    if sys.platform == "win32":
        job = _JobObject()
        job.assign(process)
    return process, job, pgid


def _drain(stream, limit: int) -> tuple[bytes, bool]:  # type: ignore[no-untyped-def]
    data = bytearray()
    truncated = False
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        room = limit - len(data)
        if room > 0:
            data.extend(chunk[:room])
        if len(chunk) > max(0, room):
            truncated = True
    return bytes(data), truncated


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


def _write_stdin(  # type: ignore[no-untyped-def]
    stream, data: bytes | Iterable[bytes], failure: list[BaseException]
) -> None:
    try:
        if isinstance(data, (bytes, bytearray, memoryview)):
            stream.write(data)
        else:
            try:
                iterator = iter(data)
            except BaseException as error:  # noqa: BLE001 - reported to the caller
                failure.append(error)
                return
            while True:
                try:
                    chunk = next(iterator)
                except StopIteration:
                    break
                except BaseException as error:  # noqa: BLE001 - reported to the caller
                    failure.append(error)
                    return
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    failure.append(TypeError("stdin chunks must be bytes"))
                    return
                stream.write(chunk)
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (BrokenPipeError, OSError, ValueError):
            pass


def _supervise(
    process: subprocess.Popen[bytes],
    workers: list[threading.Thread],
    job: _JobObject | None,
    pgid: int | None,
    cancel: CancelToken | None,
    deadline: float | None,
    input_failure: list[BaseException],
) -> tuple[bool, bool]:
    timed_out = False
    cancelled = False
    while process.poll() is None or any(worker.is_alive() for worker in workers):
        if input_failure:
            _kill_tree(process, job, pgid)
            break
        if cancel is not None and cancel.is_set():
            cancelled = True
            _kill_tree(process, job, pgid)
            break
        if deadline is not None and time.monotonic() >= deadline:
            timed_out = True
            _kill_tree(process, job, pgid)
            break
        if cancel is not None:
            cancel.wait(POLL_S)
        else:
            time.sleep(POLL_S)
    return timed_out, cancelled


def _validate_run(
    argv: Sequence[str],
    *,
    timeout_s: float | None,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    stdin_data: bytes | Iterable[bytes] | None,
) -> None:
    if not argv:
        raise ValueError("argv must contain the program")
    if max_stdout_bytes < 1 or max_stderr_bytes < 1:
        raise ValueError("output limits must be positive")
    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if isinstance(stdin_data, str):
        raise TypeError("stdin_data must be bytes or an iterable of bytes")


def run(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float | None = None,
    max_stdout_bytes: int = DEFAULT_STDOUT_BYTES,
    max_stderr_bytes: int = DEFAULT_STDERR_BYTES,
    cancel: CancelToken | None = None,
    stdin_data: bytes | Iterable[bytes] | None = None,
) -> ProcessResult:
    _validate_run(
        argv,
        timeout_s=timeout_s,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
        stdin_data=stdin_data,
    )

    started = time.monotonic()
    effective_env = build_env() if env is None else dict(env)
    if env is not None:
        unknown = sorted(set(env) - ALLOWED_ENV)
        if unknown:
            raise ValueError(f"environment variable {unknown[0]} is not allowlisted")
    process, job, pgid = _start_process(
        argv, cwd=cwd, env=effective_env, has_stdin=stdin_data is not None
    )
    captured: dict[str, tuple[bytes, bool]] = {}
    input_failure: list[BaseException] = []

    def collect(name: str, stream, limit: int) -> None:  # type: ignore[no-untyped-def]
        captured[name] = _drain(stream, limit)

    workers = [
        threading.Thread(
            target=collect, args=("stdout", process.stdout, max_stdout_bytes), daemon=True
        ),
        threading.Thread(
            target=collect, args=("stderr", process.stderr, max_stderr_bytes), daemon=True
        ),
    ]
    if stdin_data is not None and process.stdin is not None:
        workers.append(
            threading.Thread(
                target=_write_stdin,
                args=(process.stdin, stdin_data, input_failure),
                daemon=True,
            )
        )
    for worker in workers:
        worker.start()

    timed_out = False
    cancelled = False
    deadline = None if timeout_s is None else started + timeout_s
    timed_out, cancelled = _supervise(
        process, workers, job, pgid, cancel, deadline, input_failure
    )

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

    stdout, stdout_truncated = captured.get("stdout", (b"", False))
    stderr, stderr_truncated = captured.get("stderr", (b"", False))
    if input_failure:
        raise input_failure[0]
    duration_ms = int((time.monotonic() - started) * 1000)
    return ProcessResult(
        argv=tuple(argv),
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        timed_out=timed_out,
        cancelled=cancelled,
        duration_ms=duration_ms,
    )
