"""The reference_vision prompt: style notes, review inputs and the declared data."""

from __future__ import annotations

import json

import pytest

from app.ports import AppError
from app.services.reference.vision import PROMPT_ROOT, ROUTE, ReferenceValues, load_prompt


def _fixtures() -> list[dict]:
    path = PROMPT_ROOT / ROUTE / "style-fixtures.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_20_vision_prompt_has_style_notes_and_review_inputs() -> None:
    fixtures = _fixtures()
    assert 2 <= len(fixtures) <= 5
    for fixture in fixtures:
        system = load_prompt(fixture["data"])
        assert system.startswith("# Style notes")
        assert "말투 예시" in system


def test_20_vision_prompt_refuses_undeclared_or_missing_data() -> None:
    with pytest.raises(AppError):
        load_prompt({"transcript": "x"})
    with pytest.raises(AppError):
        load_prompt({"transcript": "x", "allowed": {}, "extra": 1})


def test_20_vision_output_has_no_free_text_field() -> None:
    schema = ReferenceValues.model_json_schema()
    free = [
        name for name, spec in schema["properties"].items()
        if spec.get("type") == "string" and "enum" not in spec and "pattern" not in spec
    ]
    assert free == []
    with pytest.raises(ValueError):
        ReferenceValues.model_validate({"note": "anything"})
