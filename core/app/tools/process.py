"""Run an external program with an argument array, an env allowlist and hard limits.

The process tree is killed on timeout or cancel: a process group on POSIX and a
kill-on-close Job Object on Windows. Output beyond the byte caps is read and
discarded so the child never blocks on a full pipe; a caller can ask for the tree
to be killed instead when stdout passes its cap.

An optional memory cap covers the whole tree: a Job Object memory limit on
Windows, and a delegated cgroup v2 scope (`systemd-run --user --scope`) on Linux.
`memory_cap_status` says whether the cap can be applied on this host. When it
cannot, the run goes on without one and the status names the reason, so callers
report the cap as unverified instead of claiming it.
"""

from __future__ import annotations

import functools
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
        "DENO_DIR",
        "DENO_NO_UPDATE_CHECK",
        "NO_COLOR",
    }
)
DEFAULT_STDOUT_BYTES = 48 * 1024 * 1024
DEFAULT_STDERR_BYTES = 64 * 1024
KILL_GRACE_S = 5.0
POLL_S = 0.02

# Fixed absolute paths: the cgroup wrapper is never looked up through PATH.
SYSTEMD_RUN_CANDIDATES = ("/usr/bin/systemd-run", "/bin/systemd-run")
ENV_CANDIDATES = ("/usr/bin/env", "/bin/env")
SH_CANDIDATES = ("/bin/sh", "/usr/bin/sh")
# Variables that let systemd-run reach the user manager. Only the wrapper gets
# them; `env -i` starts the real child with the caller's environment alone.
USER_BUS_ENV = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
CGROUP_SELF_TEST_S = 20.0
# A Job Object refuses allocations at the limit, so the peak stops just below it.
JOB_MEMORY_SLACK = 64 * 1024 * 1024
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


@dataclass(frozen=True)
class MemoryCap:
    """Whether a hard memory cap for a process tree can be applied on this host."""

    applied: bool
    mechanism: str  # "job_object", "cgroup_v2" or "none"
    reason: str
    limit_bytes: int


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
    output_limited: bool = False
    memory_limited: bool = False
    memory_cap: MemoryCap | None = None

    @property
    def ok(self) -> bool:
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.cancelled
            and not self.output_limited
            and not self.memory_limited
        )


def build_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy only allowlisted variables from the parent and the caller's extras."""
    env = {key: value for key, value in os.environ.items() if key in ALLOWED_ENV}
    if extra:
        for key, value in extra.items():
            if key not in ALLOWED_ENV:
                raise ValueError(f"environment variable {key} is not allowlisted")
            env[key] = value
    return env


def _first_file(candidates: Sequence[str]) -> str | None:
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _user_bus_env() -> dict[str, str]:
    return {name: os.environ[name] for name in USER_BUS_ENV if name in os.environ}


def _cgroup_prefix(limit_bytes: int) -> list[str] | None:
    systemd_run = _first_file(SYSTEMD_RUN_CANDIDATES)
    env_binary = _first_file(ENV_CANDIDATES)
    if systemd_run is None or env_binary is None:
        return None
    return [
        systemd_run,
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        "-p",
        f"MemoryMax={limit_bytes}",
        "-p",
        "MemorySwapMax=0",
        "--",
        env_binary,
        "-i",
    ]


def _cgroup_status(limit_bytes: int) -> MemoryCap:
    prefix = _cgroup_prefix(limit_bytes)
    shell = _first_file(SH_CANDIDATES)
    if prefix is None or shell is None:
        return MemoryCap(False, "none", "systemd-run is not installed", limit_bytes)
    # The scope must exist and report this exact memory.max; a scope without the
    # memory controller would accept the property and enforce nothing.
    script = 'read -r line < /proc/self/cgroup; cat "/sys/fs/cgroup${line#0::}/memory.max"'
    try:
        probe = subprocess.run(
            [*prefix, shell, "-c", script],
            env=_user_bus_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=CGROUP_SELF_TEST_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return MemoryCap(False, "none", "systemd user scope did not start", limit_bytes)
    if probe.returncode != 0:
        return MemoryCap(False, "none", "systemd user scope is unavailable", limit_bytes)
    if probe.stdout.strip() != str(limit_bytes).encode("ascii"):
        return MemoryCap(
            False, "none", "delegated cgroup v2 memory controller is missing", limit_bytes
        )
    return MemoryCap(True, "cgroup_v2", "systemd user scope with MemoryMax", limit_bytes)


def _job_object_status(limit_bytes: int) -> MemoryCap:
    try:
        job = _JobObject(memory_limit_bytes=limit_bytes)
    except OSError:
        return MemoryCap(False, "none", "Job Object memory limit is unavailable", limit_bytes)
    job.close()
    return MemoryCap(True, "job_object", "Job Object job memory limit", limit_bytes)


@functools.lru_cache(maxsize=8)
def memory_cap_status(limit_bytes: int) -> MemoryCap:
    """Check once per limit whether this host can cap the memory of a process tree."""
    if limit_bytes < 1:
        raise ValueError("limit_bytes must be positive")
    if sys.platform == "win32":
        return _job_object_status(limit_bytes)
    if sys.platform.startswith("linux"):
        return _cgroup_status(limit_bytes)
    return MemoryCap(False, "none", f"no memory cap mechanism on {sys.platform}", limit_bytes)


class _JobObject:
    """Windows Job Object with kill-on-close, so grandchildren die with the job."""

    def __init__(self, memory_limit_bytes: int | None = None) -> None:
        if os.name != "nt":
            raise OSError("Job Objects exist only on Windows")
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._memory_limit_bytes = memory_limit_bytes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self._kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        self._kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = self._job_info()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if memory_limit_bytes is not None:
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = memory_limit_bytes
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
        if not self._kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):  # noqa: SLF001
            raise self._ctypes.WinError(self._ctypes.get_last_error())

    def memory_limit_reached(self) -> bool:
        """True when the peak job memory came within the slack of the limit."""
        if self._memory_limit_bytes is None or not self._handle:
            return False
        ctypes = self._ctypes
        info = self._job_info()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return False
        return info.PeakJobMemoryUsed + JOB_MEMORY_SLACK >= self._memory_limit_bytes

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
    memory_cap: MemoryCap | None,
) -> tuple[subprocess.Popen[bytes], _JobObject | None, int | None]:
    command = list(argv)
    popen_env = dict(env)
    if memory_cap is not None and memory_cap.mechanism == "cgroup_v2":
        prefix = _cgroup_prefix(memory_cap.limit_bytes)
        if prefix is None:
            raise OSError("the cgroup wrapper disappeared after the self-test")
        # `env -i` clears the wrapper environment, then sets exactly the caller's.
        command = [*prefix, *(f"{key}={value}" for key, value in env.items()), *command]
        popen_env = _user_bus_env()
    kwargs: dict[str, object] = {
        "cwd": str(cwd) if cwd is not None else None,
        "env": popen_env,
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
        limit = (
            memory_cap.limit_bytes
            if memory_cap is not None and memory_cap.mechanism == "job_object"
            else None
        )
        job = _JobObject(memory_limit_bytes=limit)
    try:
        process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
    except BaseException:
        if job is not None:
            job.close()
        raise
    pgid = None if os.name == "nt" else os.getpgid(process.pid)
    if job is not None:
        try:
            job.assign(process)
        except OSError:
            process.kill()
            process.wait()
            job.close()
            raise
    return process, job, pgid


def _drain(stream, limit: int, overflow: threading.Event) -> tuple[bytes, bool]:  # type: ignore[no-untyped-def]
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
            overflow.set()
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


@dataclass
class _Stops:
    timed_out: bool = False
    cancelled: bool = False
    output_limited: bool = False


def _supervise(
    process: subprocess.Popen[bytes],
    workers: list[threading.Thread],
    job: _JobObject | None,
    pgid: int | None,
    cancel: CancelToken | None,
    deadline: float | None,
    input_failure: list[BaseException],
    stdout_overflow: threading.Event | None,
) -> _Stops:
    stops = _Stops()
    while process.poll() is None or any(worker.is_alive() for worker in workers):
        if input_failure:
            _kill_tree(process, job, pgid)
            break
        if stdout_overflow is not None and stdout_overflow.is_set():
            stops.output_limited = True
            _kill_tree(process, job, pgid)
            break
        if cancel is not None and cancel.is_set():
            stops.cancelled = True
            _kill_tree(process, job, pgid)
            break
        if deadline is not None and time.monotonic() >= deadline:
            stops.timed_out = True
            _kill_tree(process, job, pgid)
            break
        if cancel is not None:
            cancel.wait(POLL_S)
        else:
            time.sleep(POLL_S)
    return stops


def _validate_run(
    argv: Sequence[str],
    *,
    timeout_s: float | None,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    stdin_data: bytes | Iterable[bytes] | None,
    memory_limit_bytes: int | None,
) -> None:
    if not argv:
        raise ValueError("argv must contain the program")
    if max_stdout_bytes < 1 or max_stderr_bytes < 1:
        raise ValueError("output limits must be positive")
    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if memory_limit_bytes is not None and memory_limit_bytes < 1:
        raise ValueError("memory_limit_bytes must be positive")
    if isinstance(stdin_data, str):
        raise TypeError("stdin_data must be bytes or an iterable of bytes")


def _memory_limited(
    process: subprocess.Popen[bytes],
    job: _JobObject | None,
    memory_cap: MemoryCap | None,
    stops: _Stops,
) -> bool:
    if memory_cap is None or not memory_cap.applied or process.returncode in (0, None):
        return False
    if stops.timed_out or stops.cancelled or stops.output_limited:
        return False
    if memory_cap.mechanism == "job_object":
        return job is not None and job.memory_limit_reached()
    # The cgroup OOM killer ends the tree with SIGKILL; this run sent none.
    return process.returncode == -signal.SIGKILL


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
    kill_on_stdout_limit: bool = False,
    memory_limit_bytes: int | None = None,
) -> ProcessResult:
    """Run argv under the limits.

    `kill_on_stdout_limit` kills the tree as soon as stdout passes its cap and
    sets `output_limited`. `memory_limit_bytes` applies the host memory cap when
    `memory_cap_status` reports one; the result carries that status either way.
    """
    _validate_run(
        argv,
        timeout_s=timeout_s,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
        stdin_data=stdin_data,
        memory_limit_bytes=memory_limit_bytes,
    )

    started = time.monotonic()
    effective_env = build_env() if env is None else dict(env)
    if env is not None:
        unknown = sorted(set(env) - ALLOWED_ENV)
        if unknown:
            raise ValueError(f"environment variable {unknown[0]} is not allowlisted")
    memory_cap = None if memory_limit_bytes is None else memory_cap_status(memory_limit_bytes)
    applied_cap = memory_cap if memory_cap is not None and memory_cap.applied else None
    process, job, pgid = _start_process(
        argv,
        cwd=cwd,
        env=effective_env,
        has_stdin=stdin_data is not None,
        memory_cap=applied_cap,
    )
    captured: dict[str, tuple[bytes, bool]] = {}
    input_failure: list[BaseException] = []
    stdout_overflow = threading.Event()
    stderr_overflow = threading.Event()

    def collect(name: str, stream, limit: int, overflow: threading.Event) -> None:  # type: ignore[no-untyped-def]
        captured[name] = _drain(stream, limit, overflow)

    workers = [
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
        workers.append(
            threading.Thread(
                target=_write_stdin,
                args=(process.stdin, stdin_data, input_failure),
                daemon=True,
            )
        )
    for worker in workers:
        worker.start()

    deadline = None if timeout_s is None else started + timeout_s
    stops = _supervise(
        process,
        workers,
        job,
        pgid,
        cancel,
        deadline,
        input_failure,
        stdout_overflow if kill_on_stdout_limit else None,
    )
    if kill_on_stdout_limit and stdout_overflow.is_set():
        # A child that writes past the cap and exits before the next poll is
        # never killed, but its output is still over the limit.
        stops.output_limited = True

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
    memory_limited = _memory_limited(process, job, applied_cap, stops)
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
        timed_out=stops.timed_out,
        cancelled=stops.cancelled,
        duration_ms=duration_ms,
        output_limited=stops.output_limited,
        memory_limited=memory_limited,
        memory_cap=memory_cap,
    )
