"""Generated schema roots keep the union and object constraints of their models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from app.schemas import common, voice_manifest
from tests.conftest import load_json

SCHEMAS = Path(__file__).resolve().parents[3] / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["bgm-entry", "sandbox-io"])
def test_union_schema_rejects_an_empty_object(name: str) -> None:
    with pytest.raises(ValidationError):
        Draft202012Validator(_load(name)).validate({})


def test_palette_schema_rejects_bad_extra_colours() -> None:
    style = _load("style-manifest")
    validator = Draft202012Validator(
        {"$defs": style["$defs"], "$ref": "#/$defs/Palette"}
    )
    base = {
        "bg": "#101820",
        "ink": "#f2f2f2",
        "accent": "#ffcc00",
        "caption_text": "#ffffff",
        "caption_box": "#101820",
    }
    validator.validate({**base, "accent_light": "#abcdef"})
    with pytest.raises(ValidationError):
        validator.validate({**base, "oops": 123})
    with pytest.raises(ValidationError):
        validator.validate({**base, "BAD": "#abcdef"})


def test_bgm_schema_requires_tenths_of_a_db() -> None:
    fixtures = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "valid"
    payload = json.loads((fixtures / "bgm_builtin.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(_load("bgm-entry"))
    validator.validate(payload)
    payload["loudness_lufs_x10"] = -16.5
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_voice_speed_schema_matches_the_model_for_every_step() -> None:
    document = _load("voice-manifest")
    validator = Draft202012Validator(
        {"$defs": document["$defs"], "$ref": "#/$defs/VoiceSettings"}
    )
    fixture = load_json("contracts/valid/voice_fixed_wav.json")
    base = fixture["settings"]
    for hundredths in range(80, 126):
        payload = {**base, "speed": round(hundredths / 100, 2)}
        validator.validate(payload)
        assert voice_manifest.VoiceSettings.model_validate(payload).speed == payload[
            "speed"
        ]
    rejected = (
        1.005,
        1.001,
        0.805,
        1.111,
        0.799,
        1.251,
        1.000000001,
        1.110000001,
        0.800000001,
        1.250000001,
        0.799999999,
        1.249999999,
    )
    for speed in rejected:
        payload = {**base, "speed": speed}
        with pytest.raises(ValidationError):
            validator.validate(payload)
        with pytest.raises(PydanticValidationError):
            voice_manifest.VoiceSettings.model_validate(payload)
        with pytest.raises(PydanticValidationError):
            voice_manifest.VoiceManifest.model_validate(
                {**fixture, "settings": payload}
            )


@pytest.mark.parametrize(
    ("document", "definition", "alias", "good"),
    [
        ("common", "RelPath", common.RelPath, "assets/hero.png"),
        ("bgm-entry", "WavRelPath", common.WavRelPath, "audio/sample.wav"),
        ("style-manifest", "AssetRelPath", common.AssetRelPath, "assets/hero.png"),
        ("font-manifest", "FontRelPath", common.FontRelPath, "fonts/galmuri11.ttf"),
    ],
)
def test_relative_path_schema_matches_pydantic(
    document: str, definition: str, alias, good: str
) -> None:  # type: ignore[no-untyped-def]
    payload = _load(document)
    schema = payload["$defs"][definition]
    validator = Draft202012Validator({"$defs": payload["$defs"], **schema})
    adapter = TypeAdapter(alias)
    validator.validate(good)
    assert adapter.validate_python(good) == good
    suffix = good.rsplit(".", 1)[1]
    for bad in (f"assets/../outside.{suffix}", f"assets//outside.{suffix}"):
        with pytest.raises(ValidationError):
            validator.validate(bad)
        with pytest.raises(PydanticValidationError):
            adapter.validate_python(bad)
