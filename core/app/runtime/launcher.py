"""Local launcher: one instance, a free port, a pairing code, the server and the browser.

The distribution ships a small `dist.json` next to the program. It names the profile
(`dev` or `release`) and the deployment the distribution starts with, so the same code
runs both distributions by configuration. A value already set in the environment wins.
The entry script outside the app package passes in the settings loader and the app
factory; this module never imports the composition root.

The pairing URL carries a one-time code in its fragment. It goes only to the local
browser or the local terminal. It is never logged and never written to a file.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable, Collection, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.runtime import instance
from app.runtime.dev_cli import CliStatus, check_claude_cli
from app.runtime.web import StaticSite

DIST_NAME = "dist.json"
MAIN_SITE_NAME = "site-packages"
HEALTH_PATH = "/api/v1/health"
LOOPBACK = "127.0.0.1"
START_TIMEOUT_S = 120.0
HEALTH_POLL_S = 0.2
RECORD_WAIT_S = 30.0
PROFILES = ("dev", "release")
DEPLOYMENTS = ("local", "hosted")
LOG_NAME = "launcher.log"

log = logging.getLogger("launcher")


class AdapterTable(Protocol):
    adapters: Mapping[str, str]


class LaunchSettings(Protocol):
    profile: str
    deployment: str
    port: int
    lan: bool
    bind_host: str
    data_dir: Path
    runtime_dir: Path
    log_level: str
    providers: AdapterTable


Opener = Callable[[str], bool]
AppFactory = Callable[[LaunchSettings, Callable[[str], None]], Any]
Serve = Callable[[Any, socket.socket, LaunchSettings], bool]


@dataclass(frozen=True)
class Distribution:
    """The defaults a distribution ships with."""

    profile: str
    deployment: str
    web_dir: str
    profile_adapters: Mapping[str, Mapping[str, str]]
    align_python: str | None = None
    align_site: str | None = None


def _inside(value: object) -> bool:
    """True for a relative path of forward-slash parts that stays below the root."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def read_distribution(root: Path) -> Distribution | None:
    """The distribution file below `root`; None for a source checkout without one."""
    path = root / DIST_NAME
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    profile = payload.get("profile")
    deployment = payload.get("deployment", "local")
    web_dir = payload.get("web_dir", "web")
    profile_adapters = payload.get("profile_adapters", {})
    align_python = payload.get("align_python")
    align_site = payload.get("align_site")
    valid = isinstance(profile_adapters, dict) and all(
        name in (*PROFILES, "fixture")
        and isinstance(table, dict)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in table.items())
        for name, table in profile_adapters.items()
    )
    # The aligner environment is named by both fields or by neither.
    aligner = (align_python is None) == (align_site is None) and all(
        value is None or _inside(value) for value in (align_python, align_site)
    )
    if (
        profile not in PROFILES
        or deployment not in DEPLOYMENTS
        or not isinstance(web_dir, str)
        or not valid
        or not aligner
    ):
        raise ValueError(f"{DIST_NAME} is not a valid distribution file")
    return Distribution(
        profile=profile, deployment=deployment, web_dir=web_dir,
        profile_adapters=profile_adapters, align_python=align_python, align_site=align_site,
    )


def adapter_choices(
    dist: Distribution | None, profile: str, environ: Mapping[str, str]
) -> dict[str, str]:
    """Select providers for the effective profile, including an environment override.

    Both distributions carry all profile choices. Only the default profile differs.
    The developer profile reads `APP_LLM_ADAPTER` (`openai_compat`, `claude_cli` or
    `anthropic_api`). Without it, an `APP_LLM_BASE_URL` keeps `openai_compat` and no
    endpoint selects the official CLI, so a build started from a menu needs no
    environment variable. Release never inherits either.
    """
    if dist is None:
        return {}
    if profile not in dist.profile_adapters:
        raise ValueError(f"{DIST_NAME} has no adapters for profile {profile!r}")
    chosen = dict(dist.profile_adapters[profile])
    if profile != "dev":
        return chosen
    requested = environ.get("APP_LLM_ADAPTER")
    if requested in ("openai_compat", "claude_cli", "anthropic_api"):
        chosen["llm"] = requested
    elif not requested and not environ.get("APP_LLM_BASE_URL"):
        chosen["llm"] = "claude_cli"
    return chosen


def apply_distribution(
    root: Path, dist: Distribution | None, environ: MutableMapping[str, str]
) -> None:
    """Fill the environment defaults. Anything the user already set stays.

    A distribution also names its packages: the app's own `site-packages` and, when it
    ships one, the aligner interpreter and the aligner's packages. The workers that run
    in other processes read them from these variables.
    """
    if dist is not None:
        environ.setdefault("APP_PROFILE", dist.profile)
        environ.setdefault("APP_DEPLOYMENT", dist.deployment)
        environ.setdefault("APP_MAIN_SITE", str(root / MAIN_SITE_NAME))
        if dist.align_python is not None and dist.align_site is not None:
            environ.setdefault("APP_ALIGN_PYTHON", str(root / dist.align_python))
            environ.setdefault("APP_ALIGN_SITE", str(root / dist.align_site))
    environ.setdefault("APP_RUNTIME_DIR", str(root / "rt"))


class _Redacting(logging.Formatter):
    """Replace home, install and data folders so a log carries no absolute user path."""

    def __init__(self, replacements: Sequence[tuple[str, str]]) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self._replacements = sorted(replacements, key=lambda pair: -len(pair[0]))

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for source, label in self._replacements:
            if source:
                text = text.replace(source, label)
        return text


def open_log(root: Path, settings: LaunchSettings) -> logging.Handler:
    """Log launcher and server messages to `DATA_DIR/log/launcher.log`."""
    folder = settings.data_dir / "log"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        folder / LOG_NAME, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(
        _Redacting(
            [
                (str(root), "<install>"),
                (str(settings.data_dir), "<data>"),
                (str(Path.home()), "~"),
            ]
        )
    )
    for name in ("launcher", "app", "uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return handler


def _message_box(message: str) -> None:
    import ctypes

    ctypes.windll.user32.MessageBoxW(0, message, "Startup notice", 0x40)  # type: ignore[attr-defined]


def _say(message: str) -> None:
    """Tell the user. Without a console (a Windows shortcut) a message box is the screen."""
    if sys.stderr is not None:
        print(message, file=sys.stderr, flush=True)
    elif sys.platform == "win32":
        threading.Thread(target=_message_box, args=(message,), daemon=True).start()


def show_on_terminal(url: str) -> bool:
    """Write the pairing URL to a local terminal. False when there is none."""
    line = f"Pair this browser: {url}\n"
    if sys.stdout is not None and sys.stdout.isatty():
        sys.stdout.write(line)
        sys.stdout.flush()
        return True
    if sys.platform == "win32":
        return False
    try:
        with open("/dev/tty", "w", encoding="utf-8") as terminal:
            terminal.write(line)
    except OSError:
        return False
    return True


def wait_health(port: int, timeout: float, stop: threading.Event) -> bool:
    """True once the local server answers its health check."""
    url = f"http://{LOOPBACK}:{port}{HEALTH_PATH}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not stop.is_set():
        try:
            with opener.open(url, timeout=5.0) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        stop.wait(HEALTH_POLL_S)
    return False


def browser_url(display_url: str, port: int) -> str:
    """The same URL with the loopback host, for the browser on this computer."""
    parts = urlsplit(display_url)
    fragment = f"#{parts.fragment}" if parts.fragment else ""
    return f"http://{LOOPBACK}:{port}/{fragment}"


def _hosts(settings: LaunchSettings) -> Collection[str]:
    names = {LOOPBACK, "localhost", "[::1]"}
    if settings.lan and settings.bind_host not in ("", "0.0.0.0", "::", "[::]"):
        host = settings.bind_host
        names.add(f"[{host}]" if ":" in host and not host.startswith("[") else host)
    return {f"{name}:{settings.port}" for name in names}


def _record(settings: LaunchSettings, cli: CliStatus | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "pid": os.getpid(),
        "port": settings.port,
        "url": f"http://{LOOPBACK}:{settings.port}/",
        "profile": settings.profile,
        "deployment": settings.deployment,
        "python": sys.executable,
        "base_prefix": sys.base_prefix,
    }
    if cli is not None:
        record["claude_cli"] = {
            "state": cli.state,
            "version": cli.version,
            "message": cli.message,
        }
    return record


def _quiet_signals() -> None:
    """Let the server finish a stop signal and return, so the launcher cleans up.

    uvicorn re-raises a stop signal it handled to the handler that was installed before
    it started. With the default handler that ends the process before the record and the
    log are closed.
    """
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGINT", "SIGTERM"):
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, lambda _signum, _frame: None)


def _serve_uvicorn(app: Any, sock: socket.socket, settings: LaunchSettings) -> bool:
    import uvicorn

    _quiet_signals()

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_config=None,
            log_level=settings.log_level,
            lifespan="on",
            access_log=False,
        )
    )
    try:
        server.run(sockets=[sock])
    except SystemExit:
        # uvicorn exits the process when the app cannot start; report it as a failed start.
        pass
    return bool(server.started)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the app and open the browser.")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument(
        "--print-config", action="store_true", help="print the resolved defaults and exit"
    )
    parser.add_argument("--stop", action="store_true", help="stop the running instance")
    return parser.parse_args(argv)


def _already_running(record_path: Path, opener: Opener) -> int:
    deadline = time.monotonic() + RECORD_WAIT_S
    record = instance.read_record(record_path)
    while record is None and time.monotonic() < deadline:
        time.sleep(0.2)
        record = instance.read_record(record_path)
    if record is None or not isinstance(record.get("url"), str):
        _say("The app is already starting. Wait a moment and try again.")
        return 1
    _say("The app is already running. Opening it in the browser.")
    with contextlib.suppress(Exception):
        opener(record["url"])
    return 0


@dataclass(frozen=True)
class Parts:
    """What the entry script and the tests plug into the launcher."""

    load_settings: Callable[[int | None], LaunchSettings]
    build_app: AppFactory
    headers: Mapping[str, str]
    claude_minimum: tuple[int, int, int] | None = None
    opener: Opener = webbrowser.open
    notify: Callable[[str], None] = _say
    serve: Serve = _serve_uvicorn
    terminal: Callable[[str], bool] = show_on_terminal
    cli_check: Callable[[tuple[int, int, int]], CliStatus] = check_claude_cli


def stop_running(data_dir: Path) -> int:
    """Ask the running instance to stop. The process id is trusted only while its lock is held."""
    record_path = data_dir / instance.RECORD_NAME
    with instance.InstanceLock(data_dir / instance.LOCK_NAME) as lock:
        if lock.acquire():
            with contextlib.suppress(OSError):
                record_path.unlink()
            _say("The app is not running.")
            return 0
    record = instance.read_record(record_path)
    pid = None if record is None else record.get("pid")
    if not isinstance(pid, int):
        _say("The app is still starting. Try again in a moment.")
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        _say("The app could not be stopped.")
        return 1
    _say("Stopping the app.")
    return 0


def run(
    root: Path,
    parts: Parts,
    *,
    argv: Sequence[str] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> int:
    """Start the app of the distribution at `root` and return the process exit code."""
    args = parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        dist = read_distribution(root)
        apply_distribution(root, dist, env)
        base = parts.load_settings(None)
    except Exception as error:  # noqa: BLE001 - one plain message, no traceback for a user
        _say(f"The settings could not be read: {type(error).__name__}: {error}")
        return 1
    if args.print_config:
        # ASCII-only JSON: a pipe on Windows uses the locale code page, which cannot
        # encode a Korean folder name and would end the command before any output.
        print(
            json.dumps(
                {
                    "profile": base.profile,
                    "deployment": base.deployment,
                    "runtime_dir": str(base.runtime_dir),
                    "data_dir": str(base.data_dir),
                },
            )
        )
        return 0
    if args.stop:
        return stop_running(base.data_dir)
    record_path = base.data_dir / instance.RECORD_NAME
    with instance.InstanceLock(base.data_dir / instance.LOCK_NAME) as lock:
        if not lock.acquire():
            return _already_running(record_path, parts.opener)
        return _run_locked(root, base, dist, record_path, args, parts)


def _run_locked(
    root: Path,
    base: LaunchSettings,
    dist: Distribution | None,
    record_path: Path,
    args: argparse.Namespace,
    parts: Parts,
) -> int:
    handler = open_log(root, base)
    sock: socket.socket | None = None
    stop = threading.Event()
    try:
        sock = instance.bind_free_socket(base.bind_host, base.port)
        settings = parts.load_settings(int(sock.getsockname()[1]))
        cli: CliStatus | None = None
        # The API adapter uses the user's stored key, so the CLI probe has nothing to say.
        if (
            settings.profile == "dev"
            and settings.providers.adapters.get("llm") != "anthropic_api"
            and parts.claude_minimum is not None
        ):
            cli = parts.cli_check(parts.claude_minimum)
            log.info("claude cli: %s", cli.state)
            if cli.state != "ok":
                log.warning("%s", cli.message)
                parts.notify(cli.message)
        pairing: list[str] = []
        app = parts.build_app(settings, pairing.append)
        if dist is not None:
            app = StaticSite(
                app, root / dist.web_dir, hosts=_hosts(settings), headers=parts.headers
            )
        threading.Thread(
            target=_after_start,
            args=(settings, cli, pairing, record_path, args, parts, stop),
            daemon=True,
        ).start()
        log.info("starting profile=%s port=%s", settings.profile, settings.port)
        if parts.serve(app, sock, settings):
            return 0
        parts.notify(f"The app did not start. Details are in {LOG_NAME} under the data folder.")
        return 1
    except Exception as error:  # noqa: BLE001 - the user needs one plain message and a log
        log.exception("launcher failed: %s", type(error).__name__)
        parts.notify(f"The app could not start ({type(error).__name__}). See {LOG_NAME}.")
        return 1
    finally:
        stop.set()
        with contextlib.suppress(OSError):
            record_path.unlink()
        if sock is not None:
            sock.close()
        for name in ("launcher", "app", "uvicorn", "uvicorn.error"):
            logging.getLogger(name).removeHandler(handler)
        handler.close()


def _after_start(
    settings: LaunchSettings,
    cli: CliStatus | None,
    pairing: list[str],
    record_path: Path,
    args: argparse.Namespace,
    parts: Parts,
    stop: threading.Event,
) -> None:
    """Wait for the server, publish the status record, then show the pairing URL."""
    if not wait_health(settings.port, START_TIMEOUT_S, stop):
        return
    instance.write_record(record_path, _record(settings, cli))
    if not pairing:
        return
    display = pairing[0]
    opened = False
    if not args.no_browser:
        try:
            opened = bool(parts.opener(browser_url(display, settings.port)))
        except Exception:  # noqa: BLE001 - a missing browser is not a failure
            opened = False
    if settings.lan or (not opened and not args.no_browser):
        if not parts.terminal(display):
            log.warning("no browser or terminal could show the pairing URL")
