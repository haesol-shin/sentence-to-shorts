"""Every non-public route needs a session; Host, Origin and CSRF are exact."""

from __future__ import annotations

import re

import pytest

from tests.access.support import (
    AccessEnv,
    assert_problem,
    assert_security_headers,
    install_draft_submit,
)
from tests.conftest import pair

DRAFT_PATH = "/api/v1/videos/v_0par6gpzwz995r49419ne1gwxd/draft"
DRAFT_BODY = {"base_revision": 1, "message": "hello", "card_id": None}
PUBLIC = {("GET", "/api/v1/health"), ("POST", "/api/v1/session/pair")}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def test_all_non_public_routes_require_a_session(env: AccessEnv) -> None:
    document = env.app.openapi()
    checked: list[tuple[str, str]] = []
    for path, operations in document["paths"].items():
        for raw_method, operation in operations.items():
            method = raw_method.upper()
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            if (method, path) in PUBLIC:
                continue
            assert isinstance(operation, dict)
            headers = {"Range": "bytes=0-1"} if "artifacts" in path else {}
            response = env.client.request(method, _concrete(path), headers=headers)
            assert_problem(response, 401, "unauthenticated")
            checked.append((method, path))
    assert len(checked) >= 20


def test_artifact_range_needs_a_session_then_serves_the_range(
    env: AccessEnv, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    artifact = tmp_path / "clip.mp4"
    artifact.write_bytes(b"0123456789")
    monkeypatch.setattr(  # type: ignore[attr-defined]
        env.app.state.runtime.artifact_store, "path", lambda _aid: artifact
    )

    denied = env.client.get("/api/v1/artifacts/a_x", headers={"Range": "bytes=2-5"})
    assert_problem(denied, 401, "unauthenticated")

    pair(env.client)
    allowed = env.client.get("/api/v1/artifacts/a_x", headers={"Range": "bytes=2-5"})
    assert allowed.status_code == 206
    assert allowed.content == b"2345"
    assert allowed.headers["content-range"] == "bytes 2-5/10"
    assert_security_headers(allowed)


def test_health_and_pair_are_public_but_host_is_still_checked(env: AccessEnv) -> None:
    port = env.settings.port
    health = env.client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["profile"] == "fixture"
    assert_security_headers(health)

    invalid = env.client.post("/api/v1/session/pair", json={"code": "A" * 32})
    assert_problem(invalid, 401, "pair_invalid")
    assert "set-cookie" not in invalid.headers

    wrong_host = env.client.get(
        "/api/v1/health",
        headers={"Host": f"evil.invalid:{port}", "Origin": f"http://evil.invalid:{port}"},
    )
    assert_problem(wrong_host, 403, "forbidden_host")


@pytest.mark.parametrize("hostname", ["evil.invalid", "192.168.1.20", "0.0.0.0"])
def test_unlisted_hosts_are_rejected(env: AccessEnv, hostname: str) -> None:
    port = env.settings.port
    host = f"{hostname}:{port}"
    response = env.client.get(
        "/api/v1/health", headers={"Host": host, "Origin": f"http://{host}"}
    )
    assert_problem(response, 403, "forbidden_host")


def test_a_loopback_name_on_the_wrong_port_is_rejected(env: AccessEnv) -> None:
    other = env.settings.port + 1
    response = env.client.get(
        "/api/v1/health",
        headers={"Host": f"127.0.0.1:{other}", "Origin": f"http://127.0.0.1:{other}"},
    )
    assert_problem(response, 403, "forbidden_host")


@pytest.mark.parametrize("hostname", ["127.0.0.1", "localhost", "[::1]"])
def test_loopback_host_names_are_allowed(env: AccessEnv, hostname: str) -> None:
    port = env.settings.port
    host = f"{hostname}:{port}"
    response = env.client.get(
        "/api/v1/health", headers={"Host": host, "Origin": f"http://{host}"}
    )
    assert response.status_code == 200, response.text
    assert_security_headers(response)


def test_mutations_need_the_exact_origin(
    env: AccessEnv, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    install_draft_submit(monkeypatch, env.app)
    pair(env.client)
    port = env.settings.port

    saved = env.client.headers.pop("Origin")
    try:
        missing = env.client.post(DRAFT_PATH, json=DRAFT_BODY)
    finally:
        env.client.headers["Origin"] = saved
    assert_problem(missing, 403, "forbidden_origin")

    for origin in (
        "null",
        f"https://127.0.0.1:{port}",
        f"http://127.0.0.1:{port + 1}",
        f"http://localhost:{port}",
        f"http://evil.invalid:{port}",
    ):
        response = env.client.post(DRAFT_PATH, json=DRAFT_BODY, headers={"Origin": origin})
        assert_problem(response, 403, "forbidden_origin")
        assert response.json()["code"] == "forbidden_origin"

    accepted = env.client.post(DRAFT_PATH, json=DRAFT_BODY)
    assert accepted.status_code == 202, accepted.text


def test_mutations_need_the_session_csrf_token(
    env: AccessEnv, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    install_draft_submit(monkeypatch, env.app)
    token = pair(env.client)

    saved = env.client.headers.pop("X-CSRF-Token")
    try:
        missing = env.client.post(DRAFT_PATH, json=DRAFT_BODY)
    finally:
        env.client.headers["X-CSRF-Token"] = saved
    assert_problem(missing, 403, "csrf_failed")

    for bad in ("x" * 32, ""):
        response = env.client.post(
            DRAFT_PATH, json=DRAFT_BODY, headers={"X-CSRF-Token": bad}
        )
        assert_problem(response, 403, "csrf_failed")

    accepted = env.client.post(DRAFT_PATH, json=DRAFT_BODY)
    assert accepted.status_code == 202, accepted.text

    # A token belongs to one session: a later pairing rotates both.
    second = pair(env.client)
    assert second != token
    env.client.headers["X-CSRF-Token"] = token
    stale = env.client.post(DRAFT_PATH, json=DRAFT_BODY)
    assert_problem(stale, 403, "csrf_failed")
    env.client.headers["X-CSRF-Token"] = second
    assert env.client.post(DRAFT_PATH, json=DRAFT_BODY).status_code == 202


def test_duplicate_single_value_headers_are_rejected(env: AccessEnv) -> None:
    origin = env.client.headers["Origin"]
    response = env.client.get(
        "/api/v1/health", headers=[("Origin", origin), ("Origin", origin)]
    )
    assert_problem(response, 422, "validation_failed")


def test_tampered_or_missing_session_cookie_is_rejected(env: AccessEnv) -> None:
    pair(env.client)
    env.client.cookies.clear()
    assert_problem(env.client.get("/api/v1/runtime"), 401, "unauthenticated")

    env.client.cookies.set(
        f"session_{env.settings.port}", "not-a-session", domain="127.0.0.1", path="/"
    )
    assert_problem(env.client.get("/api/v1/runtime"), 401, "unauthenticated")
