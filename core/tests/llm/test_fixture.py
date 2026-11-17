"""Fixture playback checks for digests, record integrity and schema validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.llm.providers.fixture.adapter import FixtureLlm, request_digest
from app.ports import AppError, LlmPart, LlmRequest, LlmTask, canonical_digest

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class _NotCancelled:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


def _request(**overrides: Any) -> LlmRequest:
    values: dict[str, Any] = {
        "task": LlmTask.scene_data,
        "route": "scene_data",
        "system": "Synthetic fixture prompt.",
        "parts": [LlmPart(kind="text", text="합성 장면 <입력>")],
        "output_schema": None,
        "max_output_tokens": 256,
    }
    values.update(overrides)
    return LlmRequest(**values)


def _request_record(req: LlmRequest) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    for part in req.parts:
        payload: dict[str, Any] = {"kind": part.kind}
        if part.text is not None:
            payload["text"] = part.text
        if part.png is not None:
            payload["png_sha256"] = hashlib.sha256(part.png).hexdigest()
        parts.append(payload)
    return {
        "task": req.task.value,
        "route": req.route,
        "system": req.system,
        "parts": parts,
        "output_schema": req.output_schema,
        "max_output_tokens": req.max_output_tokens,
    }


def _payload(
    req: LlmRequest,
    *,
    text: str = '{"answer": "synthetic"}',
    parsed: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    task: str | None = None,
) -> dict[str, Any]:
    return {
        "task": req.task.value if task is None else task,
        "request": _request_record(req) if request is None else request,
        "text": text,
        "parsed": parsed,
    }


def _write(root: Path, req: LlmRequest, payload: Any) -> Path:
    path = root / req.task.value / f"{request_digest(req)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _complete(root: Path, req: LlmRequest):
    return FixtureLlm(root).complete(
        req, owner_id="owner", cancel=_NotCancelled(), deadline=1.0
    )


def test_request_digest_covers_every_public_request_field() -> None:
    req = _request()
    variants = {
        "task": replace(req, task=LlmTask.chat),
        "route": replace(req, route="scene_data.other"),
        "system": replace(req, system="Different synthetic prompt."),
        "parts": replace(req, parts=[LlmPart(kind="text", text="다른 입력")]),
        "output_schema": replace(req, output_schema=SCHEMA),
        "max_output_tokens": replace(req, max_output_tokens=257),
    }
    baseline = request_digest(req)
    for field, variant in variants.items():
        assert request_digest(variant) != baseline, field


def test_request_digest_hashes_png_bytes_in_the_canonical_payload() -> None:
    png = b"\x89PNG\r\n\x1a\nsynthetic-frame"
    req = _request(parts=[LlmPart(kind="png", png=png)])
    expected = canonical_digest(
        {
            "task": "scene_data",
            "route": "scene_data",
            "system": "Synthetic fixture prompt.",
            "parts": [
                {
                    "kind": "png",
                    "png_sha256": hashlib.sha256(png).hexdigest(),
                }
            ],
            "output_schema": None,
            "max_output_tokens": 256,
        }
    )
    assert request_digest(req) == expected
    assert request_digest(replace(req, parts=[LlmPart(kind="png", png=bytes(png))])) == expected
    assert request_digest(replace(req, parts=[LlmPart(kind="png", png=png + b"x")])) != expected


def test_png_record_with_matching_digest_plays_back(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\nsynthetic-frame"
    req = _request(parts=[LlmPart(kind="png", png=png)])
    _write(
        tmp_path,
        req,
        _payload(req, text="synthetic", parsed={"background_id": "bg"}),
    )
    result = _complete(tmp_path, req)
    assert result.text == "synthetic"
    assert result.parsed == {"background_id": "bg"}


def test_missing_record_fails_with_invalid_output(tmp_path: Path) -> None:
    req = _request()
    with pytest.raises(AppError) as raised:
        _complete(tmp_path, req)
    assert raised.value.code == "llm_invalid_output"
    assert raised.value.detail["task"] == req.task.value
    assert raised.value.detail["digest"] == request_digest(req)


def test_corrupt_record_fails_with_invalid_output(tmp_path: Path) -> None:
    req = _request()
    _write(tmp_path, req, "{not json")
    with pytest.raises(AppError) as raised:
        _complete(tmp_path, req)
    assert raised.value.code == "llm_invalid_output"
    assert raised.value.detail["record"] == "malformed"


def test_record_request_must_match_the_digest_filename(tmp_path: Path) -> None:
    req = _request()
    other = replace(req, system="Different synthetic prompt.")
    _write(tmp_path, req, _payload(req, request=_request_record(other)))
    with pytest.raises(AppError) as raised:
        _complete(tmp_path, req)
    assert raised.value.code == "llm_invalid_output"
    assert raised.value.detail["record"] == "request"


def test_record_task_must_match_the_request_task(tmp_path: Path) -> None:
    req = _request()
    _write(tmp_path, req, _payload(req, task="chat"))
    with pytest.raises(AppError) as raised:
        _complete(tmp_path, req)
    assert raised.value.code == "llm_invalid_output"
    assert raised.value.detail["record"] == "task"


def test_schema_invalid_response_is_rejected(tmp_path: Path) -> None:
    req = _request(output_schema=SCHEMA)
    _write(tmp_path, req, _payload(req, text='{"answer": 3}', parsed={"answer": 3}))
    with pytest.raises(AppError) as raised:
        _complete(tmp_path, req)
    assert raised.value.code == "llm_invalid_output"
    assert raised.value.detail["validation_rule"] == "type"


def test_recorded_parsed_value_must_match_the_validated_text(tmp_path: Path) -> None:
    req = _request(output_schema=SCHEMA)
    _write(
        tmp_path,
        req,
        _payload(req, text='{"answer": "current"}', parsed={"answer": "stale"}),
    )
    with pytest.raises(AppError) as raised:
        _complete(tmp_path, req)
    assert raised.value.code == "llm_invalid_output"
    assert raised.value.detail["record"] == "parsed"


def test_schema_valid_text_is_returned_as_parsed(tmp_path: Path) -> None:
    req = _request(output_schema=SCHEMA)
    _write(tmp_path, req, _payload(req, text='{"answer": "current"}', parsed=None))
    result = _complete(tmp_path, req)
    assert result.text == '{"answer": "current"}'
    assert result.parsed == {"answer": "current"}
    assert result.usage.provider == "fixture"
    assert result.usage.model == "fixture"


def test_legacy_record_without_schema_keeps_its_recorded_parsed_value(tmp_path: Path) -> None:
    req = _request()
    parsed = {"beats": [{"id": "beat-1", "text": "합성"}]}
    _write(tmp_path, req, _payload(req, text="synthetic", parsed=parsed))
    result = _complete(tmp_path, req)
    assert result.parsed == parsed
