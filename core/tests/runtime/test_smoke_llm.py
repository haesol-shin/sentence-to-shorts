"""The smoke's recorded LLM endpoint: it repeats the fixture adapter's id rules on the wire."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

from app.llm.common import ResolvedRoute
from app.llm.providers.fixture import adapter as fixture
from app.llm.providers.openai_compat.adapter import _request_payload
from app.ports import LlmPart, LlmRequest, LlmTask

REPO = Path(__file__).resolve().parents[3]
RECORDINGS = sorted((REPO / "fixtures" / "llm").glob("*/*.json"))
ROUTE = ResolvedRoute("recorded", "low", 60.0, 0)


def load_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "packaging" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stub_module = load_module("smoke_llm")


def request_of(path: Path) -> tuple[dict[str, Any], LlmRequest]:
    data = json.loads(path.read_text(encoding="utf-8"))
    record = data["request"]
    parts = [LlmPart(kind=p["kind"], text=p.get("text")) for p in record["parts"]]
    request = LlmRequest(
        task=LlmTask(record["task"]), route=record["route"], system=record["system"],
        parts=parts, output_schema=record["output_schema"],
        max_output_tokens=record["max_output_tokens"],
    )
    return data, request


def new_id(old: str, number: int) -> str:
    return f"{old.split('_')[0]}_{'0' * 24}{number:02d}"


def test_21_recordings_exist_and_none_carries_an_image() -> None:
    assert RECORDINGS
    for path in RECORDINGS:
        record = json.loads(path.read_text(encoding="utf-8"))["request"]
        assert all(part["kind"] == "text" for part in record["parts"]), path.name


def test_21_stub_id_rules_equal_the_fixture_adapter_over_every_recording() -> None:
    for path in RECORDINGS:
        data, request = request_of(path)
        texts = [part.text for part in request.parts]
        order = fixture._id_order(texts)
        assert stub_module.id_order(texts) == order, path
        mapping = {old: new_id(old, number) for number, old in enumerate(order)}
        for text in texts:
            assert text is not None
            assert stub_module.name_ids(text, order) == fixture._name_ids(text, order)
            assert stub_module.bind_ids(text, mapping) == fixture._bind_text(text, mapping)
        assert fixture.request_digest(request) == path.stem
        assert data["task"] == request.task.value


def test_21_stub_keys_collide_only_between_synthetic_recordings_of_different_tasks() -> None:
    recordings = stub_module.load_recordings(stub_module.FIXTURE_ROOT)
    groups: dict[str, list[Any]] = {}
    for recording in recordings:
        groups.setdefault(recording.key, []).append(recording)
    for group in groups.values():
        if len(group) > 1:
            assert len({item.task for item in group}) == len(group)
            assert all(item.system.startswith("Synthetic fixture prompt") for item in group)
    for path, recording in zip(RECORDINGS, recordings, strict=True):
        _data, request = request_of(path)
        system, parts, schema = stub_module.wire_parts(_request_payload(request, ROUTE))
        key, _order = stub_module.wire_key(system, parts, schema)
        assert key == recording.key, path


def test_21_stub_answers_every_recording_with_live_ids_bound_into_the_text() -> None:
    stub = stub_module.RecordedLlm()
    served = 0
    for path in RECORDINGS:
        data, request = request_of(path)
        order = fixture._id_order(part.text for part in request.parts)
        mapping = {old: new_id(old, number) for number, old in enumerate(order)}
        live = LlmRequest(
            task=request.task, route=request.route, system=request.system,
            parts=[
                LlmPart(kind="text", text=stub_module.bind_ids(part.text or "", mapping))
                for part in request.parts
            ],
            output_schema=request.output_schema, max_output_tokens=request.max_output_tokens,
        )
        status, body = stub.answer(_request_payload(live, ROUTE))
        shared = stub.by_key[stub_module.recorded_key(data["request"])]
        if len(shared) > 1:
            assert status == 400 and "ambiguous" in body["error"]["message"]
            continue
        assert status == 200, (path, body)
        choice = body["choices"][0]
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["content"] == stub_module.bind_ids(data["text"], mapping)
        assert isinstance(body["usage"]["prompt_tokens"], int)
        served += 1
    assert served == len(stub.served) and served > 0
    assert len(stub.unmatched) == len(RECORDINGS) - served


def test_21_stub_serves_over_http_and_refuses_an_unknown_request_without_a_digest() -> None:
    _data, request = request_of(RECORDINGS[0])
    stub = stub_module.start()
    try:
        assert stub.base_url.startswith("http://127.0.0.1:")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def post(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            call = urllib.request.Request(
                f"{stub.base_url}/chat/completions", json.dumps(payload).encode("utf-8"),
                {"Content-Type": "application/json"},
            )
            try:
                with opener.open(call, timeout=10) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as error:
                return error.code, json.loads(error.read())

        status, body = post(_request_payload(request, ROUTE))
        assert status == 200 and body["choices"][0]["message"]["content"]
        unknown = LlmRequest(
            task=request.task, route=request.route, system=request.system,
            parts=[LlmPart(kind="text", text="a request nobody recorded")],
            output_schema=request.output_schema, max_output_tokens=10,
        )
        status, body = post(_request_payload(unknown, ROUTE))
        assert status == 400 and body["error"]["code"] == "smoke_unmatched"
        assert len(stub.unmatched) == 1
        assert request.task.value in stub.unmatched[0]
        assert not re.search(r"[0-9a-f]{32}", stub.unmatched[0])
    finally:
        stub.close()


def test_21_stub_refuses_a_malformed_body() -> None:
    stub = stub_module.RecordedLlm()
    assert stub.answer({"messages": []})[0] == 400
    assert stub.answer({"messages": [{"role": "user", "content": []}] * 2})[0] == 400
    assert len(stub.unmatched) == 2
