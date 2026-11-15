from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import replace

import httpx2
import pytest

from app.llm.credentials import Credentials
from app.llm.providers.anthropic_api.adapter import AnthropicApiLlm
from app.ports import AppError, LlmPart


def message(text='{"answer":"합성"}', **extra):
    return {"id": "msg_synthetic", "type": "message", "role": "assistant",
            "model": "claude-synthetic-actual", "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 13, "output_tokens": 5, "cache_read_input_tokens": 3},
            **extra}


def adapter(settings, outcomes, key="synthetic-os-key"):
    source = Credentials("synthetic.invalid", "anthropic", backend_factory=lambda: None)
    if key:
        source.set(key)
    calls = []
    pending = iter(outcomes)

    def handler(request):
        calls.append(request)
        outcome = next(pending)
        if isinstance(outcome, Exception):
            raise outcome
        status, body, headers = outcome
        return httpx2.Response(status, json=body, headers=headers)

    llm = AnthropicApiLlm(settings, credentials=source,
                          http_transport=httpx2.MockTransport(handler))
    return llm, calls


def test_10_1_official_sdk_structured_png_and_usage(settings, request_data, cancel, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ignored-env-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ignored-oauth")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://ignored.invalid")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS",
                       "Authorization: Bearer ignored-header-key\nx-api-key: ignored-header-key")
    llm, calls = adapter(settings, [(200, message(), {})])
    request = replace(request_data, parts=[*request_data.parts, LlmPart("png", png=b"synthetic")])
    result = llm.complete(request, cancel=cancel, deadline=time.monotonic() + 10)
    assert str(calls[0].url) == "https://api.anthropic.com/v1/messages"
    assert calls[0].headers["x-api-key"] == "synthetic-os-key"
    assert "authorization" not in calls[0].headers
    payload = json.loads(calls[0].content)
    assert payload["model"] == "claude-haiku-5-5"
    assert payload["output_config"] == {
        "effort": "low", "format": {"type": "json_schema", "schema": request.output_schema}}
    assert payload["system"] == request.system
    assert payload["messages"][0]["content"][1] == {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": "c3ludGhldGlj"}}
    assert "tools" not in payload
    assert result.parsed == {"answer": "합성"}
    assert result.usage.input_tokens == 13
    assert result.usage.cache_read_tokens == 3
    assert result.usage.model == "claude-synthetic-actual"
    assert llm.auth_state() == "ok"


@pytest.mark.parametrize("status,kind,code", [
    (401, "authentication_error", "llm_auth"), (403, "permission_error", "llm_auth"),
    (402, "billing_error", "llm_quota"), (400, "invalid_request_error", "llm_refused"),
])
def test_10_3_sdk_failure_does_not_expose_key_or_body(
    settings, request_data, cancel, caplog, status, kind, code,
):
    caplog.set_level(logging.DEBUG)
    llm, calls = adapter(settings, [(status, {"type": "error", "error": {
        "type": kind, "message": "synthetic-os-key private-provider-body"}}, {})])
    with pytest.raises(AppError) as caught:
        llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert caught.value.code == code
    trace = "".join(traceback.format_exception(caught.value))
    assert "synthetic-os-key" not in trace + caplog.text
    assert "private-provider-body" not in trace + caplog.text
    assert request_data.parts[0].text not in caplog.text
    assert len(calls) == 1


def test_10_3_sdk_retries_are_owned_by_adapter(settings, request_data, cancel, monkeypatch):
    from app.llm import common
    waits = []
    monkeypatch.setattr(common, "wait_active", lambda delay, **kwargs: waits.append(delay))
    llm, calls = adapter(settings, [(429, {"type": "error", "error": {
        "type": "rate_limit_error", "message": "synthetic"}}, {"retry-after": "3"}),
                                  (200, message(), {})])
    result = llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert len(calls) == 2
    assert waits == [3]
    assert result.usage.retries == 1


@pytest.mark.parametrize("error,code,count", [
    (httpx2.ReadTimeout("synthetic"), "llm_timeout", 2),
    (httpx2.ConnectError("synthetic"), "llm_connection", 3),
])
def test_10_3_sdk_timeout_and_connection_mapping(
    settings, request_data, cancel, monkeypatch, error, code, count,
):
    from app.llm import common
    monkeypatch.setattr(common, "wait_active", lambda delay, **kwargs: None)
    llm, calls = adapter(settings, [error] * 4)
    with pytest.raises(AppError, match=code):
        llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert len(calls) == count


def test_10_3_sdk_schema_output_has_one_repair(settings, request_data, cancel):
    llm, calls = adapter(settings, [(200, message('{"answer":4}'), {}), (200, message(), {})])
    result = llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert len(calls) == 2
    repair = json.loads(calls[1].content)
    assert repair["system"] == request_data.system
    assert "Validation error: type" in repair["messages"][0]["content"][-1]["text"]
    assert result.usage.input_tokens == 26


def test_10_3_sdk_refusal_is_not_retried(settings, request_data, cancel):
    llm, calls = adapter(settings, [(200, message(stop_reason="refusal"), {})])
    with pytest.raises(AppError, match="llm_refused"):
        llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert len(calls) == 1


def test_10_1_missing_os_key_does_not_use_env_or_call(settings, request_data, cancel, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unconfigured-env-key")
    llm, calls = adapter(settings, [], key=None)
    assert llm.auth_state() == "missing"
    with pytest.raises(AppError, match="llm_auth"):
        llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert calls == []
