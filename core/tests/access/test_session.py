"""Pairing code lifetime, one-use sessions, CSRF and cookie flags."""

from __future__ import annotations

from app.access import PAIR_CODE_TTL_S, PAIR_FAILURE_LIMIT, PAIR_FAILURE_WINDOW_S
from tests.access.support import (
    AccessEnv,
    assert_problem,
    assert_security_headers,
    install_draft_submit,
)
from tests.conftest import pair

PAIR_PATH = "/api/v1/session/pair"
DRAFT_PATH = "/api/v1/videos/v_0par6gpzwz995r49419ne1gwxd/draft"
DRAFT_BODY = {"base_revision": 1, "message": "hello", "card_id": None}


def _pair_with(env: AccessEnv, code: str):
    return env.client.post(PAIR_PATH, json={"code": code})


def test_pairing_sets_a_strict_httponly_session_cookie(env: AccessEnv) -> None:
    port = env.settings.port
    code = env.app.state.runtime.access.issue_pairing_code()
    response = _pair_with(env, code)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile"] == "fixture"
    assert body["deployment"] == "local"
    assert body["ui_language"] == "ko"
    assert len(body["csrf_token"]) >= 32
    assert_security_headers(response)

    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 1
    cookie = cookies[0]
    name = f"session_{port}"
    assert cookie.startswith(f"{name}=")
    assert "Path=/" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Max-Age" not in cookie
    assert "Expires" not in cookie
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    assert env.client.cookies.get(name) == session_value
    assert body["csrf_token"] not in cookie

    assert env.client.get("/api/v1/runtime").status_code == 200


def test_csrf_reload_uses_the_session_cookie_not_persistent_storage(
    env: AccessEnv, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    token = pair(env.client)
    reloaded = env.client.get("/api/v1/session/csrf")
    assert reloaded.status_code == 200
    assert reloaded.json()["csrf_token"] == token
    assert_security_headers(reloaded)

    saved = env.client.headers.pop("Origin")
    try:
        # A reloaded tab sends no Origin on GET; Fetch Metadata says same-origin.
        same_origin = env.client.get(
            "/api/v1/session/csrf", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert same_origin.status_code == 200
        assert same_origin.json()["csrf_token"] == token

        unknown = env.client.get("/api/v1/session/csrf")
        assert unknown.status_code == 200
        assert unknown.json()["csrf_token"] == token
    finally:
        env.client.headers["Origin"] = saved

    other_origin = env.client.get(
        "/api/v1/session/csrf", headers={"Origin": "http://evil.invalid"}
    )
    assert_problem(other_origin, 403, "forbidden_origin")

    install_draft_submit(monkeypatch, env.app)
    accepted = env.client.post(DRAFT_PATH, json=DRAFT_BODY)
    assert accepted.status_code == 202, accepted.text

    env.client.cookies.clear()
    assert_problem(env.client.get("/api/v1/session/csrf"), 401, "unauthenticated")


def test_pairing_codes_expire_after_five_minutes(
    env: AccessEnv, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    assert PAIR_CODE_TTL_S == 300.0
    guard = env.app.state.runtime.access
    clock = [1000.0]
    monkeypatch.setattr(guard, "_clock", lambda: clock[0])

    code = guard.issue_pairing_code()
    clock[0] += PAIR_CODE_TTL_S + 1
    expired = _pair_with(env, code)
    assert_problem(expired, 401, "pair_invalid")
    assert "set-cookie" not in expired.headers

    fresh = guard.issue_pairing_code()
    accepted = _pair_with(env, fresh)
    assert accepted.status_code == 200, accepted.text


def test_pairing_codes_are_single_use_and_replaced(env: AccessEnv) -> None:
    guard = env.app.state.runtime.access
    code = guard.issue_pairing_code()
    first = _pair_with(env, code)
    assert first.status_code == 200

    reused = _pair_with(env, code)
    assert_problem(reused, 401, "pair_invalid")
    # The failed exchange does not sign the paired browser out.
    assert env.client.get("/api/v1/runtime").status_code == 200

    older = guard.issue_pairing_code()
    newer = guard.issue_pairing_code()
    assert_problem(_pair_with(env, older), 401, "pair_invalid")
    assert _pair_with(env, newer).status_code == 200


def test_pairing_failures_are_throttled_and_the_window_resets(
    env: AccessEnv, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    assert PAIR_FAILURE_LIMIT == 5
    assert PAIR_FAILURE_WINDOW_S == 60.0
    guard = env.app.state.runtime.access
    clock = [1000.0]
    monkeypatch.setattr(guard, "_clock", lambda: clock[0])
    code = guard.issue_pairing_code()

    for _ in range(PAIR_FAILURE_LIMIT):
        failed = _pair_with(env, "B" * 32)
        assert_problem(failed, 401, "pair_invalid")
        assert "set-cookie" not in failed.headers

    throttled = _pair_with(env, code)
    body = assert_problem(throttled, 429, "rate_limited")
    assert body["retryable"] is True
    assert "set-cookie" not in throttled.headers

    clock[0] += PAIR_FAILURE_WINDOW_S + 1
    accepted = _pair_with(env, code)
    assert accepted.status_code == 200, accepted.text


def test_pair_request_validation_is_a_problem(env: AccessEnv) -> None:
    response = env.client.post(PAIR_PATH, json={"code": "short"})
    assert_problem(response, 422, "validation_failed")
    assert response.json()["status"] == 422
