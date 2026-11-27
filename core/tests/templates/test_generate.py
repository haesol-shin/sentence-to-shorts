"""Generated styles, templates and code BGM on the host launcher (no runtime needed)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ports import AppError
from app.schemas.scene import Scene
from app.services.render import BuiltinLayerDrawer, PixelPartsBuilder
from app.services.templates import service as templates_service
from app.services.templates.prompting import PROMPT_ROOT, load_prompt
from app.services.templates.service import TEST_SCENE, BuiltinNotConnected
from tests.templates import scenarios
from tests.templates.conftest import Harness, program, style_answer, template_answer

ROUTES = ("style_code", "template_code", "bgm_code")


def test_6_shape_change_is_ready(harness: Harness) -> None:
    scenarios.shape_change_is_ready(harness)


def test_6_reference_frames_travel_with_the_style_request(harness: Harness) -> None:
    scenarios.reference_frames_travel_with_the_style_request(harness)


def test_6_style_repair_keeps_the_reference_frames(harness: Harness) -> None:
    scenarios.style_repair_keeps_the_reference_frames(harness)


def test_6_style_without_reference_sends_no_frames(harness: Harness) -> None:
    scenarios.style_without_reference_sends_no_frames(harness)


def test_6_later_rounds_get_an_earlier_deadline(harness: Harness) -> None:
    scenarios.later_rounds_get_an_earlier_deadline(harness)


def test_6_later_rounds_are_skipped_when_the_reserve_is_gone(harness: Harness) -> None:
    scenarios.later_rounds_are_skipped_when_the_reserve_is_gone(harness)


def test_6_composed_frame_ignores_the_original_script(harness: Harness) -> None:
    scenarios.composed_frame_ignores_the_original_script(harness)


def test_6_composed_frame_drops_unusable_video_settings(harness: Harness) -> None:
    scenarios.composed_frame_drops_unusable_video_settings(harness)


def test_6_compose_failure_in_a_later_round_keeps_the_last_good(harness: Harness) -> None:
    scenarios.compose_failure_in_a_later_round_keeps_the_last_good(harness)


def test_6_style_failure_in_later_round_keeps_the_last_good(harness: Harness) -> None:
    scenarios.style_failure_in_later_round_keeps_the_last_good(harness)


def test_6_package_write_failure_in_a_later_round_keeps_the_last_good(
    harness: Harness,
) -> None:
    scenarios.package_write_failure_in_a_later_round_keeps_the_last_good(harness)


def test_6_cancel_during_the_last_compose_registers_nothing(harness: Harness) -> None:
    scenarios.cancel_during_the_last_compose_registers_nothing(harness)


def test_6_color_only_change_is_rejected(harness: Harness) -> None:
    scenarios.color_only_is_rejected(harness)


def test_7_narrow_eyes_changes_the_face(harness: Harness) -> None:
    scenarios.narrow_eyes_changes_the_face(harness)


def test_7_body_only_change_is_rejected(harness: Harness) -> None:
    scenarios.body_only_change_is_rejected(harness)


def test_17_saved_style_is_reused_without_llm_or_sandbox(harness: Harness) -> None:
    scenarios.saved_style_is_reused_without_calls(harness)


def test_17_saved_style_theme_parts_match_the_stored_skin(harness: Harness) -> None:
    scenarios.saved_style_theme_parts_match_the_stored_skin(harness)


def test_17_saved_style_without_a_stored_skin_fails_with_a_render_code(
    harness: Harness,
) -> None:
    scenarios.saved_style_without_a_stored_skin_fails_with_a_render_code(harness)


def test_17_saved_style_renders_a_still(harness: Harness) -> None:
    scenarios.saved_style_renders_a_still(harness)


def test_17_template_renders_the_test_scene_and_checks_regions(harness: Harness) -> None:
    scenarios.template_renders_the_test_scene(harness)


def test_bgm_code_twenty_seconds_is_rejected(harness: Harness) -> None:
    scenarios.bgm_of_twenty_seconds_is_rejected(harness)


def test_bgm_code_bad_header_is_rejected(harness: Harness) -> None:
    scenarios.bad_header_is_rejected(harness)


def test_bgm_code_same_code_and_seed_hit_the_cache(harness: Harness) -> None:
    scenarios.same_code_and_seed_hit_the_cache(harness)


def test_bgm_code_failure_keeps_the_previous_bgm(harness: Harness) -> None:
    scenarios.failure_keeps_the_previous_bgm(harness)


def test_17_sandbox_failure_is_repaired_with_the_traceback(harness: Harness) -> None:
    harness.llm.queue(
        style_answer(program("crash")),
        style_answer(program("round_style")),
        style_answer(program("round_style")),
        style_answer(program("round_style")),
    )
    req = scenarios.style_request(harness, "둥근 머리")
    harness.service.generate_style(req, harness.video(), None, ctx=harness.ctx())
    first, second = harness.llm.data(0), harness.llm.data(1)
    assert first["failure"] is None and first["previous_code"] is None
    assert second["previous_code"] == program("crash")
    assert second["failure"]["code"] == "sandbox_crashed"
    assert "head radius is negative" in second["failure"]["message"]
    assert harness.llm.data(2)["frame_code"] == program("round_style")
    assert harness.llm.data(2)["previous_code"] is None
    assert harness.llm.data(2)["failure"] is None


def test_17_repairs_stop_after_two(harness: Harness) -> None:
    before = [item.id for item in harness.catalog.list("art_style")]
    harness.llm.queue(*[style_answer(program("crash"))] * 4)
    req = scenarios.style_request(harness, "둥근 머리")
    with pytest.raises(AppError) as failure:
        harness.service.generate_style(req, harness.video(), None, ctx=harness.ctx())
    assert failure.value.code == "sandbox_crashed"
    assert len(harness.llm.requests) == 3
    assert [item.id for item in harness.catalog.list("art_style")] == before


def test_17_template_with_caption_outside_the_safe_area_needs_a_repair(harness: Harness) -> None:
    unsafe = {
        **template_answer(program("template_band"))["regions"],
        "caption": {"x": 90, "y": 1500, "w": 900, "h": 160},
    }
    harness.llm.queue(
        template_answer(program("template_band"), regions=unsafe),
        template_answer(program("template_band")),
    )
    video = harness.video()
    req = scenarios.TemplateRequest(video_id=video.id, base_revision=1, instruction="자막 아래로")
    ref = harness.service.generate_template(req, video, ctx=harness.ctx())
    assert harness.catalog.get("template", ref.id, ref.revision).regions.caption.y == 1040
    first, repair = harness.llm.requests
    assert (first.system, first.output_schema) == (repair.system, repair.output_schema)
    assert first.parts == repair.parts[:-1]
    assert "Return corrected JSON" in (repair.parts[-1].text or "")
    assert "validation_error" in (repair.parts[-1].text or "")


def test_17_generated_template_draws_through_the_sandbox(harness: Harness) -> None:
    harness.llm.queue(template_answer(program("template_band")))
    video = harness.video()
    req = scenarios.TemplateRequest(video_id=video.id, base_revision=1, instruction="제목 띠")
    ref = harness.service.generate_template(req, video, ctx=harness.ctx())
    scene = Scene.model_validate_json(TEST_SCENE.read_bytes())
    calls = harness.launcher.calls
    layer, meta = harness.service.layer_drawer(ref).draw_layer(
        ref, scene, (1080, 1920), {}, 3, cancel=harness.ctx().cancel
    )
    assert layer is not None and layer.startswith(b"\x89PNG")
    assert meta["boxes"]["caption"] == [90, 1040, 990, 1200]
    assert harness.launcher.calls == calls + 1


def test_17_builtin_modules_come_from_the_bootstrap_tables(harness: Harness) -> None:
    pixel = harness.catalog.pin("art_style", "pixel")
    stage = harness.catalog.pin("template", "fixed_stage")
    assert isinstance(harness.service.parts_builder(pixel), PixelPartsBuilder)
    assert isinstance(harness.service.layer_drawer(stage), BuiltinLayerDrawer)


def test_17_empty_tables_fail_as_not_connected(harness: Harness) -> None:
    deps = SimpleNamespace(llm=harness.llm, sandbox=None, catalog=harness.catalog)
    service = templates_service.create(None, deps)  # type: ignore[arg-type]
    with pytest.raises(BuiltinNotConnected) as failure:
        service.parts_builder(harness.catalog.pin("art_style", "pixel"))
    assert failure.value.detail["reason"] == "builtin_not_connected"
    with pytest.raises(BuiltinNotConnected):
        service.layer_drawer(harness.catalog.pin("template", "fixed_stage"))


@pytest.mark.parametrize("route", ROUTES)
def test_17_code_routes_have_style_notes_and_review_inputs(route: str) -> None:
    path = PROMPT_ROOT / route / "style-fixtures.jsonl"
    fixtures = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert 2 <= len(fixtures) <= 5
    for fixture in fixtures:
        system = load_prompt(route, {**fixture["data"]})
        assert system.startswith("# Style notes")
        assert "말투 예시" in system


def test_17_test_scene_matches_the_contract_fixture() -> None:
    fixture = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "valid"
    expected = json.loads((fixture / "scene_generated_template.json").read_text(encoding="utf-8"))
    assert json.loads(TEST_SCENE.read_text(encoding="utf-8")) == expected
