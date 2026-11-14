"""The app declaration answers OpenAPI without building adapters or packages."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.bootstrap import declare


def test_openapi_does_not_build_a_runtime(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("build_runtime must not run for the declaration")

    monkeypatch.setattr(main, "build_runtime", fail)
    app = main.create_app()
    document = app.openapi()
    assert document["paths"]
    assert app.state.runtime is None


def test_lifespan_acquires_and_releases_the_runtime(app_settings) -> None:  # type: ignore[no-untyped-def]
    app = main.create_app(declaration=declare(app_settings))
    with TestClient(app) as client:
        assert client.app.state.runtime is not None  # type: ignore[attr-defined]
    assert app.state.runtime is None
