"""Parent supervision with a scripted launcher: protocol, error codes, limits and cache.

These tests need no runtime. The launcher stands in for the Deno process and
returns the bytes an untrusted runner could write.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.jobs import CancelFlag
from app.ports import AppError, Cancelled
from app.tools import process
from app.tools.process import MemoryCap, ProcessResult
from app.tools.sandbox.adapter import SandboxAdapter, SandboxConfig
from app.tools.sandbox.cache import ResultCache
from tests.sandbox.conftest import (
    b64,
    make_request,
    rgba_png,
    sandbox_config_values,
    tone_wav_bytes,
)

REQUEST_ID = "0123456789abcdef"


class FakeRuntime:
    def __init__(self) -> None:
        self.verified = 0

    def digest(self) -> str:
        return "ab" * 32

    def verify(self) -> None:
        self.verified += 1


class ScriptedLauncher:
    def __init__(self, *results: ProcessResult) -> None:
        self.results = list(results)
        self.payloads: list[dict] = []

    def __call__(self, payload: bytes, *, timeout_s: float, cancel) -> ProcessResult:  # type: ignore[no-untyped-def]
        self.payloads.append(json.loads(payload))
        return self.results.pop(0)


def _result(stdout: bytes = b"", **fields) -> ProcessResult:  # type: ignore[no-untyped-def]
    values = {
        "argv": ("deno",),
        "returncode": 0,
        "stdout": stdout,
        "stderr": b"",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "timed_out": False,
        "cancelled": False,
        "duration_ms": 5,
    }
    values.update(fields)
    return ProcessResult(**values)


def _line(response: dict) -> bytes:
    return json.dumps(response).encode() + b"\n"


def _png_result(*names: str, request_id: str = REQUEST_ID, meta: dict | None = None) -> bytes:
    files = [{"name": name, "media_type": "image/png", "b64": b64(rgba_png())} for name in names]
    return _line({"type": "result", "request_id": request_id, "files": files, "meta": meta or {}})


def _error(code: str, message: str) -> bytes:
    return _line({"type": "error", "request_id": REQUEST_ID, "code": code, "message": message})


def _adapter(tmp_path: Path, launcher: ScriptedLauncher, **overrides) -> SandboxAdapter:  # type: ignore[no-untyped-def]
    values = sandbox_config_values()
    values.update(overrides)
    return SandboxAdapter(
        runtime=FakeRuntime(),
        config=SandboxConfig.from_mapping(values),
        cache=ResultCache(tmp_path / "results"),
        launcher=launcher,
    )


def _style_request(**fields):  # type: ignore[no-untyped-def]
    return make_request("style_parts", "def build_assets(*a):\n    return {}\n", **fields)


def test_17_valid_result_is_returned_and_cached(tmp_path: Path) -> None:
    launcher = ScriptedLauncher(_result(_png_result("part_0", "part_1")))
    adapter = _adapter(tmp_path, launcher)
    first = adapter.run(_style_request(), cancel=CancelFlag())
    second = adapter.run(_style_request(request_id="fedcba9876543210"), cancel=CancelFlag())
    assert sorted(first.files) == ["part_0", "part_1"]
    assert first.meta["files"]["part_0"] == {"width": 4, "height": 3}
    assert second == first
    assert len(launcher.payloads) == 1


def test_17_damaged_cache_entry_runs_again_and_is_replaced(tmp_path: Path) -> None:
    launcher = ScriptedLauncher(_result(_png_result("part_0")), _result(_png_result("part_0")))
    adapter = _adapter(tmp_path, launcher)
    adapter.run(_style_request(), cancel=CancelFlag())
    for stored in (tmp_path / "results").rglob("0.bin"):
        stored.write_bytes(b"damaged")
    adapter.run(_style_request(), cancel=CancelFlag())
    adapter.run(_style_request(), cancel=CancelFlag())
    assert len(launcher.payloads) == 2


def test_17_lower_file_byte_limit_does_not_reuse_the_cache(tmp_path: Path) -> None:
    first = ScriptedLauncher(_result(_png_result("part_0")))
    _adapter(tmp_path, first).run(_style_request(), cancel=CancelFlag())
    second = ScriptedLauncher(_result(_png_result("part_0")))
    with pytest.raises(AppError) as failure:
        _adapter(tmp_path, second, max_png_bytes=16).run(_style_request(), cancel=CancelFlag())
    assert failure.value.code == "sandbox_output_invalid"
    assert len(second.payloads) == 1


def test_17_failure_is_not_cached(tmp_path: Path) -> None:
    launcher = ScriptedLauncher(_result(timed_out=True), _result(_png_result("part_0")))
    adapter = _adapter(tmp_path, launcher)
    with pytest.raises(AppError) as failure:
        adapter.run(_style_request(), cancel=CancelFlag())
    assert failure.value.code == "sandbox_timeout"
    assert adapter.run(_style_request(), cancel=CancelFlag()).files
    assert len(launcher.payloads) == 2


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (_result(timed_out=True), "sandbox_timeout"),
        (_result(memory_limited=True, returncode=-9), "sandbox_memory"),
        (_result(b"x" * 10, output_limited=True, returncode=-9), "sandbox_output_invalid"),
        (_result(_png_result("part_0"), stdout_truncated=True), "sandbox_output_invalid"),
        (_result(returncode=4), "sandbox_unavailable"),
        (_result(returncode=1), "sandbox_crashed"),
        (_result(_png_result("part_0") * 2), "sandbox_output_invalid"),
        (_result(_png_result("part_0")[:-1]), "sandbox_output_invalid"),
        (_result(b"{}\n"), "sandbox_output_invalid"),
        (_result(_png_result("part_0", request_id="fedcba9876543210")), "sandbox_output_invalid"),
        (_result(_error("import_denied", "import of 'os' is not allowed")), "sandbox_denied"),
        (
            _result(_error("python_exception", "JsException: NotCapable: Requires read access")),
            "sandbox_denied",
        ),
        (_result(_error("python_exception", "MemoryError")), "sandbox_memory"),
        (_result(_error("python_exception", "ZeroDivisionError")), "sandbox_crashed"),
        (_result(_error("bad_return", "expected a PIL image")), "sandbox_output_invalid"),
        (_result(_error("too_many_files", "65 images returned")), "sandbox_output_invalid"),
    ],
)
def test_17_runner_outcomes_map_to_job_error_codes(
    tmp_path: Path, result: ProcessResult, code: str
) -> None:
    adapter = _adapter(tmp_path, ScriptedLauncher(result))
    with pytest.raises(AppError) as failure:
        adapter.run(_style_request(), cancel=CancelFlag())
    assert failure.value.code == code


def test_17_python_traceback_is_kept_for_repair_only(tmp_path: Path) -> None:
    result = _result(_error("python_exception", "Traceback: ZeroDivisionError"))
    adapter = _adapter(tmp_path, ScriptedLauncher(result))
    with pytest.raises(AppError) as failure:
        adapter.run(_style_request(), cancel=CancelFlag())
    assert failure.value.detail == {
        "runner_code": "python_exception",
        "message": "Traceback: ZeroDivisionError",
    }


@pytest.mark.parametrize(
    ("kind", "files"),
    [
        ("style_parts", [{"name": "loop", "media_type": "audio/wav", "wav": True}]),
        ("bgm_loop", [{"name": "loop", "media_type": "image/png", "wav": False}]),
        ("template_layer", [{"name": "other", "media_type": "image/png", "wav": False}]),
        (
            "template_layer",
            [
                {"name": "layer", "media_type": "image/png", "wav": False},
                {"name": "extra", "media_type": "image/png", "wav": False},
            ],
        ),
    ],
)
def test_17_files_must_match_the_kind(tmp_path: Path, kind: str, files: list[dict]) -> None:
    encoded = [
        {
            "name": item["name"],
            "media_type": item["media_type"],
            "b64": b64(tone_wav_bytes() if item["wav"] else rgba_png()),
        }
        for item in files
    ]
    stdout = _line({"type": "result", "request_id": REQUEST_ID, "files": encoded, "meta": {}})
    adapter = _adapter(tmp_path, ScriptedLauncher(_result(stdout)))
    request = make_request(kind, "x = 1\n")
    with pytest.raises(AppError) as failure:
        adapter.run(request, cancel=CancelFlag())
    assert failure.value.code == "sandbox_output_invalid"


def test_17_runner_png_is_checked_by_the_parent(tmp_path: Path) -> None:
    files = [{"name": "part", "media_type": "image/png", "b64": b64(b"\x89PNG\r\n\x1a\n" + b"\0")}]
    stdout = _line({"type": "result", "request_id": REQUEST_ID, "files": files, "meta": {}})
    adapter = _adapter(tmp_path, ScriptedLauncher(_result(stdout)))
    with pytest.raises(AppError) as failure:
        adapter.run(_style_request(), cancel=CancelFlag())
    assert failure.value.code == "sandbox_output_invalid"


def test_17_bgm_result_carries_the_measurements(tmp_path: Path) -> None:
    files = [{"name": "loop", "media_type": "audio/wav", "b64": b64(tone_wav_bytes())}]
    stdout = _line({"type": "result", "request_id": REQUEST_ID, "files": files, "meta": {}})
    adapter = _adapter(tmp_path, ScriptedLauncher(_result(stdout)))
    output = adapter.run(make_request("bgm_loop", "x = 1\n"), cancel=CancelFlag())
    measured = output.meta["files"]["loop"]
    assert measured["duration_ms"] == 1000
    assert measured["sample_peak_dbfs_x10"] == -140


def test_17_layer_meta_is_passed_through(tmp_path: Path) -> None:
    stdout = _png_result("layer", meta={"anchor": [1, 2]})
    adapter = _adapter(tmp_path, ScriptedLauncher(_result(stdout)))
    output = adapter.run(make_request("template_layer", "x = 1\n"), cancel=CancelFlag())
    assert output.meta["program"] == {"anchor": [1, 2]}
    assert list(output.files) == ["layer"]


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("style_parts", {"input": {"spec": {}, "character": {}}}),
        ("style_parts", {"input": {"spec": {}, "character": {}, "canvas": {}, "home": "x"}}),
        ("bgm_loop", {"input": {"params": {}, "api_key": "x"}}),
        ("style_parts", {"assets": [{"name": "part", "png_b64": b64(rgba_png())}]}),
        (
            "style_parts",
            {"input": {"spec": {}, "character": {}, "canvas": {"width": 4000, "height": 10}}},
        ),
    ],
)
def test_17_parent_limits_the_input_to_the_entry_arguments(
    tmp_path: Path, kind: str, fields: dict
) -> None:
    launcher = ScriptedLauncher()
    adapter = _adapter(tmp_path, launcher)
    with pytest.raises(ValueError):
        adapter.run(make_request(kind, "x = 1\n", **fields), cancel=CancelFlag())
    assert launcher.payloads == []


def test_17_configured_limits_cap_the_request_limits(tmp_path: Path) -> None:
    launcher = ScriptedLauncher(_result(_png_result("part_0")))
    adapter = _adapter(tmp_path, launcher, max_png_side=512, max_files=4)
    canvas = {"width": 256, "height": 256}
    request = _style_request(input={"spec": {}, "character": {}, "canvas": canvas})
    adapter.run(request, cancel=CancelFlag())
    assert launcher.payloads[0]["limits"] == {
        "max_files": 4,
        "max_png_side": 512,
        "max_wav_ms": 16000,
    }


def test_17_cancel_before_run_starts_nothing(tmp_path: Path) -> None:
    launcher = ScriptedLauncher()
    token = CancelFlag()
    token.cancel()
    with pytest.raises(Cancelled):
        _adapter(tmp_path, launcher).run(_style_request(), cancel=token)
    assert launcher.payloads == []


def test_17_cancelled_process_raises_cancelled(tmp_path: Path) -> None:
    token = CancelFlag()

    class CancellingLauncher(ScriptedLauncher):
        def __call__(self, payload: bytes, *, timeout_s: float, cancel) -> ProcessResult:  # type: ignore[no-untyped-def]
            token.cancel()
            return _result(cancelled=True, returncode=-9)

    with pytest.raises(Cancelled):
        _adapter(tmp_path, CancellingLauncher()).run(_style_request(), cancel=token)


def test_17_runner_start_logs_an_unverified_memory_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    unverified = MemoryCap(False, "none", "systemd user scope is unavailable", 1 << 30)
    monkeypatch.setattr(process, "memory_cap_status", lambda limit: unverified)
    adapter = _adapter(tmp_path, ScriptedLauncher(_result(_png_result("part_0"))))
    with caplog.at_level(logging.INFO, logger="app.tools.sandbox.adapter"):
        adapter.run(_style_request(), cancel=CancelFlag())
    starts = [record for record in caplog.records if record.getMessage() == "sandbox_runner_start"]
    assert len(starts) == 1
    assert starts[0].memory_cap == "unverified"
    assert starts[0].memory_cap_reason == "systemd user scope is unavailable"
