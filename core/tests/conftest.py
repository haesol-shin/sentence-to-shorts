"""Shared pytest fixtures: isolated data roots and a paired app client."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"
LOOPBACK_CLIENT = ("127.0.0.1", 50000)


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


def browser_client(
    app,  # type: ignore[no-untyped-def]
    port: int,
    *,
    host: str = "127.0.0.1",
    client: tuple[str, int] = LOOPBACK_CLIENT,
    raise_server_exceptions: bool = True,
) -> TestClient:
    """An unpaired client that talks to the app the way the same-origin SPA does."""
    origin = f"http://{host}:{port}"
    test_client = TestClient(
        app,
        base_url=origin,
        client=client,
        headers={"Origin": origin},
        raise_server_exceptions=raise_server_exceptions,
    )
    test_client.event_hooks = {"request": [_add_idempotency_key]}
    return test_client


def _add_idempotency_key(request: Any) -> None:
    if request.method == "POST" and "Idempotency-Key" not in request.headers:
        request.headers["Idempotency-Key"] = uuid.uuid4().hex


def pair(test_client: TestClient, code: str | None = None) -> str:
    """Exchange a fresh pairing code for a session cookie and keep the CSRF token."""
    if code is None:
        code = test_client.app.state.runtime.access.issue_pairing_code()  # type: ignore[attr-defined]
    response = test_client.post("/api/v1/session/pair", json={"code": code})
    assert response.status_code == 200, response.text
    token = response.json()["csrf_token"]
    test_client.headers["X-CSRF-Token"] = token
    return token


@pytest.fixture
def client(app_settings) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.bootstrap import build_runtime
    from app.main import create_app

    pairing_urls: list[str] = []
    app = create_app(build_runtime(app_settings), pairing_display=pairing_urls.append)
    with browser_client(app, app_settings.port) as test_client:
        pair(test_client, pairing_urls[0].split("#pair=", 1)[1])
        yield test_client


def load_json(relative: str):  # type: ignore[no-untyped-def]
    import json

    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:  # type: ignore[no-untyped-def]
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
