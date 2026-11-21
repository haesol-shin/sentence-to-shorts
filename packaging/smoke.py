#!/usr/bin/env python3
"""Install a built distribution for a new user and start it without any system Python.

    python packaging/smoke.py --artifact dist/<tarball or setup exe> --os linux \\
        --profile release --output smoke-result.json

The user is synthetic: the home and install folders have Korean letters and spaces, and
PATH holds one empty folder, so a Python or ffmpeg on the machine cannot be used by
accident. The checks that gate the exit code are the install, the profile default of
the distribution, the prepared runtime items with a bundled ffmpeg that runs, and the
distribution started exactly as shipped: `/api/v1/health` 200, the built page, the bundled
interpreter and a clean stop. A fixture-profile start of the same files is run afterwards
as a diagnostic only. Those starts run with a closed loopback port as proxy, so the
background model download the app queues on its own stays cheap and deterministic.

With `--voice` (the release candidate legs) a second phase proves that a team member who
has only the installer can make a video with voice: the app starts in an empty data folder
and serves its page while the models download, a generate pressed meanwhile waits and then
succeeds with word timing, a second start without network downloads nothing, and the
installed TTS and aligner run from the installed files (`voice_probe.py`, with
`pythonw.exe` on Windows) in two environments that hold different torch.

The voice phase picks the loopback stub `smoke_llm.py` as the LLM. The release bundle
carries the adapter table of every profile, so `APP_PROFILE=dev` is legal and the only
profile where `APP_LLM_BASE_URL` selects the OpenAI-compatible adapter. That adapter needs
a model id per alias and the app has no environment override for it, so the phase writes
one into the installed copy of `core/config/models.yaml` (the throwaway install of this
run, not the build). The pairing URL is shown only to a local browser or terminal, so the
launcher is started without `--no-browser` and with `BROWSER` naming a small script that
stores the URL it is given; no browser is ever opened. Sizes and timings go to the result
under `sizes` and `seconds`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HOME_NAME = "사용자 홈 테스트"
INSTALL_NAME = "설치 폴더 테스트"
START_TIMEOUT_S = 120.0
GENERATE_TIMEOUT_S = 45 * 60.0
"""How long a generate pressed during preparation may take: the download, then the render."""
JOB_TIMEOUT_S = 600.0
"""Drafting and previews use no model; they end within this or the run is stuck."""
PROBE_TIMEOUT_S = 30 * 60.0
PAIRING_WAIT_S = 30.0
POLL_S = 2.0
GROUP_FAILED_GRACE_S = 60.0
"""After a group reports `failed` the waiting job must fail within this."""
PROXY_NAMES = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy")
VOICE_GROUP = "voice"
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
PAIR_MARK = "#pair="

CHECK_COLD = "cold start serves the page before preparation ends"
CHECK_GENERATE = "generate pressed during preparation waits and then succeeds"
CHECK_OFFLINE = "second start downloads nothing without network"
CHECK_TTS = "TTS makes a wav from the installed files"
CHECK_ALIGN = "the installed aligner times the words of that wav"
CHECK_TORCH = "the main and the aligner environments hold different torch"
VOICE_CHECKS = (CHECK_COLD, CHECK_GENERATE, CHECK_OFFLINE, CHECK_TTS, CHECK_ALIGN, CHECK_TORCH)


class SmokeError(RuntimeError):
    """A step of the voice phase failed; the message is the check detail."""


PROBLEMS = (SmokeError, KeyError, ValueError, TypeError)
"""What a step of the voice phase raises for a failed call or an unexpected answer."""


class Result:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.sizes: dict[str, int] = {}
        self.seconds: dict[str, float] = {}

    def check(self, name: str, ok: bool, detail: str = "", *, gating: bool = True) -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail, "gating": gating})
        mark = "ok  " if ok else ("FAIL" if gating else "note")
        print(f"{mark} {name}{' ' + detail if detail else ''}", flush=True)
        return bool(ok)

    @property
    def failed(self) -> bool:
        return any(not c["ok"] and c["gating"] for c in self.checks)

    def document(self) -> dict[str, Any]:
        return {"checks": self.checks, "sizes": self.sizes, "seconds": self.seconds}


def closed_port() -> int:
    """A loopback port nothing listens on, for a proxy that refuses every connection."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def blocked_network(env: Mapping[str, str]) -> dict[str, str]:
    """`env` with every proxy variable pointing at a closed port: downloads cannot connect.

    The app's own loopback calls bypass proxies, so only downloads are blocked.
    """
    proxy = f"http://127.0.0.1:{closed_port()}"
    blocked = {key: value for key, value in env.items() if key.upper() != "NO_PROXY"}
    blocked.update(dict.fromkeys(PROXY_NAMES, proxy))
    return blocked


def tree_bytes(folder: Path) -> int:
    """Sum of file sizes below `folder`; 0 when it does not exist."""
    total = 0
    for base, _dirs, names in os.walk(folder):
        for name in names:
            path = Path(base, name)
            if not path.is_symlink():
                total += path.stat().st_size
    return total


def snapshot_tree(folder: Path) -> dict[str, tuple[int, int]]:
    """Relative path -> (size, mtime in ns) of every file below `folder`."""
    found: dict[str, tuple[int, int]] = {}
    for base, _dirs, names in os.walk(folder):
        for name in names:
            path = Path(base, name)
            info = path.stat()
            found[path.relative_to(folder).as_posix()] = (info.st_size, info.st_mtime_ns)
    return found


def changed_files(
    before: Mapping[str, tuple[int, int]], after: Mapping[str, tuple[int, int]]
) -> list[str]:
    """Files added, removed or changed in size or mtime between two snapshots."""
    return sorted(
        name for name in before.keys() | after.keys() if before.get(name) != after.get(name)
    )


def user_environment(work: Path, home: Path, bare_path: Path) -> dict[str, str]:
    local = home / "AppData" / "Local"
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(local),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "TEMP": str(work / "tmp"),
        "TMP": str(work / "tmp"),
        "PATH": str(bare_path),
    }
    if sys.platform == "win32":
        for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"):
            if name in os.environ:
                env[name] = os.environ[name]
    return env


def install(artifact: Path, os_name: str, parent: Path, work: Path) -> Path:
    parent.mkdir(parents=True)
    if os_name == "linux":
        subprocess.run(["tar", "-xzf", str(artifact), "-C", str(parent)], check=True)
        folders = [path for path in parent.iterdir() if path.is_dir()]
        if len(folders) != 1:
            raise RuntimeError("the tarball must hold one top folder")
        return folders[0]
    target = parent / "app"
    subprocess.run(
        [
            str(artifact), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
            f"/DIR={target}", f"/LOG={work / 'setup.log'}",
        ],
        check=True,
    )
    return target


def bundled_python(root: Path, os_name: str) -> Path:
    return root / ("python/python.exe" if os_name == "windows" else "python/bin/python3.11")


def launch_base(root: Path, os_name: str) -> list[str]:
    if os_name == "linux":
        return [str(root / "start.sh")]
    return [str(bundled_python(root, os_name)), str(root / "launch.py")]


def launch_command(root: Path, os_name: str, *, browser: bool = False) -> list[str]:
    """The start command. `browser` leaves the pairing URL to `webbrowser` (see `BROWSER`)."""
    return launch_base(root, os_name) + ([] if browser else ["--no-browser"])


def get(url: str) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def wait_record(path: Path, process: subprocess.Popen[bytes], timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        time.sleep(0.2)
    return None


def wait_exit(process: subprocess.Popen[bytes], timeout: float) -> int | None:
    try:
        return process.wait(timeout)
    except subprocess.TimeoutExpired:
        return None


def stop(process: subprocess.Popen[bytes]) -> int | None:
    if process.poll() is None:
        process.terminate()
    try:
        return process.wait(30)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()


def run_launcher(
    root: Path, os_name: str, env: dict[str, str], data_dir: Path, log: Path,
    *, browser: bool = False,
) -> tuple[dict | None, subprocess.Popen[bytes], Any]:
    output = log.open("wb")
    process = subprocess.Popen(
        launch_command(root, os_name, browser=browser), env=env, stdout=output,
        stderr=subprocess.STDOUT, cwd=root.parent,
    )
    return wait_record(data_dir / "launcher.json", process, START_TIMEOUT_S), process, output


def stop_launcher(
    root: Path, os_name: str, env: dict[str, str], process: subprocess.Popen[bytes], output: Any
) -> tuple[int, int | None]:
    """`--stop` the running launcher: the stop command's exit code and the launcher's."""
    stopper = subprocess.run(
        launch_base(root, os_name) + ["--stop"], env=env, capture_output=True, check=False,
    )
    code = wait_exit(process, 30)
    if code is None:
        code = stop(process)
    output.close()
    return stopper.returncode, code


def runtime_verdict(states: Mapping[str, str]) -> tuple[bool, str]:
    """The installer holds every item but the models: those download after the start.

    Everything that is not a `model-` item must be ready (the Qwen package is ready through
    its bundle record), and every model must still be missing.
    """
    models = {name: state for name, state in states.items() if name.startswith("model-")}
    others = {name: state for name, state in states.items() if name not in models}
    stale = sorted(name for name, state in others.items() if state != "ready")
    present = sorted(name for name, state in models.items() if state != "missing")
    ok = bool(models) and "ffmpeg" in others and not stale and not present
    detail = (
        f"ready: {sorted(others)}; models missing: {sorted(models)}"
        + (f"; NOT ready: {stale}" if stale else "")
        + (f"; models already present: {present}" if present else "")
        + ("" if models else "; the lock lists no model")
    )
    return ok, detail


def check_runtime_ready(result: Result, python: Path, root: Path, env: dict[str, str]) -> None:
    code = (
        "import json, sys; sys.path[:0] = [sys.argv[1] + '/core', sys.argv[1] + '/site-packages'];"
        "from app.runtime import status; from app.settings import Settings;"
        "from app.tools.media.adapter import runtime_executable;"
        "s = Settings(); exe = runtime_executable(s);"
        "print(json.dumps({'states': {i.id: i.state.value for i in status(s)},"
        " 'ffmpeg': str(exe) if exe else None}))"
    )
    done = subprocess.run(
        [str(python), "-c", code, str(root)], env={**env, "APP_RUNTIME_DIR": str(root / "rt")},
        capture_output=True, text=True, check=False,
    )
    report = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip() else {}
    states = report.get("states", {})
    ready, detail = runtime_verdict(states) if states else (False, "")
    result.check(
        "the installer's runtime items are ready and the models are still to download",
        ready,
        detail if states else done.stderr.strip()[-300:],
    )
    exe = report.get("ffmpeg")
    version = ""
    if exe and Path(exe).is_file() and Path(exe).resolve().is_relative_to(root.resolve()):
        probe = subprocess.run(
            [exe, "-version"], env=env, capture_output=True, text=True, check=False, timeout=60
        )
        version = probe.stdout.splitlines()[0] if probe.returncode == 0 and probe.stdout else ""
    result.check(
        "the media adapter resolves the bundled ffmpeg, which runs without PATH",
        bool(version),
        version[:60],
    )
    result.check(
        "the GPL text and the FFmpeg notice ship with the distribution",
        (root / "licenses" / "FFmpeg-GPL-3.0.txt").is_file()
        and "FFmpeg" in (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"),
    )


def exercise(
    result: Result, label: str, root: Path, args: argparse.Namespace, env: dict[str, str],
    data_dir: Path, work: Path, *, gating: bool,
) -> None:
    """Start the launcher with `env`, check health and the page, stop it with --stop."""
    record, process, output = run_launcher(root, args.os, env, data_dir, work / f"{label}.log")
    try:
        result.check(f"[{label}] the launcher published its record", record is not None,
                     gating=gating)
        if record is not None:
            port = record["port"]
            status, _body = get(f"http://127.0.0.1:{port}/api/v1/health")
            result.check(f"[{label}] GET /api/v1/health answers 200", status == 200, str(status),
                         gating=gating)
            status, body = get(f"http://127.0.0.1:{port}/")
            result.check(f"[{label}] the built web page is served", status == 200 and b"<" in body,
                         gating=gating)
            bundled = Path(record["python"]).resolve().is_relative_to(root.resolve())
            result.check(f"[{label}] the server runs the bundled interpreter", bundled,
                         record["python"][-40:], gating=gating)
    finally:
        stopper_code, code = stop_launcher(root, args.os, env, process, output)
    result.check(f"[{label}] the stop command reaches the running launcher",
                 stopper_code == 0 or record is None, gating=gating)
    if args.os == "linux" and record is not None:
        result.check(f"[{label}] the launcher exits cleanly when stopped", code == 0, str(code),
                     gating=gating)
    if record is None:
        tail = (work / f"{label}.log").read_bytes()[-400:].decode("utf-8", "replace")
        result.check(f"[{label}] why it did not start", False, tail.strip()[-300:], gating=False)


# --- the voice phase ---------------------------------------------------------------------

DRAFT_MESSAGE = "커피 고르는 법"
DRAFT_CARD = "just_three"
"""The request the recorded LLM answers cover (see `fixtures/llm/draft`)."""
PROBE_SCRIPT = Path(__file__).with_name("voice_probe.py")


class Api:
    """The paired browser over plain HTTP: session cookie, CSRF token, one key per POST."""

    def __init__(self, port: int) -> None:
        self.origin = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.headers = {"Origin": self.origin}

    def _send(
        self, method: str, path: str, body: Any = None, params: Mapping[str, Any] | None = None,
        *, key: bool = True,
    ) -> tuple[int, bytes, Any]:
        url = f"{self.origin}/api/v1{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = dict(self.headers)
        data = None
        if method == "POST":
            data = b"" if body is None else json.dumps(body).encode("utf-8")
            if body is not None:
                headers["Content-Type"] = "application/json"
            if key:
                headers["Idempotency-Key"] = uuid.uuid4().hex
        request = urllib.request.Request(url, data, headers, method=method)
        try:
            with self.opener.open(request, timeout=120) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers
        except (urllib.error.URLError, OSError) as error:
            raise SmokeError(f"{method} {path}: {error}") from None

    def pair(self, code: str) -> None:
        status, raw, headers = self._send("POST", "/session/pair", {"code": code}, key=False)
        if status != 200:
            raise SmokeError(f"pairing answered {status}")
        cookies = [value.split(";", 1)[0] for value in headers.get_all("Set-Cookie") or []]
        self.headers["Cookie"] = "; ".join(cookies)
        self.headers["X-CSRF-Token"] = json.loads(raw)["csrf_token"]

    def request(
        self, method: str, path: str, body: Any = None, *, expect: int = 200,
        params: Mapping[str, Any] | None = None,
    ) -> bytes:
        status, raw, _headers = self._send(method, path, body, params)
        if status != expect:
            raise SmokeError(f"{method} {path}: {status} {raw[:200].decode('utf-8', 'replace')}")
        return raw

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return json.loads(self.request("GET", path, params=params))

    def post(self, path: str, body: Any = None, *, expect: int = 200) -> Any:
        raw = self.request("POST", path, body, expect=expect)
        return json.loads(raw) if raw else None

    def download(self, path: str) -> bytes:
        return self.request("GET", path)


@dataclass
class Running:
    """One started app: what the cold-start check needs and what stopping needs."""

    started: float
    api: Api | None = None
    first_page_s: float | None = None
    health: int = 0
    page: int = 0
    problem: str | None = None
    process: Any = None
    output: Any = None
    env: dict[str, str] | None = None


@dataclass
class VoicePlan:
    """The moving parts of the voice phase, so a test can replace the processes."""

    start: Callable[[bool], Running]
    """Start the app; True blocks the network (the second start)."""
    stop: Callable[[Running], None]
    probe: Callable[[], dict[str, Any]]
    model_dir: Path
    llm: Any
    """The LLM stub: `unmatched` and `served` lists."""
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    generate_timeout_s: float = GENERATE_TIMEOUT_S
    poll_s: float = POLL_S
    settle_s: float = 2.0
    timings: dict[str, float] = field(default_factory=dict)


def write_pairing_hook(work: Path, os_name: str) -> tuple[Path, Path]:
    """A `BROWSER` target that stores the URL it is given: (script, file the URL lands in)."""
    url_file = work / "pairing-url.txt"
    if os_name == "windows":
        script = work / "pairing-hook.bat"
        # `%*` keeps the URL whole: cmd splits `%1` at the `=` of `#pair=<code>`.
        script.write_text(f'@echo off\r\n> "{url_file}" echo %*\r\n', encoding="utf-8")
    else:
        script = work / "pairing-hook.sh"
        script.write_text(f"#!/bin/sh\nprintf '%s' \"$1\" > '{url_file}'\n", encoding="utf-8")
        script.chmod(0o755)
    return script, url_file


def read_pairing_code(
    url_file: Path, timeout: float, *, clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    deadline = clock() + timeout
    while True:
        if url_file.is_file():
            text = url_file.read_text(encoding="utf-8").strip()
            if PAIR_MARK in text:
                return text.split(PAIR_MARK, 1)[1].strip()
        if clock() >= deadline:
            raise SmokeError("the launcher never handed the pairing URL to the browser hook")
        sleep(0.2)


def give_endpoint_models(root: Path) -> None:
    """Name a model for the OpenAI-compatible route in the installed copy of the config."""
    path = root / "core" / "config" / "models.yaml"
    text, count = re.subn(r'(openai_compat:\s*)""', r'\1"recorded"', path.read_text("utf-8"))
    if not count:
        raise SmokeError("core/config/models.yaml has no empty openai_compat model id to fill")
    path.write_text(text, encoding="utf-8")


def start_app(
    root: Path, os_name: str, env: dict[str, str], data_dir: Path, log: Path, url_file: Path,
) -> Running:
    """Start the launcher, read the first page and pair with the URL it hands out."""
    url_file.unlink(missing_ok=True)
    started = time.monotonic()
    record, process, output = run_launcher(root, os_name, env, data_dir, log, browser=True)
    running = Running(started, process=process, output=output)
    if record is None:
        tail = log.read_bytes()[-300:].decode("utf-8", "replace").strip()
        running.problem = f"the launcher published no record: {tail}"
        return running
    base = f"http://127.0.0.1:{record['port']}"
    running.health = get(f"{base}/api/v1/health")[0]
    status, body = get(f"{base}/")
    running.page = status if b"<" in body else 0
    running.first_page_s = time.monotonic() - started
    try:
        api = Api(int(record["port"]))
        api.pair(read_pairing_code(url_file, PAIRING_WAIT_S))
        running.api = api
    except (SmokeError, KeyError, ValueError) as error:
        running.problem = f"could not pair: {error}"
    return running


def group_of(runtime: Mapping[str, Any], group_id: str) -> dict[str, Any]:
    groups = (runtime.get("prepare") or {}).get("groups") or []
    for group in groups:
        if group.get("id") == group_id:
            return dict(group)
    raise SmokeError(f"GET /runtime lists no {group_id} group: {[g.get('id') for g in groups]}")


def group_text(group: Mapping[str, Any]) -> str:
    code = f" {group['error_code']}" if group.get("error_code") else ""
    return f"{group['id']} {group['state']}{code} {group['done']}/{group['total']} bytes"


def wait_job(
    api: Api, job: Mapping[str, Any], *, timeout: float = JOB_TIMEOUT_S,
    clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    deadline = clock() + timeout
    current = dict(job)
    while current["state"] not in TERMINAL:
        if clock() > deadline:
            raise SmokeError(f"job {job['id']} did not end in {timeout:.0f}s: {current['state']}")
        sleep(0.5)
        current = api.get(f"/jobs/{job['id']}")
    if current["state"] != "succeeded":
        raise SmokeError(f"job {job['id']} {current['state']}: {current.get('error')}")
    return current


def drive_to_scenes(api: Api) -> dict[str, Any]:
    """The user's path up to the confirmed scenes: no step here needs a model."""
    project = api.post("/projects", {"title": "smoke", "language": "ko"}, expect=201)
    video = api.post(
        f"/projects/{project['id']}/videos", {"from_video_id": None, "preset_id": None},
        expect=201,
    )

    def head() -> dict[str, Any]:
        return api.get(f"/videos/{video['id']}")["video"]

    job = api.post(
        f"/videos/{video['id']}/draft",
        {"base_revision": video["revision"], "message": DRAFT_MESSAGE, "card_id": DRAFT_CARD},
        expect=202,
    )
    wait_job(api, job)
    current = head()
    for step in ("concept/confirm", "script/confirm"):
        current = api.post(f"/videos/{video['id']}/{step}", {"base_revision": current["revision"]})
    job = api.post(
        f"/videos/{video['id']}/previews", {"base_revision": current["revision"]}, expect=202
    )
    wait_job(api, job)
    current = head()
    return api.post(f"/videos/{video['id']}/scenes/confirm", {"base_revision": current["revision"]})


def word_timing(api: Api, job: Mapping[str, Any]) -> str:
    """Prove every spoken line has word-level phrases, not the sentence-caption fallback."""
    ids = ((job.get("result") or {}).get("artifacts") or {}).get("timing") or {}
    if not ids:
        raise SmokeError("the job result names no timing artifact")
    lines = phrases = 0
    for scene_id, artifact_id in ids.items():
        timing = json.loads(api.download(f"/artifacts/{artifact_id}"))
        for line in timing["lines"]:
            caption = line["caption"]
            if (caption["mode_used"] != "phrase" or caption["fallback_reason"]
                    or not caption["phrases"]):
                raise SmokeError(
                    f"scene {scene_id} line {line['line_id']} has {caption['mode_used']} "
                    f"captions, fallback {caption['fallback_reason']}"
                )
            lines += 1
            phrases += len(caption["phrases"])
    return f"{lines} lines, {phrases} timed phrases"


def generate_during_preparation(
    plan: VoicePlan, run: Running, timings: dict[str, float]
) -> str:
    """Press generate while the voice group downloads; return the check detail or raise."""
    api = run.api
    assert api is not None
    video = drive_to_scenes(api)
    group = group_of(api.get("/runtime"), VOICE_GROUP)
    if group["state"] == "ready":
        raise SmokeError("the voice group was ready before generate was pressed: nothing waited")
    job = api.post(
        f"/videos/{video['id']}/generate", {"base_revision": video["revision"]}, expect=202
    )
    pressed = plan.clock()
    problems: list[str] = []
    if job["state"] != "queued" or job["progress"]["waiting_on"] != "queue":
        problems.append(
            f"right after submit the job is {job['state']}/{job['progress']['waiting_on']}"
        )
    seen = [json.dumps(job)]
    failed_at: float | None = None
    last = group
    while job["state"] not in TERMINAL:
        now = plan.clock()
        if now - pressed > plan.generate_timeout_s:
            raise SmokeError(
                f"the job was still {job['state']} after {plan.generate_timeout_s:.0f}s; "
                f"{group_text(last)}"
            )
        plan.sleep(plan.poll_s)
        before = group_of(api.get("/runtime"), VOICE_GROUP)
        job = api.get(f"/jobs/{job['id']}")
        after = group_of(api.get("/runtime"), VOICE_GROUP)
        last = after
        seen.append(json.dumps(job))
        if after["state"] == "ready" and "voice_ready" not in timings:
            timings["voice_ready"] = round(plan.clock() - run.started, 1)
        if job["state"] == "queued":
            if after["state"] != "ready" and job["progress"]["waiting_on"] != "queue":
                problems.append(f"queued job is not waiting_on queue while {group_text(after)}")
        elif "generate_wait" not in timings:
            timings["generate_wait"] = round(plan.clock() - pressed, 1)
            if before["state"] != "ready" and after["state"] != "ready":
                problems.append(f"the job left the queue while {group_text(after)}")
        if after["state"] == "failed" and job["state"] not in TERMINAL:
            failed_at = failed_at if failed_at is not None else now
            if now - failed_at > GROUP_FAILED_GRACE_S:
                raise SmokeError(f"{group_text(after)} but the waiting job did not fail")
    if job["state"] != "succeeded" or job.get("error") is not None:
        raise SmokeError(f"job {job['state']}: {job.get('error')}; {group_text(last)}")
    if "tts_not_ready" in "".join(seen):
        problems.append("tts_not_ready appeared in the job")
    artifacts = (job.get("result") or {}).get("artifacts") or {}
    if not artifacts.get("final"):
        problems.append("the job result names no final video")
    mp4 = api.download(f"/videos/{video['id']}/download/mp4")
    if b"ftyp" not in mp4[:16]:
        problems.append("the downloaded file is not an mp4")
    timing = word_timing(api, job)
    if problems:
        raise SmokeError("; ".join(problems))
    total = plan.clock() - pressed
    return (
        f"waited {timings.get('generate_wait', 0):.0f}s in the queue, voice ready after "
        f"{timings.get('voice_ready', 0):.0f}s, done {total:.0f}s after the press; "
        f"mp4 {len(mp4)} bytes; {timing}"
    )


def prepare_job_ids(api: Api) -> set[str]:
    ids: set[str] = set()
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 50}
        if cursor:
            params["cursor"] = cursor
        page = api.get("/jobs", params)
        ids |= {job["id"] for job in page["items"] if job["kind"] == "runtime_prepare"}
        cursor = page.get("next_cursor")
        if not cursor:
            return ids


def run_probe(root: Path, os_name: str, env: dict[str, str], work: Path) -> dict[str, Any]:
    """Run the voice probe with the bundled interpreter; Windows uses the no-console one."""
    out = work / "voice-probe.json"
    log = work / "voice-probe.log"
    out.unlink(missing_ok=True)
    python = (
        root / "python" / "pythonw.exe" if os_name == "windows"
        else bundled_python(root, os_name)
    )
    with log.open("wb") as output:
        try:
            done = subprocess.run(
                [str(python), str(PROBE_SCRIPT), "--root", str(root), "--out", str(out)],
                env=env, stdout=output, stderr=subprocess.STDOUT, check=False,
                timeout=PROBE_TIMEOUT_S, cwd=root.parent,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"the probe took longer than {PROBE_TIMEOUT_S:.0f}s"}
    if out.is_file():
        return json.loads(out.read_text(encoding="utf-8"))
    tail = log.read_bytes()[-300:].decode("utf-8", "replace").strip()
    return {"error": f"the probe exited {done.returncode} without a result: {tail}"}


def probe_checks(result: Result, report: Mapping[str, Any]) -> None:
    names = (("tts", CHECK_TTS), ("align", CHECK_ALIGN), ("torch", CHECK_TORCH))
    for key, name in names:
        entry = report.get(key) or {"ok": False, "detail": str(report.get("error", "no result"))}
        result.check(name, bool(entry["ok"]), str(entry["detail"]))


def check_cold_start(result: Result, plan: VoicePlan, run: Running) -> bool:
    """Health and the page answer while the voice group is still preparing."""
    detail = f"health {run.health}, page {run.page}"
    if run.first_page_s is not None:
        detail += f" after {run.first_page_s:.1f}s"
        plan.timings["first_page"] = round(run.first_page_s, 1)
    ok = run.health == 200 and run.page == 200
    if run.api is None:
        return result.check(CHECK_COLD, False, f"{detail}; {run.problem}")
    try:
        group = group_of(run.api.get("/runtime"), VOICE_GROUP)
    except PROBLEMS as error:
        return result.check(CHECK_COLD, False, f"{detail}; {error}")
    ok = ok and group["state"] in ("queued", "downloading")
    return result.check(CHECK_COLD, ok, f"{detail}; {group_text(group)}")


def check_generate(result: Result, plan: VoicePlan, run: Running) -> None:
    try:
        detail = generate_during_preparation(plan, run, plan.timings)
        ok = True
    except PROBLEMS as error:
        detail, ok = str(error), False
    if plan.llm.unmatched:
        ok = False
        detail += f"; the LLM stub had no recording for {plan.llm.unmatched[:3]}"
    detail += f"; recordings used: {sorted(set(plan.llm.served))}"
    result.check(CHECK_GENERATE, ok, detail)


def check_offline(
    result: Result, plan: VoicePlan, jobs_before: set[str] | None
) -> None:
    """Start again with the network blocked: ready at once, nothing queued, nothing touched."""
    before = snapshot_tree(plan.model_dir)
    run = plan.start(True)
    problems: list[str] = []
    state = "unknown"
    try:
        if run.api is None:
            problems.append(f"the app did not come up: {run.problem}")
        else:
            group = group_of(run.api.get("/runtime"), VOICE_GROUP)
            state = group["state"]
            if state != "ready":
                problems.append(f"the first /runtime shows {group_text(group)}")
            plan.sleep(plan.settle_s)
            created = prepare_job_ids(run.api) - (jobs_before or set())
            if jobs_before is None:
                problems.append("the jobs before the restart are unknown")
            if created:
                problems.append(f"{len(created)} new runtime_prepare job(s) after the restart")
    except PROBLEMS as error:
        problems.append(str(error))
    finally:
        plan.stop(run)
    changed = changed_files(before, snapshot_tree(plan.model_dir))
    if changed:
        problems.append(f"{len(changed)} model file(s) changed: {changed[:3]}")
    detail = "; ".join(problems) or f"voice {state}, {len(before)} model files unchanged"
    result.check(CHECK_OFFLINE, not problems, detail)


def skip(result: Result, names: tuple[str, ...], reason: str) -> None:
    for name in names:
        result.check(name, False, f"not run: {reason}")


def voice_phase(result: Result, plan: VoicePlan) -> None:
    """The six voice checks, in the order their evidence arrives."""
    run = plan.start(False)
    jobs_before: set[str] | None = None
    try:
        check_cold_start(result, plan, run)
        if run.api is None:
            skip(result, (CHECK_GENERATE,), "the app is not paired")
        else:
            check_generate(result, plan, run)
            try:
                jobs_before = prepare_job_ids(run.api)
            except PROBLEMS:
                jobs_before = None
    finally:
        plan.stop(run)
    result.sizes["models_bytes"] = tree_bytes(plan.model_dir)
    result.seconds.update(plan.timings)
    # The app is stopped first: the probe loads the models again and memory is short.
    probe_checks(result, plan.probe())
    check_offline(result, plan, jobs_before)


def voice_leg(
    result: Result, args: argparse.Namespace, root: Path, env: dict[str, str], work: Path
) -> None:
    """The voice phase on the installed files: empty data folder, recorded LLM, real models."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import smoke_llm

    give_endpoint_models(root)
    hook, url_file = write_pairing_hook(work, args.os)
    data_dir = work / "voice-data"
    stub = smoke_llm.start()
    starts: list[Running] = []
    try:
        app_env = {
            **env, "APP_PROFILE": "dev", "APP_LLM_BASE_URL": stub.base_url,
            "APP_DATA_DIR": str(data_dir), "BROWSER": str(hook),
        }

        def start(offline: bool) -> Running:
            used = blocked_network(app_env) if offline else app_env
            log = work / f"voice-start-{len(starts)}.log"
            running = start_app(root, args.os, used, data_dir, log, url_file)
            running.env = used
            starts.append(running)
            return running

        def stop_app(running: Running) -> None:
            if running.process is not None and running.env is not None:
                stop_launcher(root, args.os, running.env, running.process, running.output)

        def probe() -> dict[str, Any]:
            clean = {k: v for k, v in app_env.items() if k != "BROWSER"}
            return run_probe(root, args.os, clean, work)

        plan = VoicePlan(start, stop_app, probe, data_dir / "models", stub)
        voice_phase(result, plan)
    finally:
        stub.close()


def smoke(args: argparse.Namespace) -> Result:
    result = Result()
    work = Path(tempfile.mkdtemp(prefix="smoke-"))
    try:
        home = work / HOME_NAME
        bare = work / "empty path"
        for folder in (home, bare, work / "tmp"):
            folder.mkdir(parents=True)
        env = user_environment(work, home, bare)
        root = install(args.artifact.resolve(), args.os, home / INSTALL_NAME, work)
        python = bundled_python(root, args.os)
        result.sizes["artifact_bytes"] = args.artifact.stat().st_size
        result.sizes["installed_bytes"] = tree_bytes(root)
        result.sizes["align_site_bytes"] = tree_bytes(root / "align-site")
        result.check("installed into a Korean path with spaces", python.is_file(), str(python.name))
        result.check(
            "no python or ffmpeg is reachable through PATH",
            all(shutil.which(name, path=str(bare)) is None
                for name in ("python", "python3", "ffmpeg")),
        )
        printed = subprocess.run(
            launch_base(root, args.os) + ["--print-config"], env=env,
            capture_output=True, text=True, check=False,
        )
        config = json.loads(printed.stdout) if printed.returncode == 0 else {}
        result.check(
            "the distribution file sets the profile default",
            config.get("profile") == args.profile, str(config.get("profile")),
        )
        check_runtime_ready(result, python, root, env)
        data_dir = Path(config.get("data_dir", home / "data"))
        # The gate: the distribution exactly as shipped, with no profile override. The
        # app queues the model download itself; a closed proxy keeps these starts cheap.
        offline = blocked_network(env)
        exercise(result, args.profile, root, args, offline, data_dir, work, gating=True)
        # Auxiliary: the same files with the fixture profile, to tell a packaging fault
        # from an application that cannot start yet. It never makes the run pass.
        exercise(result, "fixture", root, args, {**offline, "APP_PROFILE": "fixture"}, data_dir,
                 work, gating=False)
        if args.voice:
            try:
                voice_leg(result, args, root, env, work)
            except Exception as error:  # noqa: BLE001 - every voice check must still be reported
                done = {check["name"] for check in result.checks}
                skip(result, tuple(n for n in VOICE_CHECKS if n not in done),
                     f"{type(error).__name__}: {str(error)[:200]}")
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--os", choices=("linux", "windows"), required=True)
    parser.add_argument("--profile", choices=("release", "dev"), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--voice", action="store_true", help="run the voice phase")
    args = parser.parse_args(argv)
    result = smoke(args)
    if args.output is not None:
        args.output.write_text(
            json.dumps(result.document(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
