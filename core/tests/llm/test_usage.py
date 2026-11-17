"""Every provider request is reported, including retries and failures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm import common
from app.llm.common import BaseLlm, ProviderError, ProviderReply
from app.ports import AppError, Cancelled, LlmPart, LlmRequest, LlmTask, ProviderRequest
from tests.llm.conftest import CREDENTIAL_ID, OWNER, FakeResolver

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class Clock:
    now = 100.0

    def monotonic(self):
        return self.now


class Token:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.cancelled = False

    def is_set(self) -> bool:
        return self.cancelled

    def raise_if_set(self) -> None:
        if self.cancelled:
            raise Cancelled()

    def wait(self, seconds: float) -> bool:
        self.clock.now += seconds
        return self.cancelled


class SequenceLlm(BaseLlm):
    provider = "openai_compat"

    def __init__(self, settings, outcomes, *, credentials=None, developer_key=None):
        super().__init__(settings, credentials=credentials)
        self.outcomes = iter(outcomes)
        self.developer_key = developer_key

    def _developer_key(self):
        return self.developer_key

    def _invoke(self, req, route, **kwargs):
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(
        common, "time", SimpleNamespace(monotonic=value.monotonic, time=lambda: 0)
    )
    return value


@pytest.fixture
def request_data():
    return LlmRequest(
        LlmTask.draft,
        "draft",
        "Return the requested object.",
        [LlmPart("text", text="합성 주제")],
        SCHEMA,
        128,
    )


def collect(adapter, request_data, clock):
    events: list[ProviderRequest] = []
    adapter.complete(
        request_data,
        owner_id=OWNER,
        cancel=Token(clock),
        deadline=200,
        on_request=events.append,
    )
    return events


def test_usage_event_per_try(settings, request_data, clock):
    adapter = SequenceLlm(settings, [
        ProviderError("llm_connection"),
        ProviderReply('{"answer":"ok"}', "actual", 4, 5, 1, 2),
    ])
    events = collect(adapter, request_data, clock)
    assert [event.try_index for event in events] == [0, 1]
    assert [event.outcome for event in events] == ["failed", "ok"]
    assert events[0].stage.value == "llm_draft"
    assert events[0].model == "small-synthetic"
    assert events[1].model == "actual"
    assert (events[1].input_tokens, events[1].output_tokens) == (4, 5)
    assert (events[1].cache_read_tokens, events[1].cache_write_tokens) == (1, 2)


def test_failed_call_records_failed_requests(settings, request_data, clock):
    adapter = SequenceLlm(settings, [ProviderError("llm_connection")] * 3)
    events: list[ProviderRequest] = []
    with pytest.raises(AppError, match="llm_connection"):
        adapter.complete(
            request_data,
            owner_id=OWNER,
            cancel=Token(clock),
            deadline=200,
            on_request=events.append,
        )
    assert len(events) == 3
    assert {event.outcome for event in events} == {"failed"}
    assert [event.try_index for event in events] == [0, 1, 2]
    assert all(event.input_tokens is None for event in events)


def test_usage_event_carries_credential_id(settings, request_data, clock):
    adapter = SequenceLlm(
        settings,
        [ProviderReply('{"answer":"ok"}', "actual")],
        credentials=FakeResolver("synthetic-secret"),
    )
    events = collect(adapter, request_data, clock)
    assert events[0].credential_id == CREDENTIAL_ID

    environment = SequenceLlm(
        settings,
        [ProviderReply('{"answer":"ok"}', "actual")],
        credentials=FakeResolver(None),
        developer_key="synthetic-env-key",
    )
    env_events = collect(environment, request_data, clock)
    assert env_events[0].credential_id is None
