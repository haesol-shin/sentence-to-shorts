#!/usr/bin/env python3
"""Check the local real-run setup without preparing files or running a job."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path[:0] = [str(CORE), str(ROOT)]

from app.jobs import CancelFlag
from app.llm.common import resolve_route, validate_output
from app.llm.providers.openai_compat.adapter import OpenAiCompatLlm
from app.ports import AppError, LlmPart, LlmRequest, LlmTask
from app.settings import RuntimeFile, Settings
from app.tools.align.adapter import PYTHON_ENV
from app.tools.downloaders.adapter import RUNTIME_ITEM as DOWNLOADER_ITEM
from app.tools.downloaders.adapter import create as create_downloader
from app.tools.downloaders.ytdlp.downloader import COMPLETED_EXITS
from app.tools.downloaders.ytdlp.egress import EgressProxy
from app.tools.downloaders.ytdlp.urls import check_url
from app.tools.process import build_env, run
from scripts.dev_setup import LOCK, host_arch, host_os

HOSTS = (("linux", "x86_64"), ("linux", "aarch64"), ("windows", "x86_64"))
NATIVE_EXECUTABLES = frozenset({"deno", "ffmpeg"})
LINK_ENVS = ("PREFLIGHT_LINK_1", "PREFLIGHT_LINK_2")
PROBE_SCHEMA = {
    "type": "object",
    "required": ["ready"],
    "properties": {"ready": {"type": "boolean"}},
    "additionalProperties": False,
}
HTTP_TIMEOUT = 6


class CheckFailed(Exception):
    """A failure with a diagnostic that is safe to print."""


def _item_constants(app_dir: Path) -> Iterator[tuple[Path, str]]:
    for path in sorted(app_dir.rglob("*.py")):
        for node in ast.parse(path.read_bytes(), filename=str(path)).body:
            targets = node.targets if isinstance(node, ast.Assign) else (
                [node.target] if isinstance(node, ast.AnnAssign) else []
            )
            if not any(isinstance(target, ast.Name) and target.id.endswith(("_ITEM", "_ITEMS"))
                       for target in targets):
                continue
            values = ast.literal_eval(node.value)
            for value in (values,) if isinstance(values, str) else values:
                yield path.relative_to(app_dir), value


def lock_issues(app_dir: Path, lock: RuntimeFile) -> list[str]:
    items = {item.id: item for item in lock.items}
    issues = []
    required = set()
    for path, value in _item_constants(app_dir):
        if path.as_posix() == "tools/asr/faster_whisper/adapter.py":
            # The ASR constant names the model directory, not the lock ID.
            asr = items.get("model-asr-small")
            if asr is not None and Path(asr.install_path).parts[:1] != (value,):
                issues.append("model-asr-small: install_path does not match the ASR model directory")
            value = "model-asr-small"
        required.add(value)
    for item_id in sorted(required):
        if item_id not in items:
            issues.append(f"{item_id}: missing from lock")
            continue
        targets = {(entry.os, entry.arch) for entry in items[item_id].files}
        if item_id not in NATIVE_EXECUTABLES and ("any", "wasm32") in targets:
            continue
        for system, arch in HOSTS:
            if (system, arch) not in targets:
                issues.append(f"{item_id}: no file for {system}/{arch}")
    return issues


def _check_lock(lock: RuntimeFile) -> str:
    issues = lock_issues(CORE / "app", lock)
    if issues:
        raise CheckFailed("; ".join(issues))
    return "app runtime items have files for all three hosts"


def _version_checks(settings: Settings) -> Iterator[tuple[str, Callable[[], str]]]:
    system, arch = host_os(), host_arch()
    for item in settings.runtime.items:
        if item.id == DOWNLOADER_ITEM:
            # The platform-independent yt-dlp file is run by the app's Python.
            path = (settings.runtime_dir / item.install_path / item.files[0].file).resolve()
            yield f"version {item.id}", lambda path=path: _version(path, DOWNLOADER_ITEM)
            continue
        # Native lock entries are executables today; Deno's file is its archive.
        for entry in item.files:
            if (entry.os, entry.arch) != (system, arch):
                continue
            name = entry.file
            if item.id == "deno":
                name = "deno.exe" if system == "windows" else "deno"
            path = (settings.runtime_dir / item.install_path / name).resolve()
            yield f"version {item.id}", lambda path=path, item_id=item.id: _version(path, item_id)


def _version(path: Path, item_id: str) -> str:
    if not path.is_file():
        raise CheckFailed("not installed under APP_RUNTIME_DIR")
    command = [str(path)]
    if item_id == DOWNLOADER_ITEM:
        command.insert(0, sys.executable)
    elif not os.access(path, os.X_OK):
        raise CheckFailed("not executable")
    # FFmpeg uses -version, not --version.
    flag = "-version" if item_id == "ffmpeg" else "--version"
    result = subprocess.run([*command, flag], capture_output=True, timeout=3, check=False)
    if result.returncode or not (result.stdout or result.stderr).strip():
        raise CheckFailed("version command failed")
    return "version command responded"


def _aligner() -> str:
    configured = os.environ.get(PYTHON_ENV)
    if not configured:
        raise CheckFailed(f"set {PYTHON_ENV} to the aligner Python")
    # Do not resolve symlinks: a virtual environment Python may be a symlink.
    python = Path(configured).expanduser().absolute()
    result = subprocess.run([str(python), "-c", "import whisperx"], timeout=15,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise CheckFailed("cannot import whisperx")
    return "whisperx imports"


def _gateway(settings: Settings, base_url: str) -> OpenAiCompatLlm:
    routing = settings.models.model_copy(deep=True)
    for alias, providers in routing.models.items():
        model = os.environ.get(f"APP_LLM_MODEL_{alias.upper()}")
        if model:
            providers["openai_compat"] = model
    key_env = os.environ.get("APP_LLM_KEY_ENV")
    if key_env and not os.environ.get(key_env):
        raise CheckFailed("APP_LLM_KEY_ENV names an unset or empty variable")
    try:
        return OpenAiCompatLlm(settings, routing=routing, base_url=base_url, key_env=key_env)
    except ValueError:
        raise CheckFailed("APP_LLM_BASE_URL must be an HTTP(S) API base URL") from None


def _list_models(gateway: OpenAiCompatLlm) -> set[str]:
    url = gateway.url.removesuffix("/chat/completions") + "/models"
    key = gateway._developer_key()
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with gateway.opener.open(urllib.request.Request(url, headers=headers),
                                 timeout=HTTP_TIMEOUT) as response:
            data = json.loads(response.read(1024 * 1024))
        models = data["data"]
        if not isinstance(models, list) or not all(
            isinstance(model, dict) and isinstance(model.get("id"), str) for model in models
        ):
            raise ValueError
    except urllib.error.HTTPError as error:
        error.close()
        raise CheckFailed(f"model listing returned HTTP {error.code}") from None
    except (ValueError, KeyError, TypeError):
        raise CheckFailed("model listing is not an OpenAI model list") from None
    return {model["id"] for model in models}


def _route(gateway: OpenAiCompatLlm, route_id: str, models: set[str]) -> str:
    try:
        route = resolve_route(gateway.routing, route_id, gateway.provider)
    except AppError:
        raise CheckFailed("no configured model ID for this route") from None
    if route.model not in models:
        raise CheckFailed("configured model missing from /models")
    request = LlmRequest(
        task=LlmTask(route_id.split(".", 1)[0]), route=route_id,
        system="Answer the synthetic health check.",
        parts=[LlmPart(kind="text", text="Report readiness as true.")],
        output_schema=PROBE_SCHEMA, max_output_tokens=32,
    )
    # Use the real transport and validator, but send exactly one attempt: no repair or retry.
    reply = gateway._invoke(request, route, timeout=HTTP_TIMEOUT, cancel=CancelFlag(),
                            deadline=time.monotonic() + HTTP_TIMEOUT, key=gateway._developer_key())
    if validate_output(reply.text, PROBE_SCHEMA) != {"ready": True}:
        raise CheckFailed("schema-valid response did not report readiness")
    return "response passed schema validation"


def _link(settings: Settings, url: str) -> str:
    if settings.deployment == "hosted":
        raise CheckFailed("link downloads are disabled in hosted mode")
    checked = check_url(url)
    downloader = create_downloader(settings)
    if not downloader.available():
        raise CheckFailed("bundled downloader not installed")
    budget = 8 * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="preflight-") as directory:
        root = Path(directory)
        env = build_env({"PATH": str(root), "HOME": str(root), "USERPROFILE": str(root),
                         "TMPDIR": str(root), "TMP": str(root), "TEMP": str(root)})
        with EgressProxy(max_bytes=budget) as proxy:
            argv = downloader.command(
                proxy=proxy.url, out_dir=root, scratch=root, name="check",
                max_bytes=settings.app.uploads.reference_max_bytes, url=checked,
            )
            argv[-2:-2] = ["--simulate", "--skip-download", "--print", "id"]
            result = run(argv, cwd=root, env=env, timeout_s=10, cancel=CancelFlag(),
                         max_stdout_bytes=4096, max_stderr_bytes=8192)
            if result.timed_out:
                raise CheckFailed("metadata probe timed out")
            if result.returncode not in COMPLETED_EXITS or not result.stdout.strip() or proxy.denied or proxy.exceeded:
                raise CheckFailed("bundled downloader could not resolve metadata")
    return "metadata resolved without downloading media"


def _check(label: str, probe: Callable[[], Any]) -> tuple[Any, bool]:
    try:
        result = probe()
    except CheckFailed as error:
        print(f"FAIL {label}: {error}", flush=True)
    except AppError as error:
        print(f"FAIL {label}: {error.code}", flush=True)
    except (OSError, ValueError, SyntaxError, subprocess.TimeoutExpired) as error:
        # Exception details can include local paths, secret headers, URLs or provider output.
        print(f"FAIL {label}: {type(error).__name__}", flush=True)
    else:
        return result, True
    return None, False


def _report(label: str, probe: Callable[[], str]) -> bool:
    message, passed = _check(label, probe)
    if passed:
        print(f"PASS {label}: {message}", flush=True)
    return passed


def _llm(settings: Settings) -> bool:
    base_url = os.environ.get("APP_LLM_BASE_URL")
    if not base_url:
        print("SKIP llm: APP_LLM_BASE_URL is not set", flush=True)
        return True
    gateway, ok = _check("llm configuration", lambda: _gateway(settings, base_url))
    if not ok:
        return False
    models, ok = _check("llm /models", lambda: _list_models(gateway))
    if not ok:
        return False
    print("PASS llm /models: model list is valid", flush=True)
    routes = list(settings.models.routes)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(lambda route: _route_result(gateway, route, models), routes)
        return all(list(results))


def _route_result(gateway: OpenAiCompatLlm, route: str, models: set[str]) -> bool:
    return _report(f"llm route {route}", lambda: _route(gateway, route, models))


def main() -> int:
    settings, ok = _check("settings", Settings)
    if not ok:
        return 1
    print("PASS settings: loaded configuration", flush=True)
    checks = [
        _report("runtime lock", lambda: _check_lock(settings.runtime)),
        *(_report(label, probe) for label, probe in _version_checks(settings)),
        _report("aligner", _aligner),
        _llm(settings),
    ]
    for name in LINK_ENVS:
        if url := os.environ.get(name):
            checks.append(_report(f"link {name}", lambda: _link(settings, url)))
        else:
            print(f"SKIP link {name}: not set", flush=True)
    return int(not all(checks))


if __name__ == "__main__":
    sys.exit(main())
