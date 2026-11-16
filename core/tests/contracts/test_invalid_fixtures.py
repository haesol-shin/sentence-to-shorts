"""Invalid fixtures: schema failures must fail, semantic fixtures must pass schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import (
    api,
    artifact,
    bgm_entry,
    project,
    scene,
    script,
    settings,
    style_manifest,
    video,
    voice_manifest,
)
from tests.conftest import load_json

INVALID = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "invalid"

MODELS = {
    "extra_field": project.Project,
    "schema_version_2": project.Project,
    "bad_digest": artifact.Timing,
    "path_escape_asset": style_manifest.StyleManifest,
    "bgm_code_20s": bgm_entry.CodeBgm,
    "voice_cloning_true": voice_manifest.VoiceManifest,
    "stale_base_revision_request": api.BaseRevision,
    "unknown_asset_id": scene.Scene,
    "unknown_card_id": settings.Settings,
    "duplicate_scene_order": video.Video,
    "order_scene_mismatch": video.Video,
    "duplicate_line_id": scene.Scene,
    "typewriter_fixed_stage": settings.Settings,
    "role_none_with_character": settings.Settings,
    "presenter_without_character": settings.Settings,
    "highlight_out_of_range": script.Line,
    "reveal_line_unknown": scene.Scene,
    "typing_sound_mode": settings.Settings,
    "typing_sound_kind": settings.Settings,
    "typing_cue": scene.Scene,
}
SEMANTIC_CODES = {
    "unknown_catalog_id",
    "duplicate_order",
    "duplicate_line_id",
    "typewriter_layout",
    "role_none_character",
    "character_missing",
    "incompatible_part",
    "highlight_range",
    "reveal_line_unknown",
    "typing_sound_mode",
    "typing_sound_kind",
    "typing_cue",
    "revision_conflict",
}
SCHEMA_CODES = {"validation_failed", "unsupported_version"}


def test_expect_covers_every_invalid_file() -> None:
    expect = load_json("contracts/invalid/expect.json")
    files = {path.stem for path in INVALID.glob("*.json") if path.name != "expect.json"}
    expected = {name.removesuffix(".json") for name in expect["files"]}
    assert files == expected
    assert files == set(MODELS)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_invalid_fixture_expectation(name: str) -> None:
    expect = load_json("contracts/invalid/expect.json")["files"][f"{name}.json"]
    data = load_json(f"contracts/invalid/{name}.json")
    if expect["level"] == "schema":
        assert expect["code"] in SCHEMA_CODES
        with pytest.raises(ValidationError):
            MODELS[name].model_validate(data)
    else:
        assert expect["level"] == "semantic"
        assert expect["code"] in SEMANTIC_CODES
        MODELS[name].model_validate(data)
