from __future__ import annotations

import io
import json
import time
import traceback
import urllib.error
from dataclasses import replace

import pytest

from app.llm.credentials import Credentials
from app.llm.providers.openai_compat.adapter import OpenAiCompatLlm
from app.ports import AppError, LlmPart, LlmTask


def response(text='{"answer":"합성"}', **extra):
    return {"model": "actual-synthetic", "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7,
                      "prompt_tokens_details": {"cached_tokens": 2}}, **extra}


class Opener:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(json.dumps(outcome, ensure_ascii=False).encode())


def credentials(value=None):
    source = Credentials("synthetic.invalid", "openai", backend_factory=lambda: None)
    if value:
        source.set(value)
    return source


def adapter(settings, outcomes, **kwargs):
    transport = Opener(outcomes)
    value = OpenAiCompatLlm(settings, base_url="https://api.invalid/v1", opener=transport,
                           credentials=kwargs.pop("credentials", credentials()), **kwargs)
    return value, transport


@pytest.mark.parametrize("key", [None, "synthetic-key"])
def test_10_1_optional_key_and_usage(settings, request_data, cancel, key):
    llm, transport = adapter(settings, [response()], credentials=credentials(key))
    assert llm.auth_state() == "unknown"
    result = llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    sent = transport.calls[0][0]
    assert sent.full_url == "https://api.invalid/v1/chat/completions"
    assert sent.get_header("Authorization") == (f"Bearer {key}" if key else None)
    assert result.parsed == {"answer": "합성"}
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 7
    assert result.usage.cache_read_tokens == 2
    assert result.usage.model == "actual-synthetic"
    assert llm.auth_state() == "ok"


@pytest.mark.parametrize("route,model,effort", [
    ("draft", "small-synthetic", "low"), ("script.default", "large-synthetic", "medium"),
])
def test_10_2_alias_model_and_structured_output(
    settings, request_data, cancel, route, model, effort,
):
    llm, transport = adapter(settings, [response()])
    llm.complete(replace(request_data, route=route), cancel=cancel, deadline=time.monotonic() + 10)
    sent = json.loads(transport.calls[0][0].data)
    assert sent["model"] == model
    assert sent["reasoning_effort"] == effort
    assert sent["max_tokens"] == 128
    assert sent["response_format"]["json_schema"]["schema"] == request_data.output_schema
    assert sent["messages"][0] == {"role": "system", "content": request_data.system}
    assert sent["messages"][1]["content"][0]["text"] == request_data.parts[0].text
    assert "tools" not in sent


def test_10_1_png_is_image_url_data_part(settings, request_data, cancel):
    llm, transport = adapter(settings, [response()])
    request = replace(request_data, task=LlmTask.reference_vision, route="reference_vision",
                      parts=[LlmPart("png", png=b"synthetic-png")])
    llm.complete(request, cancel=cancel, deadline=time.monotonic() + 10)
    part = json.loads(transport.calls[0][0].data)["messages"][1]["content"][0]
    assert part == {"type": "image_url", "image_url": {
        "url": "data:image/png;base64,c3ludGhldGljLXBuZw=="}}


def http_error(status, body=None, headers=None):
    return urllib.error.HTTPError("https://api.invalid", status, "synthetic", headers or {},
                                  io.BytesIO(json.dumps(body or {}).encode()))


def test_10_1_image_endpoint_rejection_is_refused(settings, request_data, cancel):
    llm, transport = adapter(settings, [http_error(400)])
    request = replace(request_data, task=LlmTask.reference_vision, route="reference_vision",
                      parts=[LlmPart("png", png=b"synthetic")])
    with pytest.raises(AppError, match="llm_refused"):
        llm.complete(request, cancel=cancel, deadline=time.monotonic() + 10)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status,body,code", [
    (401, {}, "llm_auth"), (403, {}, "llm_auth"),
    (429, {"error": {"code": "insufficient_quota"}}, "llm_quota"),
    (402, {}, "llm_quota"), (400, {}, "llm_refused"),
])
def test_10_3_provider_errors_are_sanitized(
    settings, request_data, cancel, caplog, status, body, code,
):
    body["private"] = "synthetic-key-secret-prompt"
    llm, transport = adapter(settings, [http_error(status, body)],
                             credentials=credentials("synthetic-key-secret"))
    with pytest.raises(AppError) as caught:
        llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert caught.value.code == code
    trace = "".join(traceback.format_exception(caught.value))
    assert "synthetic-key-secret" not in trace + caplog.text
    assert "secret-prompt" not in trace + caplog.text
    assert len(transport.calls) == 1


def test_10_3_http_rate_limit_uses_retry_after(settings, request_data, cancel, monkeypatch):
    from app.llm import common
    waits = []
    monkeypatch.setattr(common, "wait_active", lambda delay, **kwargs: waits.append(delay))
    llm, transport = adapter(settings, [http_error(429, headers={"Retry-After": "2"}), response()])
    result = llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert waits == [2]
    assert len(transport.calls) == 2
    assert result.usage.retries == 1


def test_10_3_http_schema_error_gets_one_repair(settings, request_data, cancel):
    llm, transport = adapter(settings, [response('{"answer":2}'), response()])
    llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    repaired = json.loads(transport.calls[1][0].data)
    assert len(repaired["messages"][1]["content"]) == 2
    assert "Validation error: type" in repaired["messages"][1]["content"][-1]["text"]


@pytest.mark.parametrize("message", [{"refusal": "refused", "content": None},
                                     {"tool_calls": [{"name": "shell"}], "content": "text"}])
def test_10_4_tool_or_refusal_response_is_not_adopted(settings, request_data, cancel, message):
    llm, _ = adapter(settings, [response(choices=[{"message": message}])])
    with pytest.raises(AppError, match="llm_refused"):
        llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)


def test_10_1_unknown_usage_remains_unknown(settings, request_data, cancel):
    llm, _ = adapter(settings, [response(usage=None)])
    result = llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.cost_usd is None


def test_10_1_required_missing_key_prevents_http(settings, request_data, cancel):
    llm, transport = adapter(settings, [], key_required=True)
    assert llm.auth_state() == "missing"
    with pytest.raises(AppError, match="llm_auth"):
        llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert transport.calls == []


def test_10_1_only_configured_key_environment_is_used(settings, request_data, cancel, monkeypatch):
    monkeypatch.setenv("UNRELATED_API_KEY", "unrelated-secret")
    monkeypatch.setenv("SYNTHETIC_ENDPOINT_KEY", "selected-key")
    transport = Opener([response()])
    llm = OpenAiCompatLlm(settings, base_url="https://api.invalid/v1",
                          opener=transport, key_env="SYNTHETIC_ENDPOINT_KEY")
    llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert transport.calls[0][0].get_header("Authorization") == "Bearer selected-key"


def test_10_1_auth_failure_after_success_reports_expired(settings, request_data, cancel):
    llm, transport = adapter(settings, [response(), http_error(401)])
    llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    with pytest.raises(AppError, match="llm_auth"):
        llm.complete(request_data, cancel=cancel, deadline=time.monotonic() + 10)
    assert llm.auth_state() == "expired"
    assert len(transport.calls) == 2
