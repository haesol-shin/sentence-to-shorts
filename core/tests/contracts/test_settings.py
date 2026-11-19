"""Settings read `APP_DEVICE` once and reject a value no adapter knows."""

from __future__ import annotations

import pytest

from app.settings import Settings


def test_device_defaults_to_auto(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_DEVICE", raising=False)
    assert Settings().device == "auto"


@pytest.mark.parametrize("value", ["auto", "cpu", "cuda"])
def test_device_reads_the_environment(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("APP_DEVICE", value)
    assert Settings().device == value


def test_device_rejects_an_unknown_value(
    app_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DEVICE", "gpu")
    with pytest.raises(RuntimeError, match="APP_DEVICE must be"):
        Settings()
