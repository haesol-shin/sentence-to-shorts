"""Acceptance scenarios shared by the host runs and the real sandbox runs."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from app.plugins.registry import file_list_revision
from app.ports import AppError
from app.schemas.api import BgmCodeRequest, StyleRequest, TemplateRequest
from app.schemas.common import PinnedRef
from app.schemas.style_manifest import StyleManifest
from app.schemas.template_manifest import TemplateManifest
from app.services.render import BuiltinLayerDrawer, PixelPartsBuilder, RenderService
from app.services.templates import sprites
from tests.templates.conftest import (
    Harness,
    bgm_answer,
    narrow_eyes,
    no_new_calls,
    pixel_recolor_code,
    program,
    style_answer,
    template_answer,
)

PROJECT_ID = "p_06pxfteaw88hs93kkckw5j51ng"


def style_request(
    harness: Harness, instruction: str, base: PinnedRef | None = None
) -> StyleRequest:
    video = harness.video()
    return StyleRequest(
        video_id=video.id,
        base_revision=video.revision,
        instruction=instruction,
        base_style=base,
        use_reference=False,
    )


def new_style(harness: Harness, code: str | None = None) -> PinnedRef:
    harness.llm.queue(style_answer(code or program("round_style")))
    req = style_request(harness, "머리는 작고 둥글게, 몸은 길고 가늘게")
    return harness.service.generate_style(req, harness.video(), None, ctx=harness.ctx())


def shape_change_is_ready(harness: Harness) -> None:
    ref = new_style(harness)
    manifest = harness.catalog.get("art_style", ref.id, ref.revision)
    assert isinstance(manifest, StyleManifest)
    assert manifest.status == "ready" and manifest.origin == "generated"
    assert manifest.extends is None and manifest.renderer.kind == "sandbox"
    folder = harness.catalog.package_dir("art_style", ref)
    assert folder.parent == harness.root / "data" / "s"
    assert file_list_revision(folder) == ref.revision
    shape = json.loads((folder / "checks.json").read_text(encoding="utf-8"))["shape"]
    assert shape["passed"] and shape["threshold_iou_x1000"] == 800
    compared = {name: group for name, group in shape["groups"].items() if group["compared"]}
    assert set(compared) == {"head", "body", "prop", "background"}
    assert all(group["iou_x1000"] < 800 for group in compared.values())


def color_only_is_rejected(harness: Harness) -> None:
    before = [item.id for item in harness.catalog.list("art_style")]
    with pytest.raises(AppError) as failure:
        new_style(harness, pixel_recolor_code())
    detail = failure.value.detail
    assert failure.value.code == "sandbox_output_invalid"
    assert detail["reason"] == "color_only" and detail["threshold_iou_x1000"] == 800
    assert detail["head_iou_x1000"] >= 800 and detail["background_iou_x1000"] >= 800
    assert [item.id for item in harness.catalog.list("art_style")] == before


def narrow_eyes_changes_the_face(harness: Harness) -> None:
    parent = new_style(harness)
    harness.llm.queue(style_answer(narrow_eyes(program("round_style"))))
    req = style_request(harness, "눈을 가늘게", base=parent)
    child = harness.service.generate_style(req, harness.video(parent), None, ctx=harness.ctx())
    manifest = harness.catalog.get("art_style", child.id, child.revision)
    assert isinstance(manifest, StyleManifest) and manifest.extends == parent
    folder = harness.catalog.package_dir("art_style", child)
    shape = json.loads((folder / "checks.json").read_text(encoding="utf-8"))["shape"]
    assert shape["mode"] == "modify" and shape["face_changed_pixels"] > 0
    assert harness.llm.data(1)["parent_program"] == program("round_style")

    harness.llm.queue(style_answer(program("round_style")))
    with pytest.raises(AppError) as failure:
        harness.service.generate_style(req, harness.video(parent), None, ctx=harness.ctx())
    assert failure.value.detail["reason"] == "face_unchanged"
    assert failure.value.detail["face_changed_pixels"] == 0


def body_only_change_is_rejected(harness: Harness) -> None:
    parent = new_style(harness)
    before = harness.catalog.list("art_style")
    code = program("round_style").replace("0.72, 0.95", "0.72, 0.75", 1)
    harness.llm.queue(style_answer(code))
    req = style_request(harness, "눈을 가늘게", base=parent)
    with pytest.raises(AppError) as failure:
        harness.service.generate_style(req, harness.video(parent), None, ctx=harness.ctx())
    assert failure.value.code == "sandbox_output_invalid"
    assert failure.value.detail["reason"] == "face_unchanged"
    assert failure.value.detail["face_changed_pixels"] == 0
    assert failure.value.detail["body_iou_x1000"] < 1000
    assert harness.catalog.list("art_style") == before


def saved_style_is_reused_without_calls(harness: Harness) -> None:
    ref = new_style(harness)
    video = harness.video(ref)
    character = video.settings.visual.character
    assert character is not None
    folder = harness.catalog.package_dir("art_style", ref)
    with no_new_calls(harness):
        builder = harness.service.parts_builder(ref)
        parts = builder.build_parts(
            ref,
            character.model_dump(mode="json"),
            "expr_happy",
            "pose_idle",
            0,
            cancel=harness.ctx().cancel,
        )
    stored = (folder / "sprites" / f"{character.slots.face}.json").read_bytes()
    assert Image.open(io.BytesIO(parts["face"])).tobytes() == sprites.rasterize(stored).tobytes()
    assert set(parts) >= {"body", "face", "expression", "pose"}


def saved_style_renders_a_still(harness: Harness) -> None:
    """A video on the generated style renders through the existing render path."""
    ref = new_style(harness)
    video = harness.video(ref)
    scene_id = video.scene_order[0]
    scene = video.scenes[scene_id]
    assert scene.visual is not None and video.settings.visual.character is not None
    ctx = harness.ctx()
    parts: dict[str, bytes] = {}
    if scene.visual.characters:
        placement = scene.visual.characters[0]
        parts = harness.service.parts_builder(ref).build_parts(
            ref,
            video.settings.visual.character.model_dump(mode="json"),
            placement.expression_id,
            placement.pose_id,
            0,
            cancel=ctx.cancel,
        )
    skin = PixelPartsBuilder(harness.catalog).theme_parts(ref, video.settings.visual.theme_id)
    layer, _ = BuiltinLayerDrawer(harness.catalog).draw_layer(
        video.settings.format.layout,
        scene,
        (1080, 1920),
        {**parts, **skin},
        0,
        cancel=ctx.cancel,
    )
    render = RenderService(media=None, artifacts=None, catalog=harness.catalog)  # type: ignore[arg-type]
    still = render.still(video, scene_id, parts, layer, None, ctx=ctx)
    with Image.open(still) as image:
        assert image.size == (540, 960)


def template_renders_the_test_scene(harness: Harness) -> None:
    harness.llm.queue(template_answer(program("template_band")))
    video = harness.video()
    req = TemplateRequest(video_id=video.id, base_revision=video.revision, instruction="제목 띠")
    ref = harness.service.generate_template(req, video, ctx=harness.ctx())
    manifest = harness.catalog.get("template", ref.id, ref.revision)
    assert isinstance(manifest, TemplateManifest) and manifest.renderer.kind == "sandbox"
    assert manifest.test.layer_digest is not None
    folder = harness.catalog.package_dir("template", ref)
    assert (folder / "test_scene.json").is_file()

    harness.llm.queue(*[template_answer(program("template_cover"))] * 3)
    with pytest.raises(AppError) as failure:
        harness.service.generate_template(req, video, ctx=harness.ctx())
    assert failure.value.detail["reason"] == "layer covers the visual region"
    assert failure.value.detail["visual_clear_x1000"] < 500


def bgm_request(seed: int | None = 42) -> BgmCodeRequest:
    return BgmCodeRequest(project_id=PROJECT_ID, mood="calm", instruction=None, seed=seed)


def bgm_of_twenty_seconds_is_rejected(harness: Harness) -> None:
    harness.llm.queue(*[bgm_answer(program("bgm_arpeggio"), bpm=60, bars=5)] * 2)
    with pytest.raises(AppError) as failure:
        harness.service.generate_bgm(bgm_request(), ctx=harness.ctx())
    assert failure.value.code == "llm_invalid_output"
    assert harness.launcher.calls == 0

    overrun = program("bgm_arpeggio").replace("EXTRA_BARS = 0", "EXTRA_BARS = 6", 1)
    harness.llm.queue(*[bgm_answer(overrun)] * 3)
    with pytest.raises(AppError) as failure:
        harness.service.generate_bgm(bgm_request(), ctx=harness.ctx())
    assert failure.value.code == "sandbox_output_invalid"


def bad_header_is_rejected(harness: Harness) -> None:
    harness.llm.queue(*[bgm_answer(program("bgm_bad_header"))] * 3)
    with pytest.raises(AppError) as failure:
        harness.service.generate_bgm(bgm_request(), ctx=harness.ctx())
    assert failure.value.code == "sandbox_output_invalid"
    assert "RIFF" in failure.value.detail["reason"]


def same_code_and_seed_hit_the_cache(harness: Harness) -> None:
    harness.llm.queue(bgm_answer(program("bgm_arpeggio")), bgm_answer(program("bgm_arpeggio")))
    first = harness.service.generate_bgm(bgm_request(), ctx=harness.ctx())
    second = harness.service.generate_bgm(bgm_request(), ctx=harness.ctx())
    assert harness.launcher.calls == 1
    first_entry = harness.catalog.get("bgm", first.id, first.revision)
    second_entry = harness.catalog.get("bgm", second.id, second.revision)
    assert first_entry.sha256 == second_entry.sha256
    assert first_entry.duration_ms == 8000 and first_entry.loudness_lufs_x10 is not None


def failure_keeps_the_previous_bgm(harness: Harness) -> None:
    harness.llm.queue(bgm_answer(program("bgm_arpeggio")))
    previous = harness.service.generate_bgm(bgm_request(), ctx=harness.ctx())
    folder = harness.catalog.package_dir("bgm", previous)
    kept = {path.name: path.read_bytes() for path in folder.iterdir()}
    before = harness.catalog.list("bgm")
    harness.llm.queue(*[bgm_answer(program("bgm_bad_header"))] * 3)
    ctx = harness.ctx()
    with pytest.raises(AppError):
        harness.service.generate_bgm(bgm_request(seed=7), ctx=ctx)
    assert harness.catalog.list("bgm") == before
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == kept
    staging = ctx.job_dir / "staging"
    assert not staging.exists() or not any(staging.iterdir())
