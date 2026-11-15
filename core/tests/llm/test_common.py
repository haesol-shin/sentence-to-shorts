from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.llm import common
from app.llm.common import BaseLlm, ProviderError, ProviderReply
from app.ports import AppError, Cancelled, LlmPart


class Clock:
    now = 100.0

    def monotonic(self):
        return self.now


class Token:
    def __init__(self, clock, *, cancel_after=None):
        self.clock = clock
        self.cancel_after = cancel_after
        self.waits = []
        self.cancelled = False

    def is_set(self):
        return self.cancelled

    def raise_if_set(self):
        if self.cancelled:
            raise Cancelled()

    def wait(self, seconds):
        self.waits.append(seconds)
        self.clock.now += seconds
        self.cancelled = self.cancel_after is not None and self.clock.now >= self.cancel_after
        return self.cancelled


class SequenceLlm(BaseLlm):
    provider = "openai_compat"

    def __init__(self, settings, outcomes):
        super().__init__(settings)
        self.outcomes = iter(outcomes)
        self.calls = []

    def _invoke(self, req, route, **kwargs):
        self.calls.append((req, route, kwargs))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(common, "time", SimpleNamespace(monotonic=value.monotonic, time=lambda: 0))
    return value


@pytest.mark.parametrize("code,count", [
    ("llm_auth", 1), ("llm_quota", 1), ("llm_refused", 1),
    ("llm_timeout", 2), ("llm_connection", 3), ("llm_rate_limited", 3),
])
def test_10_3_error_retry_budgets(settings, request_data, clock, code, count):
    adapter = SequenceLlm(settings, [ProviderError(code)] * 4)
    token = Token(clock)
    with pytest.raises(AppError) as caught:
        adapter.complete(request_data, cancel=token, deadline=150)
    assert caught.value.code == code
    assert len(adapter.calls) == count
    assert all(delay <= 0.25 for delay in token.waits)
    assert all(call[1].model == "small-synthetic" for call in adapter.calls)


def test_10_3_backoff_doubles_and_records_usage(settings, request_data, clock):
    adapter = SequenceLlm(settings, [ProviderError("llm_connection"),
                                   ProviderError("llm_connection"),
                                   ProviderReply('{"answer":"성공"}', "actual-model", 3, 4, 0)])
    token = Token(clock)
    result = adapter.complete(request_data, cancel=token, deadline=150)
    assert sum(token.waits) == 3
    assert result.usage.retries == 2
    assert result.usage.wall_ms == 3000
    assert result.usage.model == "actual-model"
    assert result.usage.effort == "low"
    assert result.usage.cost_usd is None


def test_10_3_retry_after_wait_cancels_within_quarter_second(settings, request_data, clock):
    adapter = SequenceLlm(settings, [ProviderError("llm_rate_limited", retry_after=120)])
    token = Token(clock, cancel_after=100.5)
    with pytest.raises(Cancelled):
        adapter.complete(request_data, cancel=token, deadline=300)
    assert token.waits == [0.25, 0.25]
    assert len(adapter.calls) == 1


def test_10_3_retry_after_cannot_overrun_deadline(settings, request_data, clock):
    adapter = SequenceLlm(settings, [ProviderError("llm_rate_limited", retry_after=20)])
    with pytest.raises(AppError, match="deadline_exceeded"):
        adapter.complete(request_data, cancel=Token(clock), deadline=100.5)
    assert len(adapter.calls) == 1


def test_10_3_timeout_is_clamped_to_remaining_deadline(settings, request_data, clock):
    adapter = SequenceLlm(settings, [ProviderReply('{"answer":"ok"}', "actual")])
    adapter.complete(request_data, cancel=Token(clock), deadline=103)
    assert adapter.calls[0][2]["timeout"] == 3


def test_10_3_schema_repair_is_once_and_keeps_untrusted_output_in_data(
    settings, request_data, clock,
):
    adapter = SequenceLlm(settings, [ProviderReply('{"answer":7}', "actual", 2, 3, None),
                                   ProviderReply('{"answer":"수정"}', "actual", 4, 5, None)])
    result = adapter.complete(request_data, cancel=Token(clock), deadline=150)
    assert result.parsed == {"answer": "수정"}
    repair = adapter.calls[1][0]
    assert repair.system == request_data.system
    assert repair.parts[:-1] == request_data.parts
    assert "type" in repair.parts[-1].text
    assert '{"answer":7}' in repair.parts[-1].text
    assert result.usage.input_tokens == 6
    assert result.usage.output_tokens == 8
    assert result.usage.cache_read_tokens is None
    assert result.usage.retries == 1


def test_10_3_second_invalid_output_fails_without_third_call(settings, request_data, clock):
    adapter = SequenceLlm(settings, [ProviderReply("secret-invalid", "actual")] * 3)
    with pytest.raises(AppError) as caught:
        adapter.complete(request_data, cancel=Token(clock), deadline=150)
    assert caught.value.code == "llm_invalid_output"
    assert "secret-invalid" not in str(caught.value)
    assert len(adapter.calls) == 2


def test_10_3_cancelled_late_reply_is_not_adopted(settings, request_data, clock):
    token = Token(clock)

    class Late(SequenceLlm):
        def _invoke(self, *args, **kwargs):
            token.cancelled = True
            return ProviderReply('{"answer":"late"}', "actual")

    with pytest.raises(Cancelled):
        Late(settings, []).complete(request_data, cancel=token, deadline=150)


def test_10_3_mixed_errors_share_configured_retry_budget(settings, request_data, clock):
    adapter = SequenceLlm(settings, [ProviderError("llm_connection"),
                                   ProviderError("llm_rate_limited", retry_after=0),
                                   ProviderError("llm_timeout")])
    with pytest.raises(AppError, match="llm_timeout"):
        adapter.complete(request_data, cancel=Token(clock), deadline=150)
    assert len(adapter.calls) == 3


def test_10_1_excess_frames_refused_before_call(settings, request_data, clock):
    adapter = SequenceLlm(settings, [])
    request = replace(request_data, parts=[LlmPart("png", png=b"synthetic")] * 9)
    with pytest.raises(AppError, match="llm_refused"):
        adapter.complete(request, cancel=Token(clock), deadline=150)
    assert adapter.calls == []


def test_10_2_unknown_route_never_guesses_from_prompt(settings, request_data, clock):
    adapter = SequenceLlm(settings, [])
    with pytest.raises(AppError, match="llm_invalid_output"):
        adapter.complete(replace(request_data, route="missing"),
                         cancel=Token(clock), deadline=150)
    assert adapter.calls == []


@pytest.mark.parametrize("value,expected", [("2", 2), ("-1", 0), ("NaN", None),
                                            ("invalid", None),
                                            ("Thu, 01 Jan 1970 00:00:03 GMT", 3)])
def test_10_3_retry_after_delta_and_date(value, expected, clock):
    assert common.retry_after_seconds(value) == expected


@pytest.mark.parametrize("status", [500, 502, 503, 504, 529])
def test_10_3_all_server_failures_are_connection_errors(status):
    assert common.status_error(status).code == "llm_connection"


def test_10_3_zero_configured_retries_disables_retry(settings, request_data, clock):
    settings.models.routes["draft"].retries = 0
    adapter = SequenceLlm(settings, [ProviderError("llm_connection")])
    with pytest.raises(AppError, match="llm_connection"):
        adapter.complete(request_data, cancel=Token(clock), deadline=150)
    assert len(adapter.calls) == 1
