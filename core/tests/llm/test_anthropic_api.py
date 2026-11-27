from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import replace

import httpx2
import pytest

from app.jobs import LocalJobContext
from app.llm.providers.anthropic_api.adapter import AnthropicApiLlm
from app.ports import AppError, LlmPart
from tests.llm.conftest import OWNER, FakeResolver

DEADLINE = time.monotonic() + 3600


def message(text='{"answer":"합성"}', **extra):
    return {"id": "msg_synthetic", "type": "message", "role": "assistant",
            "model": "claude-synthetic-actual", "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 13, "output_tokens": 5, "cache_read_input_tokens": 3,
                      "cache_creation_input_tokens": 4},
            **extra}


def adapter(settings, outcomes, key="synthetic-os-key"):
    source = FakeResolver(key)
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


def test_10_1_official_sdk_structured_png_and_usage(
    settings, request_data, cancel, monkeypatch, tmp_path,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ignored-env-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ignored-oauth")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://ignored.invalid")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS",
                       "Authorization: Bearer ignored-header-key\nx-api-key: ignored-header-key")
    llm, calls = adapter(settings, [(200, message(), {})])
    request = replace(request_data, parts=[*request_data.parts, LlmPart("png", png=b"synthetic")])
    usage_records, events = [], []
    ctx = LocalJobContext(
        cancel, DEADLINE, tmp_path, owner_id=OWNER,
        job_id="j_01jdq7c3v8m4n5p6q7r8s9t0vw",
        on_usage=usage_records.append, on_request=events.append,
    )
    result = llm.complete(
        request, owner_id=OWNER, cancel=cancel, deadline=DEADLINE, on_request=ctx.record_request,
    )
    ctx.record_usage(result.usage)
    assert str(calls[0].url) == "https://api.anthropic.com/v1/messages"
    assert calls[0].headers["x-api-key"] == "synthetic-os-key"
    assert "authorization" not in calls[0].headers
    payload = json.loads(calls[0].content)
    assert payload["model"] == "claude-haiku-5-5"
    assert payload["output_config"]["effort"] == "low"
    assert payload["system"] == [
        {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}},
    ]
    assert "cache_control" not in payload
    assert payload["messages"][0]["content"][0] == {
        "type": "text", "text": request.parts[0].text,
    }
    assert payload["messages"][0]["content"][1] == {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": "c3ludGhldGlj"}}
    assert "tools" not in payload
    assert result.parsed == {"answer": "합성"}
    assert result.usage.input_tokens == 13
    snapshot, = usage_records
    event, = events
    assert (snapshot.cache_read_tokens, snapshot.cache_write_tokens) == (3, 4)
    assert (event.cache_read_tokens, event.cache_write_tokens) == (3, 4)
    assert result.usage.model == "claude-synthetic-actual"
    assert llm.auth_state(OWNER) == "ok"


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
        llm.complete(request_data, owner_id=OWNER, cancel=cancel, deadline=DEADLINE)
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
    result = llm.complete(request_data, owner_id=OWNER, cancel=cancel, deadline=DEADLINE)
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
        llm.complete(request_data, owner_id=OWNER, cancel=cancel, deadline=DEADLINE)
    assert len(calls) == count


def test_10_3_schema_transform_keeps_original_response_validation(settings, request_data, cancel):
    schema = {**request_data.output_schema, "properties": {
        "answer": {"type": "string", "minLength": 2},
    }}
    request = replace(request_data, output_schema=schema)
    llm, calls = adapter(settings, [(200, message('{"answer":"가"}'), {}), (200, message(), {})])
    result = llm.complete(request, owner_id=OWNER, cancel=cancel, deadline=DEADLINE)
    assert len(calls) == 2
    first, repair = (json.loads(call.content) for call in calls)
    assert repair["system"] == first["system"]
    assert repair["output_config"] == first["output_config"]
    for call in calls:
        output_format = json.loads(call.content)["output_config"]["format"]
        assert output_format["type"] == "json_schema"
        assert "minLength" not in output_format["schema"]["properties"]["answer"]
    assert 'Validation error: minLength' in repair["messages"][0]["content"][-1]["text"]
    assert schema["properties"]["answer"]["minLength"] == 2
    assert result.parsed == {"answer": "합성"}
    assert result.usage.input_tokens == 26
    assert result.usage.cache_read_tokens == 6
    assert result.usage.cache_write_tokens == 8


def test_scene_data_caches_only_through_the_video_context(settings, request_data, cancel):
    settings.models.routes["scene_data"] = settings.models.routes["draft"]
    llm, calls = adapter(settings, [(200, message(), {})] * 2)
    shared = LlmPart("text", text='{"allowed":["synthetic"]}')
    for scene in ("first", "second"):
        request = replace(request_data, route="scene_data", parts=[
            shared, LlmPart("text", text=scene),
        ])
        llm.complete(request, owner_id=OWNER, cancel=cancel, deadline=DEADLINE)

    for call, scene in zip(calls, ("first", "second"), strict=True):
        payload = json.loads(call.content)
        assert "cache_control" not in payload
        assert payload["system"] == [{"type": "text", "text": request_data.system}]
        assert payload["messages"][0]["content"] == [
            {"type": "text", "text": shared.text, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": scene},
        ]


def test_10_3_sdk_refusal_is_not_retried(settings, request_data, cancel):
    llm, calls = adapter(settings, [(200, message(stop_reason="refusal"), {})])
    with pytest.raises(AppError, match="llm_refused"):
        llm.complete(request_data, owner_id=OWNER, cancel=cancel, deadline=DEADLINE)
    assert len(calls) == 1


def test_10_1_missing_os_key_does_not_use_env_or_call(settings, request_data, cancel, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unconfigured-env-key")
    llm, calls = adapter(settings, [], key=None)
    assert llm.auth_state(OWNER) == "missing"
    with pytest.raises(AppError, match="llm_auth"):
        llm.complete(request_data, owner_id=OWNER, cancel=cancel, deadline=DEADLINE)
    assert calls == []


def test_llm_call_uses_job_owner_key(settings, request_data, cancel):
    first_owner = "u_0hzb7bexv28termtt2ypc6trzt"
    second_owner = "u_08c71zekrt8ceaqnmy5jjy5zv"
    resolver = FakeResolver(None)
    resolver.set("first-owner-key", first_owner, "k_0hzb7bexv28termtt2ypc6trzt")
    resolver.set("second-owner-key", second_owner, "k_08c71zekrt8ceaqnmy5jjy5zv")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(200, json=message(), headers={})

    llm = AnthropicApiLlm(
        settings,
        credentials=resolver,
        http_transport=httpx2.MockTransport(handler),
    )
    llm.complete(request_data, owner_id=first_owner, cancel=cancel, deadline=DEADLINE)
    llm.complete(request_data, owner_id=second_owner, cancel=cancel, deadline=DEADLINE)
    assert [call.headers["x-api-key"] for call in calls] == [
        "first-owner-key",
        "second-owner-key",
    ]
