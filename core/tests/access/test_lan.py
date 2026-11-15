"""Default loopback bind, LAN docs/debug off, Host allowlist and loopback-only CRUD."""

from __future__ import annotations

from app.bootstrap import AppDeclaration, declare
from app.main import create_app
from tests.access.support import access_env, assert_problem, install_draft_submit
from tests.conftest import pair

SELECTED_IP = "192.168.1.50"
PHONE_CLIENT = ("192.168.1.77", 50000)


def _lan_settings(app_settings):  # type: ignore[no-untyped-def]
    return app_settings.model_copy(
        deep=True, update={"lan": True, "bind_host": SELECTED_IP}
    )


def test_default_settings_bind_only_loopback(app_settings) -> None:  # type: ignore[no-untyped-def]
    assert app_settings.lan is False
    assert app_settings.bind_host == "127.0.0.1"


def test_default_launcher_binds_loopback_and_never_reloads(
    app_settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import app.__main__ as runner

    captured: dict[str, object] = {}

    def fake_run(application, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

    monkeypatch.setattr(runner.uvicorn, "run", fake_run)
    monkeypatch.setattr(
        runner,
        "declare",
        lambda: AppDeclaration(
            version=app_settings.app_version, docs_enabled=True, settings=app_settings
        ),
    )
    runner.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == app_settings.port
    assert captured.get("reload", False) is False


def test_lan_launcher_binds_the_chosen_interface_and_never_reloads(
    app_settings, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import app.__main__ as runner

    lan = _lan_settings(app_settings)
    captured: dict[str, object] = {}

    def fake_run(application, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

    monkeypatch.setattr(runner.uvicorn, "run", fake_run)
    monkeypatch.setattr(
        runner,
        "declare",
        lambda: AppDeclaration(version=lan.app_version, docs_enabled=False, settings=lan),
    )
    runner.main()

    assert captured["host"] == SELECTED_IP
    assert captured["port"] == lan.port
    assert captured.get("reload", False) is False


def test_lan_mode_disables_docs_and_debug(app_settings) -> None:  # type: ignore[no-untyped-def]
    lan = _lan_settings(app_settings)
    declaration = declare(lan)
    assert declaration.docs_enabled is False
    app = create_app(declaration=declaration, pairing_display=lambda _url: None)
    assert app.docs_url is None
    assert app.openapi_url is None
    assert app.redoc_url is None
    assert app.debug is False

    normal = create_app(
        declaration=declare(app_settings), pairing_display=lambda _url: None
    )
    assert normal.docs_url == "/docs"
    assert normal.openapi_url == "/openapi.json"


def test_lan_requests_only_use_the_selected_host_and_lose_the_docs(
    app_settings,
) -> None:  # type: ignore[no-untyped-def]
    lan = _lan_settings(app_settings)
    port = lan.port
    with access_env(lan, host=SELECTED_IP, client=PHONE_CLIENT) as env:
        pair(env.client)
        assert env.client.get("/api/v1/runtime").status_code == 200
        assert env.app.debug is False

        assert env.client.get("/docs").status_code == 404
        assert env.client.get("/openapi.json").status_code == 404

        other_host = f"192.168.1.99:{port}"
        assert_problem(
            env.client.get(
                "/api/v1/runtime",
                headers={"Host": other_host, "Origin": f"http://{other_host}"},
            ),
            403,
            "forbidden_host",
        )
        assert_problem(
            env.client.get(
                "/api/v1/runtime",
                headers={"Origin": f"http://192.168.1.99:{port}"},
            ),
            403,
            "forbidden_origin",
        )


def test_lan_credentials_changes_are_loopback_only(
    app_settings,
) -> None:  # type: ignore[no-untyped-def]
    lan = _lan_settings(app_settings)
    with access_env(lan, host=SELECTED_IP, client=PHONE_CLIENT) as env:
        pair(env.client)
        put = env.client.put(
            "/api/v1/credentials/llm", json={"api_key": "sk-" + "a" * 24}
        )
        assert_problem(put, 403, "loopback_only")

        delete = env.client.delete("/api/v1/credentials/llm")
        assert_problem(delete, 403, "loopback_only")


def test_lan_csrf_reload_without_optional_browser_headers(app_settings, monkeypatch) -> None:
    lan = _lan_settings(app_settings)
    with access_env(lan, host=SELECTED_IP, client=PHONE_CLIENT) as env:
        token = pair(env.client)
        env.client.headers.pop("Origin")
        env.client.headers.pop("X-CSRF-Token")
        response = env.client.get("/api/v1/session/csrf")
        assert response.status_code == 200, response.text
        assert response.json()["csrf_token"] == token
        assert "access-control-allow-origin" not in response.headers

        for headers in (
            {"Origin": "http://evil.invalid"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
        ):
            assert_problem(
                env.client.get("/api/v1/session/csrf", headers=headers),
                403,
                "forbidden_origin",
            )

        _, calls = install_draft_submit(monkeypatch, env.app)
        env.client.headers["Origin"] = str(env.client.base_url).rstrip("/")
        env.client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        edited = env.client.post(
            "/api/v1/videos/v_0par6gpzwz995r49419ne1gwxd/draft",
            json={"base_revision": 1, "message": "hello", "card_id": None},
        )
        assert edited.status_code == 202, edited.text
        assert len(calls) == 1
