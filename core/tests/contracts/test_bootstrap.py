"""Adapter selection fails at startup instead of falling back to a fixture."""

from __future__ import annotations

import pytest

from app.bootstrap import build_runtime
from app.settings import Settings


def test_unknown_adapter_fails_at_startup(app_settings: Settings) -> None:
    app_settings.providers.fixture_adapters["llm"] = "no_such_adapter"
    with pytest.raises(RuntimeError, match="unknown llm adapter"):
        build_runtime(app_settings)


def test_unimplemented_adapter_fails_at_startup(app_settings: Settings) -> None:
    app_settings.profile = "dev"
    app_settings.providers.adapters["llm"] = "anthropic_api"
    with pytest.raises(RuntimeError, match="not implemented"):
        build_runtime(app_settings)


def test_unimplemented_default_adapter_fails_in_dev(app_settings: Settings) -> None:
    app_settings.profile = "dev"
    app_settings.providers.adapters["llm"] = "fixture"
    with pytest.raises(RuntimeError, match="adapter 'default' is not implemented"):
        build_runtime(app_settings)


def test_skeleton_adapter_is_fixture_only(app_settings: Settings) -> None:
    app_settings.profile = "dev"
    app_settings.providers.adapters["llm"] = "fixture"
    app_settings.providers.adapters["aligner"] = "skeleton"
    with pytest.raises(RuntimeError, match="only available in the fixture profile"):
        build_runtime(app_settings)


def test_fixture_profile_uses_the_declared_skeleton(app_settings: Settings) -> None:
    runtime = build_runtime(app_settings)
    try:
        with pytest.raises(NotImplementedError):
            runtime.aligner.align(
                app_settings.data_dir / "missing.wav", "a", "a", "ko", cancel=None
            )
    finally:
        runtime.close()


def test_missing_selection_fails_at_startup(app_settings: Settings) -> None:
    del app_settings.providers.adapters["llm"]
    del app_settings.providers.fixture_adapters["llm"]
    with pytest.raises(RuntimeError, match="does not select a llm adapter"):
        build_runtime(app_settings)
