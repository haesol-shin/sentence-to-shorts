"""The acceptance scenarios on the real Pyodide on Deno runner (CI `sandbox` job)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.sandbox.runtime import DenoLauncher, SandboxRuntime
from tests.sandbox.conftest import (  # noqa: F401
    runtime_lock_items,
    runtime_root,
    sandbox_config_values,
)
from tests.templates import scenarios
from tests.templates.conftest import Harness, build_harness

pytestmark = pytest.mark.sandbox


@pytest.fixture
def runner(runtime_root: Path, tmp_path: Path) -> Harness:  # noqa: F811
    runtime = SandboxRuntime(runtime_root, runtime_lock_items())
    limits = sandbox_config_values()
    launcher = DenoLauncher(
        runtime,
        cache_dir=tmp_path / "cache" / "sandbox",
        memory_bytes=int(limits["memory_bytes"]),
        stdout_bytes=int(limits["stdout_bytes"]),
        stderr_bytes=int(limits["stderr_bytes"]),
    )
    return build_harness(tmp_path, launcher, runtime=runtime)


def test_6_shape_change_is_ready_in_the_runner(runner: Harness) -> None:
    scenarios.shape_change_is_ready(runner)


def test_6_color_only_change_is_rejected_in_the_runner(runner: Harness) -> None:
    scenarios.color_only_is_rejected(runner)


def test_7_narrow_eyes_changes_the_face_in_the_runner(runner: Harness) -> None:
    scenarios.narrow_eyes_changes_the_face(runner)


def test_7_body_only_change_is_rejected_in_the_runner(runner: Harness) -> None:
    scenarios.body_only_change_is_rejected(runner)


def test_17_saved_style_is_reused_without_llm_or_runner(runner: Harness) -> None:
    scenarios.saved_style_is_reused_without_calls(runner)


def test_17_saved_style_renders_a_still_from_the_runner(runner: Harness) -> None:
    scenarios.saved_style_renders_a_still(runner)


def test_17_template_renders_the_test_scene_in_the_runner(runner: Harness) -> None:
    scenarios.template_renders_the_test_scene(runner)


def test_bgm_code_twenty_seconds_is_rejected_in_the_runner(runner: Harness) -> None:
    scenarios.bgm_of_twenty_seconds_is_rejected(runner)


def test_bgm_code_bad_header_is_rejected_in_the_runner(runner: Harness) -> None:
    scenarios.bad_header_is_rejected(runner)


def test_bgm_code_same_code_and_seed_hit_the_cache_in_the_runner(runner: Harness) -> None:
    scenarios.same_code_and_seed_hit_the_cache(runner)


def test_bgm_code_failure_keeps_the_previous_bgm_in_the_runner(runner: Harness) -> None:
    scenarios.failure_keeps_the_previous_bgm(runner)
