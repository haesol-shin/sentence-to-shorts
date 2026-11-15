"""Startup pairing output and runtime cleanup when the idempotency gate fails."""

from __future__ import annotations

import io
from contextlib import nullcontext
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.bootstrap import build_runtime
from tests.conftest import browser_client


class _RedirectedOutput(io.StringIO):
    def isatty(self) -> bool:
        return False


class _TerminalOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_startup_pairing_url_is_usable_and_stays_out_of_captured_output(
    app_settings, capsys
) -> None:  # type: ignore[no-untyped-def]
    urls: list[str] = []
    app = main.create_app(
        build_runtime(app_settings), pairing_display=urls.append
    )
    with browser_client(app, app_settings.port) as client:
        assert len(urls) == 1
        parsed = urlsplit(urls[0])
        assert parsed.scheme == "http"
        assert parsed.hostname == "127.0.0.1"
        assert parsed.port == app_settings.port
        assert parsed.fragment.startswith("pair=")
        code = parsed.fragment.split("=", 1)[1]
        assert code

        # The startup code itself is exchanged; no second code is issued.
        response = client.post("/api/v1/session/pair", json={"code": code})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        assert client.get("/api/v1/runtime").status_code == 200

    captured = capsys.readouterr()
    assert "#pair=" not in captured.out
    assert code not in captured.out
    assert code not in captured.err


def test_default_display_uses_a_tty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    url = "http://127.0.0.1:8700/#pair=synthetic-code-0123456789"
    terminal = _TerminalOutput()
    monkeypatch.setattr(main.sys, "stdout", terminal)
    main._display_pairing_url(url)
    assert "Pair this browser" in terminal.getvalue()
    assert url in terminal.getvalue()


def test_default_display_never_writes_a_secret_to_redirected_stdout(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    url = "http://127.0.0.1:8700/#pair=synthetic-code-0123456789"
    redirected = _RedirectedOutput()
    terminal = io.StringIO()
    monkeypatch.setattr(main.sys, "stdout", redirected)
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: nullcontext(terminal))

    main._display_pairing_url(url)

    assert redirected.getvalue() == ""
    assert url in terminal.getvalue()


def test_default_display_fails_loudly_without_a_local_terminal(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main.sys, "stdout", _RedirectedOutput())

    def no_terminal(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise OSError("no controlling terminal")

    monkeypatch.setattr("builtins.open", no_terminal)
    with pytest.raises(RuntimeError, match="local terminal"):
        main._display_pairing_url("http://127.0.0.1:8700/#pair=synthetic")


def test_runtime_closes_when_the_idempotency_gate_cannot_open(
    app_settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    runtime = build_runtime(app_settings)
    closed: list[bool] = []
    original_close = runtime.close

    def close() -> None:
        original_close()
        closed.append(True)

    monkeypatch.setattr(runtime, "close", close)

    def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise OSError("state unavailable")

    monkeypatch.setattr(main.IdempotencyGate, "open", classmethod(fail))
    app = main.create_app(runtime, pairing_display=lambda _url: None)
    with pytest.raises(OSError, match="state unavailable"):
        with TestClient(app):
            pass
    assert closed == [True]
