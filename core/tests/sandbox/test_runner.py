"""Denial tests on the real runner (CONTRACTS 9.6). They need the pinned runtime.

Every attack program steps around the import hook on purpose, so a pass shows
that the Deno permissions or the parent stopped it, not the hook.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path

import pytest

from app.jobs import CancelFlag
from app.ports import AppError
from app.tools import process
from app.tools.sandbox.adapter import SandboxAdapter, SandboxConfig
from app.tools.sandbox.cache import ResultCache
from app.tools.sandbox.runtime import DenoLauncher, SandboxRuntime
from tests.sandbox.conftest import (
    b64,
    make_request,
    program,
    rgba_png,
    runtime_lock_items,
    sandbox_config_values,
)

pytestmark = pytest.mark.sandbox

# The configured limits, with a shorter wall time so the loop test ends sooner.
TEST_WALL_MS = 30000
DENIED_ATTACKS = (
    "js_bridge_sys",
    "file_read",
    "file_write",
    "network_fetch",
    "env_read",
    "subprocess_run",
    "ffi_dlopen",
    "permission_request",
    "remote_import",
)


def _adapter(runtime_root: Path, tmp_path: Path, launcher=None) -> SandboxAdapter:  # type: ignore[no-untyped-def]
    values = sandbox_config_values()
    values["wall_ms"] = {kind: TEST_WALL_MS for kind in values["wall_ms"]}
    config = SandboxConfig.from_mapping(values)
    runtime = SandboxRuntime(runtime_root, runtime_lock_items())
    return SandboxAdapter(
        runtime=runtime,
        config=config,
        cache=ResultCache(tmp_path / "cache" / "results"),
        launcher=launcher
        or DenoLauncher(
            runtime,
            cache_dir=tmp_path / "cache",
            memory_bytes=config.memory_bytes,
            stdout_bytes=config.stdout_bytes,
            stderr_bytes=config.stderr_bytes,
        ),
    )


def _failure(adapter: SandboxAdapter, kind: str, name: str) -> AppError:
    with pytest.raises(AppError) as failure:
        adapter.run(make_request(kind, program(name)), cancel=CancelFlag())
    return failure.value


def test_17_style_parts_program_returns_checked_pngs(runtime_root: Path, tmp_path: Path) -> None:
    adapter = _adapter(runtime_root, tmp_path)
    request = make_request("style_parts", program("style_parts_ok"))
    output = adapter.run(request, cancel=CancelFlag())
    assert sorted(output.files) == ["part_0", "part_1"]
    for name, data in output.files.items():
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", data[16:24]) == (64, 64)
        assert output.meta["files"][name] == {"width": 64, "height": 64}


def test_17_bgm_program_returns_a_checked_wav(runtime_root: Path, tmp_path: Path) -> None:
    adapter = _adapter(runtime_root, tmp_path)
    output = adapter.run(make_request("bgm_loop", program("bgm_loop_ok")), cancel=CancelFlag())
    assert list(output.files) == ["loop"]
    measured = output.meta["files"]["loop"]
    assert measured["duration_ms"] == 2000
    assert measured["sample_peak_dbfs_x10"] is not None
    assert measured["loudness_lufs_x10"] is not None


@pytest.mark.parametrize("name", DENIED_ATTACKS)
def test_17_attack_is_denied_by_the_deno_permissions(
    runtime_root: Path, tmp_path: Path, name: str
) -> None:
    error = _failure(_adapter(runtime_root, tmp_path), "style_parts", name)
    assert error.code == "sandbox_denied", error.detail
    assert error.detail["runner_code"] == "python_exception"


def test_17_import_outside_the_allowlist_is_refused(runtime_root: Path, tmp_path: Path) -> None:
    error = _failure(_adapter(runtime_root, tmp_path), "style_parts", "import_outside_allowlist")
    assert error.code == "sandbox_denied"
    assert error.detail["runner_code"] == "import_denied"


def test_17_infinite_loop_is_killed_by_the_parent(runtime_root: Path, tmp_path: Path) -> None:
    error = _failure(_adapter(runtime_root, tmp_path), "style_parts", "infinite_loop")
    assert error.code == "sandbox_timeout"


def test_17_memory_spike_is_stopped(runtime_root: Path, tmp_path: Path) -> None:
    error = _failure(_adapter(runtime_root, tmp_path), "style_parts", "memory_spike")
    assert error.code == "sandbox_memory", error.detail


def test_17_stdout_flood_is_cut_by_the_parent(runtime_root: Path, tmp_path: Path) -> None:
    error = _failure(_adapter(runtime_root, tmp_path), "style_parts", "stdout_flood")
    assert error.code == "sandbox_output_invalid"
    assert error.detail == {"reason": "stdout passed its limit"}


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("style_parts", "bad_png"),
        ("bgm_loop", "bad_wav_header"),
        ("bgm_loop", "overlong_wav"),
    ],
)
def test_17_invalid_output_is_rejected_by_the_parent_validator(
    runtime_root: Path, tmp_path: Path, kind: str, name: str
) -> None:
    error = _failure(_adapter(runtime_root, tmp_path), kind, name)
    assert error.code == "sandbox_output_invalid"
    assert error.detail["reason"].startswith(("part:", "loop:"))


def test_17_state_does_not_survive_into_the_next_run(runtime_root: Path, tmp_path: Path) -> None:
    adapter = _adapter(runtime_root, tmp_path)
    plant = make_request("template_layer", program("state_leak_plant"))
    adapter.run(plant, cancel=CancelFlag())
    asset = {"name": "part_0", "png_b64": b64(rgba_png(width=8, height=8))}
    check = make_request("template_layer", program("state_leak_check"), assets=[asset])
    output = adapter.run(check, cancel=CancelFlag())
    assert output.meta["program"] == {
        "module": False,
        "file": False,
        "patch": False,
        "parts": ["part_0"],
    }


def test_17_same_input_twice_starts_one_process(
    runtime_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts = []
    real_run = process.run

    def counting_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        starts.append(args[0])
        return real_run(*args, **kwargs)

    monkeypatch.setattr(process, "run", counting_run)
    adapter = _adapter(runtime_root, tmp_path)
    request = make_request("style_parts", program("style_parts_ok"))
    first = adapter.run(request, cancel=CancelFlag())
    second = adapter.run(request, cancel=CancelFlag())
    assert second == first
    assert len(starts) == 1


def test_17_runner_start_reports_the_memory_cap(
    runtime_root: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    adapter = _adapter(runtime_root, tmp_path)
    with caplog.at_level(logging.INFO, logger="app.tools.sandbox.adapter"):
        adapter.run(make_request("bgm_loop", program("bgm_loop_ok")), cancel=CancelFlag())
    starts = [record for record in caplog.records if record.getMessage() == "sandbox_runner_start"]
    assert len(starts) == 1
    status = process.memory_cap_status(sandbox_config_values()["memory_bytes"])
    assert starts[0].memory_cap == ("applied" if status.applied else "unverified")
    assert starts[0].memory_cap_mechanism == status.mechanism
