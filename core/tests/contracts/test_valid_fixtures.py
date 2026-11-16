"""Every valid contract fixture must validate against its Pydantic model."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas import (
    artifact,
    bgm_entry,
    change,
    job,
    preset,
    project,
    scene,
    settings,
    style_manifest,
    template_manifest,
    video,
    voice_manifest,
)
from tests.conftest import load_json

VALID = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "valid"

MODELS = {
    "project_min": project.Project,
    "video_ko_just_three": video.Video,
    "video_ko_typewriter_typing": video.Video,
    "video_en_its_like": video.Video,
    "video_ko_draft_no_visual": video.Video,
    "scene_fixed_stage": scene.Scene,
    "scene_full_stage": scene.Scene,
    "scene_dialog_stage_typewriter": scene.Scene,
    "scene_generated_template": scene.Scene,
    "scene_text_edge": scene.Scene,
    "settings_typewriter_typing": settings.Settings,
    "preset_min": preset.Preset,
    "change_single_value": change.ChangePlan,
    "change_scene_rewrite": change.ChangePlan,
    "change_reorder": change.ChangePlan,
    "timing_sentence_fallback": artifact.Timing,
    "timing_typewriter": artifact.Timing,
    "bgm_builtin": bgm_entry.BuiltinBgm,
    "bgm_upload": bgm_entry.UploadBgm,
    "bgm_code": bgm_entry.CodeBgm,
    "sfx_pop": bgm_entry.SfxEntry,
    "typing_keys": bgm_entry.TypingSoundEntry,
    "style_generated": style_manifest.StyleManifest,
    "template_generated": template_manifest.TemplateManifest,
    "voice_fixed_wav": voice_manifest.VoiceManifest,
}
for state in ("queued", "running", "succeeded", "failed", "cancelling", "cancelled"):
    MODELS[f"job_{state}"] = job.Job


def test_all_valid_fixtures_have_a_model() -> None:
    names = {path.stem for path in VALID.glob("*.json")}
    assert names == set(MODELS), f"unmapped fixtures: {sorted(names - set(MODELS))}"


@pytest.mark.parametrize("name", sorted(MODELS))
def test_valid_fixture_passes_schema(name: str) -> None:
    data = load_json(f"contracts/valid/{name}.json")
    instance = MODELS[name].model_validate(data)
    assert instance.model_dump(mode="json", by_alias=True) is not None
