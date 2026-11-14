"""Shared pytest fixtures: isolated data roots and an app client."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"


@pytest.fixture
def app_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_PROFILE", "fixture")
    monkeypatch.setenv("APP_DEPLOYMENT", "local")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("APP_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("APP_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("APP_LAN", "0")
    monkeypatch.delenv("APP_PORT", raising=False)
    from app.settings import Settings

    return Settings()


@pytest.fixture
def client(app_settings) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.bootstrap import build_runtime
    from app.main import create_app

    with TestClient(create_app(build_runtime(app_settings))) as test_client:
        yield test_client


def load_json(relative: str):  # type: ignore[no-untyped-def]
    import json

    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:  # type: ignore[no-untyped-def]
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
