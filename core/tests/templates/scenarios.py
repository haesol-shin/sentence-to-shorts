"""Acceptance scenarios shared by the host runs and the real sandbox runs."""

from __future__ import annotations

import errno
import io
import json
import time
from typing import Any

import pytest
from PIL import Image

from app.plugins.registry import file_list_revision
from app.ports import AppError, Cancelled, StyleFrames
from app.schemas.api import BgmCodeRequest, StyleRequest, TemplateRequest
from app.schemas.common import CharacterRole, PinnedRef
from app.schemas.settings import CaptionLayer, CaptionMode, CaptionPosition
from app.schemas.style_manifest import StyleManifest
from app.schemas.template_manifest import TemplateManifest
from app.services.render import BuiltinLayerDrawer, PixelPartsBuilder, RenderService
from app.services.templates import sprites
from app.services.templates.builders import GeneratedPartsBuilder
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
    style = code or program("round_style")
    harness.llm.queue(style_answer(style), style_answer(style), style_answer(style))
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


def _frame(color: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 48), color).save(buffer, format="PNG")
    return buffer.getvalue()


def reference_frames_travel_with_the_style_request(harness: Harness) -> None:
    frames = [_frame(color) for color in ("#112233", "#445566", "#778899", "#aabbcc")]
    hints = StyleFrames(palette=["#112233", "#445566"], frames=frames)
    harness.llm.queue(*(style_answer(program("round_style")) for _ in range(3)))
    req = style_request(harness, "참고 영상의 그림체로").model_copy(
        update={"use_reference": True}
    )

    ref = harness.service.generate_style(req, harness.video(), hints, ctx=harness.ctx())

    first = harness.llm.requests[0]
    assert [part.kind for part in first.parts] == ["png", "png", "png", "png", "text"]
    assert [part.png for part in first.parts if part.kind == "png"] == frames
    second = harness.llm.requests[1]
    assert [part.kind for part in second.parts] == ["png"] * 5 + ["text", "text"]
    images = [part.png for part in second.parts[:5]]
    assert images[:4] == frames
    assert images[4] is not None
    with Image.open(io.BytesIO(images[4])) as composed:
        assert composed.size == (1080, 1920)
    assert second.system == first.system
    assert "Self view" in (second.parts[5].text or "")
    data = json.loads(second.parts[6].text or "")
    assert data["frame_code"] == program("round_style")
    assert data["previous_code"] is None and data["failure"] is None
    assert data["reference_hints"] == {"palette": ["#112233", "#445566"]}
    assert len(harness.llm.requests) == 3
    assert harness.progress[-1] == (3, 3)
    assert {total for _, total in harness.progress} == {3}
    assert str(harness.root) not in json.dumps(data)
    manifest = harness.catalog.get("art_style", ref.id, ref.revision)
    assert isinstance(manifest, StyleManifest) and manifest.provenance is not None
    assert manifest.provenance.reference_digest is not None


def style_repair_keeps_the_reference_frames(harness: Harness) -> None:
    frames = [_frame("#112233")]
    hints = StyleFrames(palette=["#112233"], frames=frames)
    harness.llm.queue(
        style_answer(program("crash")),
        style_answer(program("round_style")),
        style_answer(program("round_style")),
        style_answer(program("round_style")),
    )
    req = style_request(harness, "참고 영상의 그림체로").model_copy(
        update={"use_reference": True}
    )

    harness.service.generate_style(req, harness.video(), hints, ctx=harness.ctx())

    assert len(harness.llm.requests) == 4
    for request in harness.llm.requests:
        assert request.parts[0].kind == "png" and request.parts[0].png == frames[0]
    assert harness.llm.data(1)["reference_hints"] == {"palette": ["#112233"]}
    assert harness.llm.data(1)["previous_code"] == program("crash")
    assert harness.llm.data(1)["failure"]["code"] == "sandbox_crashed"
    assert harness.llm.data(2)["frame_code"] == program("round_style")
    assert harness.llm.data(2)["previous_code"] is None
    assert harness.llm.data(2)["failure"] is None


def style_without_reference_sends_no_frames(harness: Harness) -> None:
    new_style(harness)

    first = harness.llm.requests[0]
    assert [part.kind for part in first.parts] == ["text"]
    assert harness.llm.data(0)["reference_hints"] is None
    second = harness.llm.requests[1]
    assert [part.kind for part in second.parts] == ["png", "text", "text"]
    assert harness.llm.data(1)["frame_code"] == program("round_style")
    assert first.system == second.system
    assert "Self view" in (second.parts[1].text or "")


def later_rounds_get_an_earlier_deadline(harness: Harness) -> None:
    deadline = time.monotonic() + 300
    harness.llm.queue(*(style_answer(program("round_style")) for _ in range(3)))

    harness.service.generate_style(
        style_request(harness, "둥근 머리"),
        harness.video(),
        None,
        ctx=harness.ctx(deadline=deadline),
    )

    assert harness.llm.deadlines[0] == deadline
    assert harness.llm.deadlines[1] <= deadline - 120
    assert harness.llm.deadlines[2] <= deadline - 120


def later_rounds_are_skipped_when_the_reserve_is_gone(harness: Harness) -> None:
    harness.llm.queue(style_answer(program("round_style")))

    ref = harness.service.generate_style(
        style_request(harness, "둥근 머리"),
        harness.video(),
        None,
        ctx=harness.ctx(deadline=time.monotonic() + 5),
    )

    assert len(harness.llm.requests) == 1
    assert harness.progress[-1] == (1, 3)
    folder = harness.catalog.package_dir("art_style", ref)
    assert (folder / "program.py").read_text(encoding="utf-8") == program("round_style")


def composed_frame_ignores_the_original_script(harness: Harness) -> None:
    frames: list[bytes] = []
    for title in ("첫 번째 제목", "두 번째 제목"):
        video = harness.video()
        assert video.script is not None
        video.script.title = title
        harness.llm.queue(*(style_answer(program("round_style")) for _ in range(3)))
        harness.service.generate_style(
            style_request(harness, "둥근 머리"), video, None, ctx=harness.ctx()
        )
        round_two = harness.llm.requests[-2]
        images = [part.png for part in round_two.parts if part.kind == "png"]
        assert len(images) == 1 and images[0] is not None
        frames.append(images[0])
    assert frames[0] == frames[1]


def composed_frame_drops_unusable_video_settings(harness: Harness) -> None:
    video = harness.video()
    video.settings.format.character_role = CharacterRole.none
    video.settings.caption.extra = [
        CaptionLayer(
            language="en",
            mode=CaptionMode.sentence,
            font_id=video.settings.caption.font_id,
            position=CaptionPosition.bottom,
        )
    ]
    harness.llm.queue(*(style_answer(program("round_style")) for _ in range(3)))

    harness.service.generate_style(
        style_request(harness, "둥근 머리"), video, None, ctx=harness.ctx()
    )

    assert len(harness.llm.requests) == 3
    assert harness.progress[-1] == (3, 3)


def compose_failure_in_a_later_round_keeps_the_last_good(harness: Harness) -> None:
    first = program("round_style")
    second = narrow_eyes(first)
    original = harness.service.render_factory
    calls = 0

    def factory(catalog: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise AppError("render_failed")
        assert original is not None
        return original(catalog)

    harness.service.render_factory = factory
    harness.llm.queue(style_answer(first), style_answer(second), style_answer(first))

    ref = harness.service.generate_style(
        style_request(harness, "둥근 머리"), harness.video(), None, ctx=harness.ctx()
    )

    folder = harness.catalog.package_dir("art_style", ref)
    assert (folder / "program.py").read_text(encoding="utf-8") == second
    assert calls == 3
    assert harness.progress[-1] == (2, 3)


def style_failure_in_later_round_keeps_the_last_good(harness: Harness) -> None:
    first = program("round_style")
    second = narrow_eyes(first)
    harness.llm.queue(
        style_answer(first),
        style_answer(second),
        *[style_answer(program("crash")) for _ in range(3)],
    )
    req = style_request(harness, "둥근 머리")
    frames: list[bytes] = []
    compose = harness.service._compose_style_frame

    def record(*args: Any, **kwargs: Any) -> bytes:
        frames.append(compose(*args, **kwargs))
        return frames[-1]

    harness.service._compose_style_frame = record  # type: ignore[method-assign]

    ref = harness.service.generate_style(req, harness.video(), None, ctx=harness.ctx())

    manifests = harness.catalog.list("art_style")
    generated = [item for item in manifests if item.id == ref.id]
    assert len(generated) == 1
    folder = harness.catalog.package_dir("art_style", ref)
    assert (folder / "program.py").read_text(encoding="utf-8") == second
    checks = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
    assert checks["shape"]["passed"]
    assert harness.llm.data(2)["frame_code"] == second
    assert harness.llm.data(2)["previous_code"] is None
    assert harness.llm.data(2)["failure"] is None
    images = [
        [part.png for part in request.parts if part.kind == "png"]
        for request in harness.llm.requests
    ]
    assert len(images[2]) == 1 and images[2][0] == frames[1]
    assert frames[0] != frames[1]
    for repair in (3, 4):
        data = harness.llm.data(repair)
        assert data["frame_code"] == second
        assert data["previous_code"] == program("crash")
        assert data["failure"]["code"] == "sandbox_crashed"
        assert images[repair] == images[2]
    with Image.open(io.BytesIO(frames[1])) as composed:
        assert composed.size == (1080, 1920)
    assert len(harness.llm.requests) == 5
    assert harness.progress[-1] == (2, 3)


def package_write_failure_in_a_later_round_keeps_the_last_good(harness: Harness) -> None:
    first = program("round_style")
    harness.llm.queue(style_answer(first), style_answer(narrow_eyes(first)))
    original = harness.service._style_package
    calls = 0

    def write(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.ENOSPC, "no space")
        return original(*args, **kwargs)

    harness.service._style_package = write  # type: ignore[method-assign]

    ref = harness.service.generate_style(
        style_request(harness, "둥근 머리"), harness.video(), None, ctx=harness.ctx()
    )

    folder = harness.catalog.package_dir("art_style", ref)
    assert (folder / "program.py").read_text(encoding="utf-8") == first
    assert len(harness.llm.requests) == 2
    assert harness.progress[-1] == (1, 3)


def cancel_during_the_last_compose_registers_nothing(harness: Harness) -> None:
    harness.llm.queue(*(style_answer(program("round_style")) for _ in range(3)))
    before = [item.id for item in harness.catalog.list("art_style")]
    ctx = harness.ctx()
    original = harness.service._compose_style_frame
    calls = 0

    def compose(*args: Any, **kwargs: Any) -> bytes:
        nonlocal calls
        calls += 1
        frame = original(*args, **kwargs)
        if calls == 3:
            ctx.cancel.cancel()  # type: ignore[attr-defined]
        return frame

    harness.service._compose_style_frame = compose  # type: ignore[method-assign]

    with pytest.raises(Cancelled):
        harness.service.generate_style(
            style_request(harness, "둥근 머리"), harness.video(), None, ctx=ctx
        )

    assert calls == 3
    assert [item.id for item in harness.catalog.list("art_style")] == before


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
    child_code = narrow_eyes(program("round_style"))
    harness.llm.queue(*(style_answer(child_code) for _ in range(3)))
    req = style_request(harness, "눈을 가늘게", base=parent)
    child = harness.service.generate_style(req, harness.video(parent), None, ctx=harness.ctx())
    manifest = harness.catalog.get("art_style", child.id, child.revision)
    assert isinstance(manifest, StyleManifest) and manifest.extends == parent
    folder = harness.catalog.package_dir("art_style", child)
    shape = json.loads((folder / "checks.json").read_text(encoding="utf-8"))["shape"]
    assert shape["mode"] == "modify" and shape["face_changed_pixels"] > 0
    assert harness.llm.data(3)["parent_program"] == program("round_style")

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


def saved_style_theme_parts_match_the_stored_skin(harness: Harness) -> None:
    ref = new_style(harness)
    video = harness.video(ref)
    theme_id = video.settings.visual.theme_id
    manifest = harness.catalog.get("art_style", ref.id, ref.revision)
    assert isinstance(manifest, StyleManifest)
    theme = next(item for item in manifest.themes if item.id == theme_id)
    folder = harness.catalog.package_dir("art_style", ref)
    stored = (folder / "sprites" / f"{theme.skin_id}.json").read_bytes()
    with no_new_calls(harness):
        skin = harness.service.parts_builder(ref).theme_parts(ref, theme_id)  # type: ignore[attr-defined]
    assert set(skin) == {"skin"}
    assert Image.open(io.BytesIO(skin["skin"])).tobytes() == sprites.rasterize(
        stored, cell=1
    ).tobytes()
    assert skin == PixelPartsBuilder(harness.catalog).theme_parts(ref, theme_id)


class _EditedCatalog:
    """Serves one style manifest edited after it was accepted, over the same package."""

    def __init__(self, catalog: Any, manifest: StyleManifest) -> None:
        self.catalog = catalog
        self.manifest = manifest

    def get(self, kind: str, item_id: str, revision: str) -> StyleManifest:
        return self.manifest

    def package_dir(self, kind: str, ref: PinnedRef) -> Any:
        return self.catalog.package_dir(kind, ref)


def saved_style_without_a_stored_skin_fails_with_a_render_code(harness: Harness) -> None:
    ref = new_style(harness)
    theme_id = harness.video(ref).settings.visual.theme_id
    manifest = harness.catalog.get("art_style", ref.id, ref.revision)
    assert isinstance(manifest, StyleManifest)
    theme = next(item for item in manifest.themes if item.id == theme_id)
    others = [item for item in manifest.assets if item.id != theme.skin_id]
    skin = next(item for item in manifest.assets if item.id == theme.skin_id)
    edits = {
        "missing": others,
        "not_a_stored_grid": [*others, skin.model_copy(update={"file": "sprites/skin.png"})],
    }
    for reason, assets in edits.items():
        edited = _EditedCatalog(harness.catalog, manifest.model_copy(update={"assets": assets}))
        builder = GeneratedPartsBuilder(edited, None)  # type: ignore[arg-type]
        with pytest.raises(AppError) as failure:
            builder.theme_parts(ref, theme_id)
        assert failure.value.code == "render_input_invalid"
        assert failure.value.detail == {"input": "skin", "reason": reason}
    builder = GeneratedPartsBuilder(harness.catalog, None)  # type: ignore[arg-type]
    with pytest.raises(AppError) as unknown:
        builder.theme_parts(ref, "no_such_theme")
    assert unknown.value.code == "unknown_catalog_id"


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
