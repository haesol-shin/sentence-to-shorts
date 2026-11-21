"""Offline coverage for the real-path preflight and its lock gate."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

import pytest

from app.settings import RuntimeFile, Settings

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "realpath_preflight", ROOT / "scripts" / "realpath_preflight.py"
)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
# The script adds its source roots for direct invocation; do not modify pytest's paths.
paths = sys.path[:]
try:
    SPEC.loader.exec_module(preflight)
finally:
    sys.path[:] = paths


def test_runtime_lock_covers_all_app_item_constants() -> None:
    lock = RuntimeFile.model_validate_json(preflight.LOCK.read_bytes())
    assert preflight.lock_issues(ROOT / "core" / "app", lock) == []


def test_runtime_lock_detects_new_item_and_missing_host(tmp_path: Path) -> None:
    (tmp_path / "adapter.py").write_text(
        'RUNTIME_ITEMS = ("new-binary", "ffmpeg", "pyodide-core")\n', encoding="utf-8"
    )
    lock = RuntimeFile.model_validate_json(preflight.LOCK.read_bytes())
    ffmpeg = next(item for item in lock.items if item.id == "ffmpeg")
    ffmpeg.files = [entry for entry in ffmpeg.files if entry.os != "windows"]
    assert preflight.lock_issues(tmp_path, lock) == [
        "ffmpeg: no file for windows/x86_64",
        "new-binary: missing from lock",
    ]


@pytest.fixture
def synthetic_run(app_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    source = tmp_path / "source"
    app = source / "app"
    app.mkdir(parents=True)
    (app / "align.py").write_text('MODEL_KO_ITEM = "model-align-ko"\n', encoding="utf-8")
    monkeypatch.setattr(preflight, "CORE", source)
    lock = app_settings.runtime
    lock.items = [item for item in lock.items if item.id == "model-align-ko"]
    monkeypatch.setattr(preflight, "Settings", lambda: app_settings)
    monkeypatch.setenv("APP_ALIGN_PYTHON", sys.executable)
    (tmp_path / "whisperx.py").touch()
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    for name in ("APP_LLM_BASE_URL", "APP_LLM_KEY_ENV", *preflight.LINK_ENVS):
        monkeypatch.delenv(name, raising=False)
    return app_settings


def test_preflight_reports_pass_and_optional_skips(synthetic_run, capsys) -> None:
    assert preflight.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS settings: loaded configuration",
        "PASS runtime lock: app runtime items have files for all three hosts",
        "PASS aligner: whisperx imports",
        "SKIP llm: APP_LLM_BASE_URL is not set",
        "SKIP link PREFLIGHT_LINK_1: not set",
        "SKIP link PREFLIGHT_LINK_2: not set",
    ]


def test_preflight_returns_failure_and_keeps_checking(synthetic_run, capsys, monkeypatch) -> None:
    synthetic_run.runtime.items.clear()
    monkeypatch.delenv("APP_ALIGN_PYTHON")
    assert preflight.main() == 1
    output = capsys.readouterr().out
    assert "FAIL runtime lock: model-align-ko: missing from lock\n" in output
    assert "FAIL aligner: set APP_ALIGN_PYTHON to the aligner Python\n" in output
    assert "SKIP link PREFLIGHT_LINK_2: not set\n" in output


def test_preflight_rejects_installed_binary_without_execute_bit(
    synthetic_run, tmp_path, monkeypatch, capsys
) -> None:
    lock = RuntimeFile.model_validate_json(preflight.LOCK.read_bytes())
    deno = next(item for item in lock.items if item.id == "deno")
    synthetic_run.runtime.items.append(deno)
    monkeypatch.setattr(preflight, "host_os", lambda: "linux")
    monkeypatch.setattr(preflight, "host_arch", lambda: "x86_64")
    binary = synthetic_run.runtime_dir / deno.install_path / "deno"
    binary.parent.mkdir(parents=True)
    binary.touch()
    with monkeypatch.context() as patch:
        # Windows does not implement the POSIX executable bit.
        patch.setattr(preflight.os, "access", lambda path, mode: False)
        assert preflight.main() == 1
    assert "FAIL version deno: not executable\n" in capsys.readouterr().out


@pytest.mark.parametrize("valid", [True, False])
def test_preflight_validates_one_schema_reply_per_route(
    synthetic_run, monkeypatch, capsys, valid
) -> None:
    requests: list[str] = []

    class Transport:
        def open(self, request: Request, *, timeout: int) -> io.BytesIO:
            assert request.get_header("Authorization") == "Bearer synthetic-secret"
            if request.get_method() == "GET":
                assert request.full_url == "https://gateway.invalid/v1/models"
                return io.BytesIO(b'{"data":[{"id":"model"}]}')
            assert request.full_url == "https://gateway.invalid/v1/chat/completions"
            payload = json.loads(request.data)
            assert payload["model"] == "model"
            assert payload["response_format"]["json_schema"]["schema"] == preflight.PROBE_SCHEMA
            requests.append(payload["model"])
            content = '{"ready":true}' if valid else '{"ready":"synthetic-secret"}'
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

    monkeypatch.setattr(preflight.urllib.request, "build_opener", lambda *_: Transport())
    monkeypatch.setenv("APP_LLM_BASE_URL", "https://gateway.invalid/v1")
    monkeypatch.setenv("APP_LLM_KEY_ENV", "PREFLIGHT_TEST_SECRET")
    monkeypatch.setenv("PREFLIGHT_TEST_SECRET", "synthetic-secret")
    for alias in synthetic_run.models.models:
        monkeypatch.setenv(f"APP_LLM_MODEL_{alias.upper()}", "model")
    assert preflight.main() == int(not valid)
    output = capsys.readouterr().out
    assert "PASS llm /models:" in output
    assert len(requests) == len(synthetic_run.models.routes)
    for route in synthetic_run.models.routes:
        assert f"{'PASS' if valid else 'FAIL'} llm route {route}:" in output
    assert "synthetic-secret" not in output


def test_preflight_probes_link_with_download_disabled(synthetic_run, monkeypatch, capsys) -> None:
    class Proxy:
        url = "http://127.0.0.1:1"
        denied: list[str] = []
        exceeded = False

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    def simulate(argv, **kwargs):
        assert argv[0] == sys.executable
        delimiter = argv.index("--")
        assert {"--simulate", "--skip-download", "--ignore-config", "--no-cookies"} <= set(
            argv[:delimiter]
        )
        assert argv[delimiter + 1:] == ["https://video.invalid/watch?v=synthetic"]
        assert kwargs["env"]["PATH"] == str(kwargs["cwd"])
        return SimpleNamespace(ok=True, stdout=b"synthetic", timed_out=False)

    monkeypatch.setenv("PREFLIGHT_LINK_1", "https://video.invalid/watch?v=synthetic")
    monkeypatch.setattr(preflight, "check_url", lambda url: url)
    monkeypatch.setattr(preflight, "runtime_executable", lambda _: Path(sys.executable))
    monkeypatch.setattr(preflight, "EgressProxy", lambda **_: Proxy())
    monkeypatch.setattr(preflight, "run", simulate)
    assert preflight.main() == 0
    output = capsys.readouterr().out
    assert "PASS link PREFLIGHT_LINK_1: metadata resolved without downloading media\n" in output
    assert "video.invalid" not in output
