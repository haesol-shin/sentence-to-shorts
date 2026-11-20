"""Offline checks for the structured output schemas sent to Anthropic."""

from typing import Any

import anthropic
import pytest
from jsonschema import Draft202012Validator

from app.services.reference.vision import ReferenceValues
from app.services.story.draft import DraftOutput
from app.services.story.interpret import ChatOutput
from app.services.story.precheck import PrecheckResponse
from app.services.story.scene_data import SceneDataResponse
from app.services.story.scene_edit import SceneRewriteResponse
from app.services.story.script import ScriptOutput, SplitOutput
from app.services.templates.outputs import BgmCodeAnswer, StyleCodeAnswer, TemplateCodeAnswer

OUTPUT_MODELS = (
    BgmCodeAnswer,
    ChatOutput,
    DraftOutput,
    PrecheckResponse,
    ReferenceValues,
    SceneDataResponse,
    SceneRewriteResponse,
    ScriptOutput,
    SplitOutput,
    StyleCodeAnswer,
    TemplateCodeAnswer,
)
REJECTED = {"minLength", "maxLength", "minimum", "maximum", "maxItems"}


def _assert_strict_schema(node: dict[str, Any], path: str) -> None:
    assert not (REJECTED & node.keys()), path
    assert node.get("minItems", 0) in (0, 1), path
    if node.get("type") == "object" or "additionalProperties" in node:
        assert node.get("additionalProperties") is False, path
        assert set(node.get("required", ())) <= node.get("properties", {}).keys(), path

    for keyword in ("properties", "$defs"):
        for name, child in node.get(keyword, {}).items():
            _assert_strict_schema(child, f"{path}/{keyword}/{name}")
    for keyword in ("anyOf", "allOf"):
        for index, child in enumerate(node.get(keyword, ())):
            _assert_strict_schema(child, f"{path}/{keyword}/{index}")
    if "items" in node:
        _assert_strict_schema(node["items"], f"{path}/items")


@pytest.mark.parametrize("model", OUTPUT_MODELS, ids=[model.__name__ for model in OUTPUT_MODELS])
def test_10_1_output_model_transforms_to_strict_schema(model):
    schema = anthropic.transform_schema(model.model_json_schema())
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object"
    _assert_strict_schema(schema, model.__name__)


def test_10_1_transformed_draft_schema_admits_a_nonempty_evidence_list():
    validator = Draft202012Validator(anthropic.transform_schema(DraftOutput.model_json_schema()))
    validator.validate({
        "topic": "합성 주제",
        "values": {"target_duration_s": 60},
        "evidence": [{"field": "target_duration_s", "quote": "1분짜리"}],
    })
