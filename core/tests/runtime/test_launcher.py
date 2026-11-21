"""Launcher: distribution defaults, one instance, free port, pairing, real start."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.runtime import instance
from app.runtime import launcher as launcher_module
from app.runtime.dev_cli import CliStatus
from app.runtime.launcher import (
    Parts,
    adapter_choices,
    apply_distribution,
    read_distribution,
    run,
)

CODE = "SYNTHETIC-CODE-0123456789ABCDEF"
REPO = Path(__file__).resolve().parents[3]


def write_dist(root: Path, profile: str = "release", web: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dist.json").write_text(
        json.dumps({
            "profile": profile, "deployment": "local", "web_dir": "web",
            "profile_adapters": {
                "dev": {"llm": "openai_compat"},
                "release": {"llm": "anthropic_api"},
                "fixture": {"llm": "fixture"},
            },
        }),
        encoding="utf-8",
    )
    if web:
        (root / "web" / "assets").mkdir(parents=True, exist_ok=True)
        (root / "web" / "index.html").write_text("<html>home</html>", encoding="utf-8")


def settings_loader(env: dict[str, str], data: Path, preferred: int = 0) -> Callable[..., Any]:
    def load(port: int | None) -> Any:
        return SimpleNamespace(
            profile=env.get("APP_PROFILE", "fixture"),
            deployment=env.get("APP_DEPLOYMENT", "local"),
            port=port or preferred,
            lan=False,
            bind_host="127.0.0.1",
            data_dir=data,
            runtime_dir=Path(env["APP_RUNTIME_DIR"]),
            log_level="info",
        )

    return load


class Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        status = 200 if self.path == "/api/v1/health" else 404
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args: object) -> None:
        pass


def health_server(stop: threading.Event) -> Callable[..., bool]:
    def serve(_app: Any, sock: socket.socket, _settings: Any) -> bool:
        server = ThreadingHTTPServer(sock.getsockname(), Health, bind_and_activate=False)
        server.socket.close()
        server.socket = sock
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stop.wait(30)
        server.shutdown()
        thread.join()
        return True

    return serve


class Harness:
    def __init__(self, tmp_path: Path, profile: str = "release") -> None:
        self.root = tmp_path / "설치 폴더"
        self.data = tmp_path / "데이터 폴더"
        write_dist(self.root, profile)
        self.env: dict[str, str] = {}
        self.stop = threading.Event()
        self.opened: list[str] = []
        self.terminal: list[str] = []
        self.apps: list[Any] = []
        self.exit_code: list[int] = []

    def parts(self, **overrides: Any) -> Parts:
        def build_app(settings: Any, display: Callable[[str], None]) -> Any:
            display(f"http://127.0.0.1:{settings.port}/#pair={CODE}")
            self.apps.append(settings)
            return object()

        values: dict[str, Any] = {
            "load_settings": settings_loader(self.env_with_runtime(), self.data),
            "build_app": build_app,
            "headers": {"X-Test": "1"},
            "opener": lambda url: self.opened.append(url) or True,
            "serve": health_server(self.stop),
            "terminal": lambda url: self.terminal.append(url) or True,
            "claude_minimum": (2, 0, 0),
        }
        values.update(overrides)
        return Parts(**values)

    def env_with_runtime(self) -> dict[str, str]:
        self.env.setdefault("APP_RUNTIME_DIR", str(self.root / "rt"))
        return self.env

    def start(self, parts: Parts | None = None, *args: str) -> threading.Thread:
        chosen = parts or self.parts()

        def target() -> None:
            self.exit_code.append(run(self.root, chosen, argv=list(args), environ=self.env))

        thread = threading.Thread(target=target)
        thread.start()
        return thread

    def wait_record(self) -> dict[str, Any]:
        path = self.data / instance.RECORD_NAME
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            record = instance.read_record(path)
            if record is not None:
                return record
            time.sleep(0.05)
        raise AssertionError("the launcher never published its record")

    def finish(self, thread: threading.Thread) -> None:
        self.stop.set()
        thread.join(20)
        assert not thread.is_alive()


def test_launcher_reads_the_profile_defaults_from_the_distribution_file(tmp_path: Path) -> None:
    for profile in ("release", "dev"):
        root = tmp_path / profile
        write_dist(root, profile, web=False)
        env: dict[str, str] = {}
        apply_distribution(root, read_distribution(root), env)
        assert env["APP_PROFILE"] == profile
        assert env["APP_DEPLOYMENT"] == "local"
        assert env["APP_RUNTIME_DIR"] == str(root / "rt")


def test_launcher_keeps_a_profile_the_user_already_set(tmp_path: Path) -> None:
    write_dist(tmp_path, "release", web=False)
    env = {"APP_PROFILE": "fixture", "APP_RUNTIME_DIR": "/elsewhere"}
    apply_distribution(tmp_path, read_distribution(tmp_path), env)
    assert env["APP_PROFILE"] == "fixture"
    assert env["APP_RUNTIME_DIR"] == "/elsewhere"


def test_launcher_rejects_a_distribution_file_with_an_unknown_profile(tmp_path: Path) -> None:
    (tmp_path / "dist.json").write_text('{"profile": "fixture"}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_distribution(tmp_path)


def test_launcher_prints_the_resolved_defaults_without_starting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness(tmp_path, "dev")
    code = run(
        harness.root, harness.parts(), argv=["--print-config"], environ=harness.env
    )
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["profile"] == "dev"
    assert not harness.apps


def test_launcher_serves_on_the_preferred_port_and_publishes_its_record(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    parts = harness.parts(load_settings=settings_loader(harness.env_with_runtime(),
                                                        harness.data, preferred=port))
    thread = harness.start(parts)
    record = harness.wait_record()
    assert record["port"] == port
    assert record["python"] == sys.executable
    assert record["profile"] == "release"
    assert "pair" not in json.dumps(record)
    harness.finish(thread)
    assert harness.exit_code == [0]
    assert not (harness.data / instance.RECORD_NAME).exists()


def test_launcher_uses_another_port_when_the_preferred_one_is_taken(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        taken = busy.getsockname()[1]
        parts = harness.parts(load_settings=settings_loader(
            harness.env_with_runtime(), harness.data, preferred=taken))
        thread = harness.start(parts)
        record = harness.wait_record()
        assert record["port"] != taken
        harness.finish(thread)


def test_launcher_opens_the_browser_with_the_pairing_fragment_and_never_logs_it(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    thread = harness.start()
    record = harness.wait_record()
    deadline = time.monotonic() + 10
    while not harness.opened and time.monotonic() < deadline:
        time.sleep(0.05)
    assert harness.opened == [f"http://127.0.0.1:{record['port']}/#pair={CODE}"]
    assert harness.terminal == []
    harness.finish(thread)
    log_text = (harness.data / "log" / "launcher.log").read_text(encoding="utf-8")
    assert "starting profile=release" in log_text
    assert CODE not in log_text
    assert str(tmp_path) not in log_text


def test_launcher_shows_the_pairing_url_on_the_terminal_when_no_browser_opens(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    thread = harness.start(harness.parts(opener=lambda _url: False))
    harness.wait_record()
    deadline = time.monotonic() + 10
    while not harness.terminal and time.monotonic() < deadline:
        time.sleep(0.05)
    assert harness.terminal and harness.terminal[0].endswith(f"#pair={CODE}")
    harness.finish(thread)


def test_launcher_no_browser_flag_never_calls_the_opener(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    thread = harness.start(None, "--no-browser")
    harness.wait_record()
    harness.finish(thread)
    assert harness.opened == [] and harness.terminal == []


def test_launcher_second_start_opens_the_running_instance_instead(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    holder = instance.InstanceLock(harness.data / instance.LOCK_NAME)
    assert holder.acquire()
    instance.write_record(
        harness.data / instance.RECORD_NAME, {"url": "http://127.0.0.1:9/", "port": 9}
    )
    try:
        code = run(
            harness.root, harness.parts(), argv=[], environ=harness.env_with_runtime()
        )
    finally:
        holder.release()
    assert code == 0
    assert harness.opened == ["http://127.0.0.1:9/"]
    assert harness.apps == []


def test_launcher_stop_flag_ends_the_running_instance_and_reports_when_none_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness(tmp_path)
    parts = harness.parts()
    assert run(harness.root, parts, argv=["--stop"], environ=harness.env_with_runtime()) == 0
    assert "not running" in capsys.readouterr().err

    holder = instance.InstanceLock(harness.data / instance.LOCK_NAME)
    assert holder.acquire()
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        instance.write_record(harness.data / instance.RECORD_NAME, {"pid": sleeper.pid})
        code = run(harness.root, parts, argv=["--stop"], environ=harness.env_with_runtime())
        assert code == 0
        assert sleeper.wait(20) != 0
    finally:
        sleeper.kill()
        sleeper.wait()
        holder.release()


def test_launcher_stop_flag_never_signals_a_process_when_no_instance_holds_the_lock(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        instance.write_record(harness.data / instance.RECORD_NAME, {"pid": sleeper.pid})
        code = run(
            harness.root, harness.parts(), argv=["--stop"], environ=harness.env_with_runtime()
        )
        assert code == 0 and sleeper.poll() is None
        assert not (harness.data / instance.RECORD_NAME).exists()
    finally:
        sleeper.kill()
        sleeper.wait()


def test_launcher_instance_lock_is_released_when_the_launcher_exits(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    thread = harness.start()
    harness.wait_record()
    harness.finish(thread)
    lock = instance.InstanceLock(harness.data / instance.LOCK_NAME)
    assert lock.acquire()
    lock.release()


def test_launcher_reports_a_server_that_did_not_start(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness(tmp_path)
    code = run(
        harness.root,
        harness.parts(serve=lambda _app, _sock, _settings: False),
        argv=[],
        environ=harness.env_with_runtime(),
    )
    assert code == 1
    assert "did not start" in capsys.readouterr().err


def test_launcher_reports_an_app_whose_startup_fails_instead_of_exiting_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async def failing_app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await receive()
            raise RuntimeError("startup refused")

    harness = Harness(tmp_path)
    parts = harness.parts(
        build_app=lambda _settings, _display: failing_app,
        serve=launcher_module._serve_uvicorn,
    )
    code = run(harness.root, parts, argv=[], environ=harness.env_with_runtime())
    assert code == 1
    assert "did not start" in capsys.readouterr().err
    assert "startup refused" in (harness.data / "log" / "launcher.log").read_text("utf-8")


def test_launcher_checks_the_official_cli_only_in_the_dev_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[int, int, int]] = []

    def check(minimum: tuple[int, int, int]) -> CliStatus:
        calls.append(minimum)
        return CliStatus("missing", None, "install the official CLI from the guide")

    release = Harness(tmp_path / "r", "release")
    thread = release.start(release.parts(cli_check=check))
    assert "claude_cli" not in release.wait_record()
    release.finish(thread)
    assert calls == []

    dev = Harness(tmp_path / "d", "dev")
    thread = dev.start(dev.parts(cli_check=check))
    record = dev.wait_record()
    dev.finish(thread)
    assert calls == [(2, 0, 0)]
    assert record["claude_cli"] == {
        "state": "missing",
        "version": None,
        "message": "install the official CLI from the guide",
    }
    assert "official CLI" in capsys.readouterr().err


def test_launcher_cli_guidance_reaches_the_log_and_the_notice_hook_without_a_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guide = "https://example.invalid/cli-guide"
    shown: list[str] = []
    monkeypatch.setattr(launcher_module.sys, "stderr", None)
    harness = Harness(tmp_path, "dev")
    parts = harness.parts(
        cli_check=lambda _minimum: CliStatus("missing", None, f"install it from {guide}"),
        notify=shown.append,
    )
    thread = harness.start(parts)
    record = harness.wait_record()
    harness.finish(thread)
    assert shown == [f"install it from {guide}"]
    assert guide in (harness.data / "log" / "launcher.log").read_text(encoding="utf-8")
    assert guide in record["claude_cli"]["message"]


def test_launcher_without_a_console_shows_a_message_box_on_windows_and_never_fails_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boxes: list[str] = []
    monkeypatch.setattr(launcher_module.sys, "stderr", None)
    monkeypatch.setattr(launcher_module, "_message_box", boxes.append)
    monkeypatch.setattr(launcher_module.sys, "platform", "linux")
    launcher_module._say("quiet")
    assert boxes == []
    monkeypatch.setattr(launcher_module.sys, "platform", "win32")
    launcher_module._say("visible")
    deadline = time.monotonic() + 5
    while not boxes and time.monotonic() < deadline:
        time.sleep(0.02)
    assert boxes == ["visible"]


def test_launcher_distribution_selects_the_effective_profile_providers(tmp_path: Path) -> None:
    (tmp_path / "dist.json").write_text(
        json.dumps({
            "profile": "release",
            "profile_adapters": {
                "dev": {"llm": "openai_compat"},
                "release": {"llm": "anthropic_api"},
                "fixture": {"llm": "fixture"},
            },
        }), encoding="utf-8"
    )
    dist = read_distribution(tmp_path)
    assert adapter_choices(dist, "dev", {}) == {"llm": "openai_compat"}
    assert adapter_choices(dist, "dev", {"APP_LLM_ADAPTER": "claude_cli"}) == {"llm": "claude_cli"}
    assert adapter_choices(dist, "release", {"APP_LLM_ADAPTER": "claude_cli"}) == {
        "llm": "anthropic_api"
    }
    assert adapter_choices(dist, "fixture", {}) == {"llm": "fixture"}
    assert adapter_choices(None, "dev", {}) == {}


def test_launcher_rejects_a_distribution_file_with_a_malformed_adapter_table(
    tmp_path: Path,
) -> None:
    (tmp_path / "dist.json").write_text(
        json.dumps({"profile": "dev", "profile_adapters": {"dev": {"llm": 3}}}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        read_distribution(tmp_path)


def write_aligner_dist(root: Path, **fields: object) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dist.json").write_text(
        json.dumps({"profile": "release"} | fields), encoding="utf-8"
    )


def test_21_a_distribution_names_the_packages_its_workers_load(tmp_path: Path) -> None:
    write_aligner_dist(
        tmp_path, align_python="align-python/bin/python", align_site="align-site"
    )
    env: dict[str, str] = {}
    apply_distribution(tmp_path, read_distribution(tmp_path), env)
    assert env["APP_MAIN_SITE"] == str(tmp_path / "site-packages")
    assert env["APP_ALIGN_PYTHON"] == str(tmp_path / "align-python/bin/python")
    assert env["APP_ALIGN_SITE"] == str(tmp_path / "align-site")

    kept = {"APP_ALIGN_SITE": "/elsewhere", "APP_MAIN_SITE": "/main"}
    apply_distribution(tmp_path, read_distribution(tmp_path), kept)
    assert kept["APP_ALIGN_SITE"] == "/elsewhere" and kept["APP_MAIN_SITE"] == "/main"


def test_21_a_distribution_without_an_aligner_sets_no_aligner_variables(tmp_path: Path) -> None:
    write_aligner_dist(tmp_path)
    env: dict[str, str] = {}
    apply_distribution(tmp_path, read_distribution(tmp_path), env)
    assert "APP_MAIN_SITE" in env
    assert not [key for key in env if key.startswith("APP_ALIGN")]


@pytest.mark.parametrize(
    "fields",
    [
        {"align_python": "align-python/bin/python"},
        {"align_site": "align-site"},
        {"align_python": "../out/python", "align_site": "align-site"},
        {"align_python": "/abs/python", "align_site": "align-site"},
        {"align_python": "C:\\python.exe", "align_site": "align-site"},
        {"align_python": "align-python/bin/python", "align_site": ""},
        {"align_python": 3, "align_site": "align-site"},
    ],
    ids=["python-only", "site-only", "parent", "absolute", "windows", "empty", "not-text"],
)
def test_21_a_distribution_with_a_half_or_escaping_aligner_is_refused(
    tmp_path: Path, fields: dict[str, object]
) -> None:
    write_aligner_dist(tmp_path, **fields)
    with pytest.raises(ValueError):
        read_distribution(tmp_path)


def wait_for(path: Path, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = instance.read_record(path)
        if record is not None:
            return record
        time.sleep(0.1)
    raise AssertionError(f"{path.name} did not appear")


def lowered(headers: Any) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def get(url: str) -> tuple[int, dict[str, str], bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=10) as response:
            return response.status, lowered(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, lowered(error.headers), error.read()


def test_launcher_runs_the_real_app_with_the_built_web_files(tmp_path: Path) -> None:
    root = tmp_path / "설치 폴더 한글"
    write_dist(root, "release")
    (root / "web" / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    shutil.copy2(REPO / "packaging" / "launch.py", root / "launch.py")
    data = tmp_path / "데이터 폴더"
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "core"),
        "APP_PROFILE": "fixture",
        "APP_DATA_DIR": str(data),
        "APP_CACHE_DIR": str(tmp_path / "cache"),
        "APP_MODEL_DIR": str(tmp_path / "models"),
    }
    env.pop("APP_PORT", None)
    env.pop("APP_RUNTIME_DIR", None)
    output = (tmp_path / "launcher.out").open("w+b")
    process = subprocess.Popen(
        [sys.executable, str(root / "launch.py"), "--no-browser"],
        env=env,
        stdout=output,
        stderr=subprocess.STDOUT,
        cwd=tmp_path,
    )
    try:
        record = wait_for(data / instance.RECORD_NAME)
        base = f"http://127.0.0.1:{record['port']}"
        status, _headers, body = get(base + "/api/v1/health")
        assert status == 200
        assert json.loads(body)["profile"] == "fixture"
        status, headers, body = get(base + "/")
        assert status == 200 and body == b"<html>home</html>"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert get(base + "/projects/one")[2] == b"<html>home</html>"
        assert get(base + "/assets/app.js")[0] == 200
        assert get(base + "/assets/missing.js")[0] == 404
        assert get(base + "/api/v1/runtime")[0] == 401
        assert Path(record["python"]) == Path(sys.executable)
    finally:
        process.terminate()
        try:
            process.wait(20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        output.seek(0)
        text = output.read().decode("utf-8", "replace")
        output.close()
    assert "#pair=" not in text
    if sys.platform != "win32":
        assert process.returncode == 0
        assert not (data / instance.RECORD_NAME).exists()
