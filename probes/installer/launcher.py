"""Start the bundled empty app on a free port and open the browser.

The probe runs this through the installed shortcut on Windows and through `start.sh` on
Linux, both without arguments. It writes the chosen port, the absolute interpreter paths
and the server pid to `port.json` next to this file, or to `--port-file`, only after
`GET /health` answers, so a reader of that file never talks to a half-started server.

Exit codes: 0 when the server started (it then blocks until stopped), 1 when the server
did not become healthy. The probe treats a nonzero exit as a result of the thing under
test, not as a harness error.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
START_TIMEOUT = 120.0
POLL_INTERVAL = 0.2


def free_port(host: str = HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def wait_health(port: int, timeout: float = START_TIMEOUT) -> dict:
    url = f"http://{HOST}:{port}/health"
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if response.status == 200 and payload.get("status") == "ok":
                return payload
            last = f"status {response.status}, body {payload!r}"
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            last = str(exc)
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"health check did not pass after {timeout:g}s: {last}")


def write_port_file(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def server_command(port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "health_app:app",
        "--host",
        HOST,
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]


def default_port_file() -> Path:
    """The port record a shortcut or start.sh reads when no argument is given."""
    return Path(__file__).resolve().parent / "port.json"


def port_file(args: argparse.Namespace) -> Path:
    return args.port_file or default_port_file()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-file", type=Path, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout", type=float, default=START_TIMEOUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, opener=webbrowser.open) -> int:
    args = parse_args(argv)
    record_path = port_file(args)
    port = free_port()
    app_dir = Path(__file__).resolve().parent
    process = subprocess.Popen(
        server_command(port),
        cwd=str(app_dir / "app"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    stopped = False

    def stop(_signum=None, _frame=None) -> None:
        nonlocal stopped
        if stopped:
            return
        stopped = True
        process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        try:
            payload = wait_health(port, args.timeout)
        except RuntimeError as exc:
            error = str(exc)
            if process.poll() is None:
                process.terminate()
            stderr = ""
            try:
                _out, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            write_port_file(
                record_path,
                {
                    "error": error,
                    "server_stderr": stderr[-1200:],
                    "launcher_python": sys.executable,
                },
            )
            print(error, file=sys.stderr)
            return 1
        url = f"http://{HOST}:{port}/"
        record = {
            "port": port,
            "url": url,
            "launcher_pid": os.getpid(),
            "server_pid": process.pid,
            "launcher_python": sys.executable,
            "server_python": payload.get("python", ""),
            "server_python_version": payload.get("version", ""),
        }
        if not args.no_browser:
            try:
                record["browser_opened"] = bool(opener(url))
            except Exception as exc:  # noqa: BLE001 - opening the browser is not a gate
                record["browser_opened"] = False
                record["browser_error"] = f"{type(exc).__name__}: {exc}"
        write_port_file(record_path, record)
        while process.poll() is None:
            time.sleep(0.2)
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
