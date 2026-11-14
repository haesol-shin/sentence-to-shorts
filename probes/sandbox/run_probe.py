#!/usr/bin/env python3
"""Run the sandbox probe programs under the parent supervisor.

The parent owns every limit: wall time, stdout and stderr byte caps, process tree
kill, and the memory cap when the host offers one. Runner output is treated as an
untrusted byte stream; media payloads are validated here, and a claimed verdict
from inside the sandbox is never trusted.

A failure of the program under test is a result. It is recorded in result.json
and the probe exits 0. A nonzero exit means a harness error only.

    python probes/sandbox/run_probe.py --runtime <dir> --out probes/sandbox/out
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import validate

HERE = Path(__file__).resolve().parent
DEFAULT_PROGRAMS = HERE / "programs.json"
DEFAULT_OUT = HERE / "out"
RUNNER = HERE / "runner.js"
PROTOCOL = 1

DEFAULT_LIMITS = {
    "wall_ms": 60_000,
    "stdout_bytes": 48 * 1024 * 1024,
    "stderr_bytes": 64 * 1024,
    "request_bytes": 12 * 1024 * 1024,
}
MEMORY_CAP_BYTES = 1024 * 1024 * 1024
DENIAL_VERDICTS = {"rejected", "invalid_output", "timeout", "output_limit", "memory_limit"}
MET = {
    "pass": {"passed"},
    "reject": DENIAL_VERDICTS,
    "measure": DENIAL_VERDICTS | {"measured", "escape"},
}


@dataclass
class Outcome:
    exit_code: int | None
    signal: int | None
    timed_out: bool
    stdout: bytes
    stderr: bytes
    stdout_bytes: int
    stderr_bytes: int
    stdout_overflow: bool
    stderr_overflow: bool
    wall_ms: int
    memory_cap: dict = field(default_factory=dict)


class Capture(threading.Thread):
    """Read a pipe, keep at most cap bytes, and flag an overflow."""

    def __init__(self, stream, cap: int) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.cap = cap
        self.data = bytearray()
        self.total = 0
        self.overflow = False
        self._read = getattr(stream, "read1", stream.read)

    def run(self) -> None:
        while True:
            try:
                chunk = self._read(65536)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            self.total += len(chunk)
            room = self.cap + 1 - len(self.data)
            if room > 0:
                self.data += chunk[:room]
            if self.total > self.cap:
                self.overflow = True


def kill_tree(process: subprocess.Popen) -> None:
    """Kill the child and every process it started."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def _write_stdin(pipe, payload: bytes) -> None:
    try:
        pipe.write(payload)
        pipe.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except (BrokenPipeError, OSError):
            pass


def posix_memory_wrapper(cap_bytes: int) -> tuple[list[str] | None, str]:
    """Return a systemd-run prefix that applies a hard memory cap, or a reason."""
    if os.name != "posix":
        return None, "not a POSIX host"
    executable = shutil.which("systemd-run")
    if not executable:
        return None, "systemd-run not found"
    prefix = [
        executable,
        "--user",
        "--scope",
        "--collect",
        "--quiet",
        "-p",
        f"MemoryMax={cap_bytes}",
    ]
    try:
        probe = subprocess.run(
            prefix + ["true"], capture_output=True, timeout=20, check=False, env={}
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f"systemd-run self-test failed: {error}"
    if probe.returncode != 0:
        detail = probe.stderr.decode("utf-8", "replace").strip().splitlines()
        return None, "systemd-run --user --scope unavailable with the sandbox environment: " + (
            detail[-1] if detail else "unknown"
        )
    return prefix, "systemd-run --user --scope MemoryMax"


def windows_memory_job(cap_bytes: int):
    """Attach the process to a Job Object with a process memory limit."""
    if os.name != "nt":
        return None, "not a Windows host"
    try:
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None, f"CreateJobObject failed: {ctypes.get_last_error()}"
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x100 | 0x2000  # process memory, kill on close
        info.ProcessMemoryLimit = cap_bytes
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            return None, f"SetInformationJobObject failed: {ctypes.get_last_error()}"
        return handle, "Job Object process memory limit"
    except Exception as error:  # noqa: BLE001 - a missing cap must not stop the probe
        return None, f"Job Object unavailable: {error}"


def attach_job(handle, pid: int) -> str:
    if not handle or os.name != "nt":
        return ""
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        process = kernel32.OpenProcess(0x0100 | 0x0001 | 0x0400, False, pid)
        if not process:
            return f"OpenProcess failed: {ctypes.get_last_error()}"
        assigned = kernel32.AssignProcessToJobObject(handle, process)
        kernel32.CloseHandle(process)
        if not assigned:
            return f"AssignProcessToJobObject failed: {ctypes.get_last_error()}"
        return ""
    except Exception as error:  # noqa: BLE001 - record, do not abort
        return f"Job Object assignment failed: {error}"


def child_environment(cache_dir: Path) -> dict[str, str]:
    """A minimal environment. The sandbox denies env reads, so this only boots Deno."""
    environment = {
        "DENO_DIR": str(cache_dir),
        "DENO_NO_UPDATE_CHECK": "1",
        "NO_COLOR": "1",
    }
    if os.name == "nt":
        for name in ("SystemRoot", "windir", "PATHEXT"):
            if name in os.environ:
                environment[name] = os.environ[name]
        environment["TEMP"] = str(cache_dir)
        environment["TMP"] = str(cache_dir)
    return environment


def supervise(
    command: list[str],
    request: bytes,
    limits: dict,
    workdir: Path,
    memory_prefix: list[str] | None,
    job_handle,
) -> Outcome:
    cache_dir = workdir / "deno-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    full_command = (memory_prefix or []) + command
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP
    started = time.monotonic()
    process = subprocess.Popen(
        full_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(workdir),
        env=child_environment(cache_dir),
        start_new_session=os.name == "posix",
        creationflags=creationflags,
    )
    job_detail = attach_job(job_handle, process.pid)
    stdout = Capture(process.stdout, int(limits["stdout_bytes"]))
    stderr = Capture(process.stderr, int(limits["stderr_bytes"]))
    stdout.start()
    stderr.start()
    writer = threading.Thread(target=_write_stdin, args=(process.stdin, request), daemon=True)
    writer.start()

    deadline = started + int(limits["wall_ms"]) / 1000
    timed_out = False
    while process.poll() is None:
        if stdout.overflow or stderr.overflow:
            kill_tree(process)
            break
        if time.monotonic() > deadline:
            timed_out = True
            kill_tree(process)
            break
        time.sleep(0.01)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        process.wait(timeout=30)
    stdout.join(timeout=5)
    stderr.join(timeout=5)
    for stream in (process.stdout, process.stderr):
        try:
            stream.close()
        except OSError:
            pass

    wall_ms = int((time.monotonic() - started) * 1000)
    return Outcome(
        exit_code=process.returncode,
        signal=-process.returncode if (process.returncode or 0) < 0 else None,
        timed_out=timed_out,
        stdout=bytes(stdout.data),
        stderr=bytes(stderr.data),
        stdout_bytes=stdout.total,
        stderr_bytes=stderr.total,
        stdout_overflow=stdout.overflow,
        stderr_overflow=stderr.overflow,
        wall_ms=wall_ms,
        memory_cap={"detail": job_detail} if job_detail else {},
    )


def protocol_lines(payload: bytes) -> list[str]:
    text = payload.decode("utf-8", "replace")
    return [line for line in text.splitlines() if line.strip()]


def payload_detail(value: dict) -> tuple[str, str]:
    """Validate a runner payload. The runner's own verdict is not trusted."""
    kind = value.get("kind")
    if kind == "json":
        return "payload", json.dumps(value.get("value"), ensure_ascii=False, sort_keys=True)[:400]
    if kind not in ("png", "wav"):
        return "invalid_output", f"unknown payload kind {kind!r}"
    try:
        data = base64.b64decode(value.get("base64") or "", validate=True)
    except (ValueError, TypeError) as error:
        return "invalid_output", f"base64 decode failed: {error}"
    check = validate.check_png if kind == "png" else validate.check_wav
    accepted, detail = check(data)
    return ("payload", detail) if accepted else ("invalid_output", detail)


def run_program(
    deno: Path,
    flags: list[str],
    runtime_dir: Path,
    memory_prefix: list[str] | None,
    job_handle,
    program: dict,
    limits: dict,
) -> dict:
    source_path = HERE / "programs" / program["file"]
    source = source_path.read_text(encoding="utf-8")
    request = json.dumps(
        {
            "protocol": PROTOCOL,
            "run_id": program["id"],
            "entry": program["entry"],
            "arg_names": program["arg_names"],
            "args": program["args"],
            "output": program["output"],
            "async_source": bool(program.get("async")),
            "source": source,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    if len(request) > int(limits["request_bytes"]):
        return {"harness_error": f"request is {len(request)} bytes"}

    command = [str(deno), *flags, str(RUNNER), str(runtime_dir)]
    with tempfile.TemporaryDirectory(prefix="probe-run-") as workdir:
        outcome = supervise(
            command, request, limits, Path(workdir), memory_prefix, job_handle
        )
    return {"outcome": outcome, "request_bytes": len(request)}


def describe_stderr(data: bytes) -> str:
    lines = data.decode("utf-8", "replace").strip().splitlines()
    return " | ".join(line.strip() for line in lines[-3:] if line.strip())[:400]


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def classify(program: dict, result: dict, memory_cap: dict) -> dict:
    if "harness_error" in result:
        return {
            "verdict": "harness_error",
            "detail": result["harness_error"],
            "met": False,
        }
    outcome: Outcome = result["outcome"]
    detail = ""
    verdict = "harness_error"
    response = None
    error_message = ""

    if outcome.timed_out:
        verdict = "timeout"
        detail = f"parent killed the process tree after {outcome.wall_ms} ms"
    elif outcome.stdout_overflow or outcome.stderr_overflow:
        verdict = "output_limit"
        stream = "stdout" if outcome.stdout_overflow else "stderr"
        detail = f"{stream} passed the {stream} byte cap"
    else:
        lines = protocol_lines(outcome.stdout)
        if len(lines) == 1:
            try:
                response = json.loads(lines[0])
            except json.JSONDecodeError:
                response = None
        if len(lines) > 1:
            verdict, detail = "harness_error", f"{len(lines)} protocol lines on stdout"
        elif response is None:
            if outcome.signal is not None and program.get("contain") == "memory":
                verdict = "memory_limit"
                detail = (
                    "process died from signal "
                    f"{outcome.signal} without a protocol line; memory cap applied: "
                    f"{bool(memory_cap.get('applied'))}"
                )
                if not memory_cap.get("applied"):
                    verdict, detail = "crashed", detail + " (no hard memory cap)"
            else:
                verdict = "crashed"
                detail = f"no protocol line; exit {outcome.exit_code}, stderr: {describe_stderr(outcome.stderr)}"
        elif response.get("status") == "error":
            code = (response.get("error") or {}).get("code")
            message = ((response.get("error") or {}).get("message") or "").strip()
            error_message = message[:2000]
            summary = last_line(message)[:300]
            if code == "permission_denied":
                verdict, detail = "rejected", summary
            elif code == "memory_limit":
                verdict, detail = "memory_limit", summary
            elif code in ("invalid_request", "permission_gate", "bootstrap_failed"):
                verdict, detail = "harness_error", f"{code}: {summary}"
            else:
                verdict, detail = "crashed", f"{code or 'error'}: {summary}"
        elif response.get("status") == "ok":
            value = response.get("value") or {}
            kind, payload_text = payload_detail(value)
            if kind != "payload" or value.get("kind") != program["output"]:
                verdict = "invalid_output"
                detail = payload_text if kind == "invalid_output" else (
                    f"payload kind {value.get('kind')!r}, expected {program['output']!r}"
                )
            elif program["expect"] == "reject":
                verdict, detail = "escape", payload_text
            elif program["expect"] == "measure":
                verdict, detail = "measured", payload_text
            else:
                verdict, detail = "passed", payload_text
        else:
            verdict, detail = "harness_error", "protocol line without status"

    return {
        "verdict": verdict,
        "detail": detail,
        "error_message": error_message,
        "met": verdict in MET.get(program["expect"], set()),
        "request_bytes": result.get("request_bytes"),
        "exit_code": outcome.exit_code,
        "signal": outcome.signal,
        "wall_ms": outcome.wall_ms,
        "stdout_bytes": outcome.stdout_bytes,
        "stderr_bytes": outcome.stderr_bytes,
        "stderr_tail": describe_stderr(outcome.stderr),
        "captured": (response.get("captured") if response else None),
        "timings": (response.get("timings") if response else None),
        "permissions": (response.get("permissions") if response else None),
        "gate": (response.get("gate") if response else None),
        "memory_job": outcome.memory_cap.get("detail") or None,
    }


def memory_cap_setup(enabled: bool) -> tuple[list[str] | None, dict, object]:
    if not enabled:
        return None, {"applied": False, "mechanism": "disabled", "detail": "disabled by flag"}, None
    if os.name == "nt":
        handle, detail = windows_memory_job(MEMORY_CAP_BYTES)
        return None, {
            "applied": handle is not None,
            "mechanism": "job_object" if handle else "none",
            "detail": detail,
        }, handle
    prefix, detail = posix_memory_wrapper(MEMORY_CAP_BYTES)
    return prefix, {
        "applied": prefix is not None,
        "mechanism": "systemd-run" if prefix else "none",
        "detail": detail,
    }, None


def peak_rss_bytes() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    scale = 1024 if sys.platform.startswith("linux") else 1
    return int(usage.ru_maxrss) * scale


def format_summary(result: dict) -> str:
    lines = [
        f"## Sandbox probe ({result['os']})",
        "",
        "| program | expect | verdict | met | detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for run in result["runs"]:
        detail = str(run["detail"]).replace("|", "/")[:160]
        lines.append(
            f"| {run['id']} | {run['expect']} | {run['verdict']} | {'yes' if run['met'] else 'no'} | {detail} |"
        )
    lines += [
        "",
        f"Gate: {result['gate']}",
        f"Memory cap: {result['memory_cap']['applied']} ({result['memory_cap']['mechanism']}: {str(result['memory_cap']['detail']).replace('|', '/')})",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--deno", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--programs", type=Path, default=DEFAULT_PROGRAMS)
    parser.add_argument("--os-label", default=None)
    parser.add_argument("--only", action="append", default=None)
    parser.add_argument("--no-memory-cap", action="store_true")
    args = parser.parse_args(argv)

    manifest = json.loads(args.programs.read_text(encoding="utf-8"))
    runtime = args.runtime.resolve()
    deno = args.deno or runtime / "deno" / ("deno.exe" if os.name == "nt" else "deno")
    os_label = args.os_label or ("windows" if os.name == "nt" else f"linux-{os.uname().machine}")

    flags = [
        "run",
        "--quiet",
        "--no-prompt",
        "--no-config",
        "--cached-only",
        f"--allow-read={runtime}",
        "--deny-write",
        "--deny-net",
        "--deny-env",
        "--deny-run",
        "--deny-ffi",
        "--deny-sys",
        "--deny-import",
    ]
    memory_prefix, memory_cap, job_handle = memory_cap_setup(not args.no_memory_cap)

    programs = manifest["programs"]
    if args.only:
        wanted = set(args.only)
        programs = [program for program in programs if program["id"] in wanted]
        missing = wanted - {program["id"] for program in programs}
        if missing:
            parser.error(f"unknown program ids: {sorted(missing)}")

    runs = []
    started = time.time()
    harness_errors = 0
    for program in programs:
        limits = dict(DEFAULT_LIMITS)
        limits.update(manifest.get("limits", {}))
        for key in ("wall_ms", "stdout_bytes", "stderr_bytes"):
            if key in program:
                limits[key] = program[key]
        result = run_program(
            deno, flags, runtime, memory_prefix, job_handle, program, limits
        )
        record = classify(program, result, memory_cap)
        record["id"] = program["id"]
        record["expect"] = program["expect"]
        record["limits"] = limits
        if record["verdict"] == "harness_error":
            harness_errors += 1
        runs.append(record)

    escapes = [run["id"] for run in runs if run["verdict"] == "escape"]
    unmet = [run["id"] for run in runs if not run["met"]]
    if escapes:
        gate = "stop"
    elif harness_errors:
        gate = "harness_error"
    elif unmet:
        gate = "review"
    elif memory_cap["applied"]:
        gate = "proceed"
    else:
        gate = "proceed_with_timeout_and_output_caps"

    verified = {}
    verified_path = runtime / "runtime-verified.json"
    if verified_path.is_file():
        verified = json.loads(verified_path.read_text(encoding="utf-8"))
    peak_rss = peak_rss_bytes()

    result = {
        "schema": 1,
        "probe": "sandbox",
        "protocol": PROTOCOL,
        "os": os_label,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "deno": {
            "version": (verified.get("deno") or {}).get("version"),
            "flags": flags,
        },
        "pyodide": verified.get("pyodide"),
        "verified_files": verified.get("verified"),
        "memory_cap": memory_cap,
        "cold_start_ms": runs[0]["wall_ms"] if runs else None,
        "peak_rss_bytes": peak_rss,
        "peak_rss_method": "getrusage(RUSAGE_CHILDREN) max, whole probe"
        if peak_rss
        else "unavailable",
        "gate": gate,
        "summary": {
            "total": len(runs),
            "met": sum(1 for run in runs if run["met"]),
            "unmet": unmet,
            "escapes": escapes,
            "harness_errors": harness_errors,
        },
        "runs": runs,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    result_path = args.out / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary = format_summary(result)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary)

    if job_handle and os.name == "nt":
        try:
            import ctypes

            ctypes.WinDLL("kernel32").CloseHandle(job_handle)
        except Exception:  # noqa: BLE001 - closing a handle must not mask results
            pass
    return 3 if harness_errors else 0


if __name__ == "__main__":
    sys.exit(main())
