"""Offline regression coverage for the settings shared by real acceptance and the app."""

from __future__ import annotations

import pytest

from app.settings import Settings


def test_dev_profile_reads_endpoint_models_and_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PROFILE", "dev")
    monkeypatch.setenv("APP_LLM_MODEL_HAIKU", "endpoint-small")
    monkeypatch.setenv("APP_LLM_MODEL_SONNET", "endpoint-large")
    monkeypatch.setenv("APP_LLM_KEY_ENV", "SYNTHETIC_KEY_VAR")
    settings = Settings()
    assert settings.models.models["haiku"]["openai_compat"] == "endpoint-small"
    assert settings.models.models["sonnet"]["openai_compat"] == "endpoint-large"
    assert settings.llm_options["openai_compat"] == {
        "key_env": "SYNTHETIC_KEY_VAR", "key_required": True,
    }


def test_dev_profile_without_key_env_does_not_require_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_PROFILE", "dev")
    monkeypatch.delenv("APP_LLM_KEY_ENV", raising=False)
    assert not Settings().llm_options["openai_compat"]["key_required"]


@pytest.mark.parametrize("profile", ["fixture", "release"])
def test_other_profiles_ignore_the_dev_endpoint_variables(
    monkeypatch: pytest.MonkeyPatch, profile: str,
) -> None:
    monkeypatch.setenv("APP_PROFILE", profile)
    monkeypatch.setenv("APP_LLM_MODEL_HAIKU", "endpoint-small")
    monkeypatch.setenv("APP_LLM_MODEL_SONNET", "endpoint-large")
    monkeypatch.setenv("APP_LLM_KEY_ENV", "SYNTHETIC_KEY_VAR")
    settings = Settings()
    assert settings.models.models["haiku"]["openai_compat"] != "endpoint-small"
    assert settings.models.models["sonnet"]["openai_compat"] != "endpoint-large"
    assert "openai_compat" not in settings.llm_options
