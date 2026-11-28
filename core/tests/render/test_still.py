"""Scene stills: fixture scenes, determinism, themes, caption safety and glyphs."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageChops

from app.caption_layout import (
    BUBBLE_OUTSET,
    FRAME_WIDTH,
    PLATE_SIDE_PAD,
    SAFE_TOP,
    inside,
    place_area,
    place_box,
    safe_area,
)
from app.ports import AppError
from app.schemas.artifact import Timing
from app.schemas.common import Box
from app.schemas.settings import CaptionPlace
from app.schemas.template_manifest import TemplateManifest
from app.schemas.video import Video
from app.services.render.layers import CORNER_CELLS, SKIN_CELL, nine_slice
from app.services.render.pixel import decode_png
from app.services.render.text import ELLIPSIS, fit, open_font
from tests.render.conftest import Studio, Token, load

GRID = [
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "middle_center",
    "middle_right",
    "left",
    "center",
    "right",
]

FIXTURE_SCENES = [
    ("scene_fixed_stage.json", "fixed_stage", "sentence", "presenter"),
    ("scene_full_stage.json", "full_stage", "phrase", "subject"),
    ("scene_dialog_stage_typewriter.json", "dialog_stage", "typewriter", "presenter"),
    ("scene_text_edge.json", "fixed_stage", "sentence", "presenter"),
]
POSITION_LAYOUTS = ["fixed_stage", "full_stage"]
POSITIONS = ["top", "upper", "middle", "lower", "bottom"]
THEME_BACKGROUNDS = {"day": "bg_village", "moonlight": "bg_city_night", "arcade": "bg_castle"}
TEMPLATES = [
    ("fixed_stage", "sentence"),
    ("full_stage", "sentence"),
    ("dialog_stage", "typewriter"),
]
ONE_LINE = "첫째, 원두가 신선한지 본다."
TWO_LINES = "첫째, 원두가 신선한지 본다. 볶은 날짜가 2주 안쪽이면 향이 살아 있다."
PLATFORM_ZONE_TOP = 1248
"""Top of the bottom 672 px that platform overlays cover."""
OLD_FIGURE_BOXES = {
    ("fixed_stage", "top_left"): (170, 384, 370, 704),
    ("fixed_stage", "center"): (440, 640, 640, 960),
    ("fixed_stage", "middle_right"): (710, 512, 910, 832),
    ("full_stage", "top_left"): (120, 126, 420, 606),
    ("full_stage", "center"): (390, 480, 690, 960),
    ("full_stage", "middle_right"): (660, 303, 960, 783),
    ("dialog_stage", "top_left"): (120, 126, 420, 606),
    ("dialog_stage", "center"): (390, 480, 690, 960),
    ("dialog_stage", "middle_right"): (660, 303, 960, 783),
}
"""Pixels the character covered (left, top, right, bottom) when the visual region ended
above the caption band; the picture growing to the frame bottom must not change them."""


def _record(path: Path) -> dict:
    return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))


def _fixture_still(studio: Studio, name: str, layout: str, mode: str, role: str) -> Path:
    scene = load(name)
    video = studio.video(scene, layout=layout, mode=mode, role=role)
    return studio.still(video, scene["id"])


def _box(values: list[int]) -> Box:
    x, y, w, h = values
    return Box(x=x, y=y, w=w, h=h)


def _assert_safe(record: dict) -> None:
    caption = record["caption"]
    plate = _box(caption["plate"])
    assert 1 <= len(caption["lines"]) <= 2
    assert inside(plate, safe_area())
    for line in caption["lines"]:
        assert inside(_box(line["box"]), plate)


@pytest.mark.parametrize(("name", "layout", "mode", "role"), FIXTURE_SCENES)
def test_29_fixture_scene_renders_png(
    studio: Studio, name: str, layout: str, mode: str, role: str
) -> None:
    path = _fixture_still(studio, name, layout, mode, role)
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == (540, 960)
        assert image.text["timing"] == "estimated"


@pytest.mark.parametrize("base", ["video_ko_just_three.json", "video_en_its_like.json"])
def test_29_first_scene_of_language_video_renders_png(studio: Studio, base: str) -> None:
    video = Video.model_validate(load(base))
    path = studio.still(video, video.scene_order[0])
    with Image.open(path) as image:
        assert image.size == (540, 960)
    _, record = studio.compose(video, video.scene_order[0])
    assert record["caption"]["lines"][0]["text"] == video.scenes[video.scene_order[0]].lines[
        0
    ].display_text


def test_29_preview_still_has_no_baked_caption(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    other = copy.deepcopy(scene)
    other["lines"][0]["display_text"] = "다른 대사"
    other["lines"][0]["speech_text"] = "다른 대사"
    first = studio.video(scene)
    second = studio.video(other)

    first_path = studio.still(first, scene["id"], name="caption_free_first")
    second_path = studio.still(second, scene["id"], name="caption_free_second")

    assert hashlib.sha256(first_path.read_bytes()).hexdigest() == hashlib.sha256(
        second_path.read_bytes()
    ).hexdigest()
    record = _record(first_path)
    assert record["caption"]["line_id"] == scene["lines"][0]["id"]
    assert "caption_extra" not in record
    _, composed = studio.compose(first, scene["id"])
    assert composed["caption"]["plate"] == record["caption"]["plate"]


def test_29_same_input_gives_same_png_digest(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    video = studio.video(scene)
    first = studio.still(video, scene["id"], name="first")
    second = studio.still(video, scene["id"], name="second")
    digest = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)]
    assert digest[0] == digest[1]


def _figure_box(
    studio: Studio,
    scene: dict[str, Any],
    anchor: str,
    *,
    layout: str = "fixed_stage",
    mode: str = "sentence",
) -> tuple[tuple[int, int, int, int], TemplateManifest]:
    """Pixels the character adds over the same frame without a character."""
    scene = copy.deepcopy(scene)
    scene["visual"]["characters"][0]["anchor"] = anchor
    video = studio.video(scene, layout=layout, mode=mode)
    parts, layer = studio.inputs(video, scene["id"])
    frame, _ = studio.service.compose(video, scene["id"], parts, layer)
    bare = copy.deepcopy(scene)
    bare["visual"]["characters"] = []
    empty = studio.video(bare, layout=layout, mode=mode)
    base, _ = studio.service.compose(empty, scene["id"], parts, layer)
    box = ImageChops.difference(frame.convert("RGB"), base.convert("RGB")).getbbox()
    assert box is not None
    layout_ref = video.settings.format.layout
    manifest = studio.registry.get("template", layout_ref.id, layout_ref.revision)
    assert isinstance(manifest, TemplateManifest)
    return box, manifest


@pytest.mark.parametrize("anchor", GRID)
def test_29_character_grid_places_the_figure_at_each_point(
    studio: Studio, anchor: str
) -> None:
    scene = load("scene_fixed_stage.json")
    (left, top, right, bottom), manifest = _figure_box(studio, scene, anchor)
    region = manifest.regions.visual
    point = getattr(manifest.character_anchors, anchor)
    assert point is not None
    assert (left + right) // 2 == pytest.approx(point.x, abs=2)
    assert bottom == pytest.approx(point.y, abs=2)
    assert region.x <= left and right <= region.x + region.w
    assert region.y < top and bottom <= region.y + region.h


@pytest.mark.parametrize("layout", ["fixed_stage", "dialog_stage", "full_stage"])
def test_29_builtin_templates_define_nine_distinct_grid_points(
    studio: Studio, layout: str
) -> None:
    manifest = studio.registry.get("template", layout)
    assert isinstance(manifest, TemplateManifest)
    anchors = manifest.character_anchors
    points = [(getattr(anchors, name).x, getattr(anchors, name).y) for name in GRID]
    assert len(set(points)) == len(GRID)
    rows = [
        {getattr(anchors, f"{row}_{column}").y for column in ("left", "center", "right")}
        for row in ("top", "middle")
    ]
    bottom_row = {anchors.left.y, anchors.center.y, anchors.right.y}
    assert all(len(row) == 1 for row in rows)
    assert rows[0].pop() < rows[1].pop() < bottom_row.pop()
    columns = {anchors.left.x, anchors.center.x, anchors.right.x}
    assert len(columns) == 3


def test_6_theme_change_changes_background_box_and_palette(studio: Studio) -> None:
    frames = {}
    plates = {}
    for theme, background in THEME_BACKGROUNDS.items():
        scene = load("scene_fixed_stage.json")
        scene["visual"]["background_id"] = background
        video = studio.video(scene, theme=theme)
        frame, record = studio.compose(video, scene["id"])
        frames[theme] = frame.convert("RGB")
        plates[theme] = record["caption"]["plate"]
    # preview pixels: half of the 1080x1920 layout coordinates
    x, y, w, _ = plates["day"]
    areas = {
        "background": (60, 140, 480, 480),  # inside the fixed stage visual region
        "plate": (x // 2 + 10, y // 2, (x + w) // 2 - 10, y // 2 + 2),  # top pad
        "palette": (0, 640, 540, 960),  # plain theme background below the caption
    }
    themes = list(frames)
    for area, box in areas.items():
        for index, left in enumerate(themes):
            for right in themes[index + 1 :]:
                a = frames[left].crop(box).tobytes()
                b = frames[right].crop(box).tobytes()
                assert a != b, f"{area} is the same for {left} and {right}"


def test_29_caption_lines_stay_in_safe_area_and_line_limit(studio: Studio) -> None:
    for name, layout, mode, role in FIXTURE_SCENES:
        scene = load(name)
        video = studio.video(scene, layout=layout, mode=mode, role=role)
        _, record = studio.compose(video, scene["id"])
        _assert_safe(record)


def test_29_plate_follows_the_text_through_each_position(studio: Studio) -> None:
    for layout in POSITION_LAYOUTS:
        plate_rows = []
        for position in POSITIONS:
            scene = load("scene_fixed_stage.json")
            video = studio.video(scene, layout=layout, position=position)
            _, record = studio.compose(video, scene["id"])
            _assert_safe(record)
            plate_rows.append(record["caption"]["plate"][1])
        assert plate_rows == sorted(plate_rows)
        assert plate_rows[0] < plate_rows[-1]


def test_29_placed_caption_keeps_its_box_and_a_narrow_width(studio: Studio) -> None:
    """A reference plate at 0.55 of the frame width keeps both its x and its text."""
    scene = _caption_scene(ONE_LINE)
    place = CaptionPlace(x=48, y=600, w=round(0.55 * FRAME_WIDTH))
    video = studio.video(scene, place=place.model_dump(mode="json"))

    _, record = studio.compose(video, scene["id"])

    caption = record["caption"]
    block_height = caption["size"] * 5 // 4 * len(caption["lines"])
    expected = place_box(place, block_height)
    x, y, w, h = caption["plate"]
    assert abs(x - expected.x) <= 1
    assert abs(y - expected.y) <= 1
    assert abs(w - expected.w) <= 1
    assert abs(h - expected.h) <= 1
    assert caption["plate"] == [48, 600, 594, block_height + 8]
    for line in caption["lines"]:
        assert inside(_box(line["box"]), _box(caption["plate"]))
    assert inside(_box(caption["plate"]), place_area())


def test_29_placed_caption_keeps_the_side_pad_when_left_aligned(studio: Studio) -> None:
    scene = _caption_scene(ONE_LINE)
    place = {"x": 48, "y": 600, "w": 594, "align": "left"}
    video = studio.video(scene, place=place)

    _, record = studio.compose(video, scene["id"])

    plate = _box(record["caption"]["plate"])
    for line in record["caption"]["lines"]:
        box = _box(line["box"])
        assert box.x >= plate.x + PLATE_SIDE_PAD
        assert box.x + box.w <= plate.x + plate.w - PLATE_SIDE_PAD + 1


def _caption_scene(text: str) -> dict[str, Any]:
    scene = load("scene_fixed_stage.json")
    scene["lines"][0]["display_text"] = text
    scene["lines"][0]["speech_text"] = text
    scene["lines"][0]["highlight"] = []
    return scene


def _caption_frame(
    studio: Studio, layout: str, mode: str, text: str, position: str = "bottom"
) -> tuple[Image.Image, dict[str, Any]]:
    scene = _caption_scene(text)
    video = studio.video(scene, layout=layout, mode=mode, position=position)
    return studio.compose(video, scene["id"])


def _ink_gaps(frame: Image.Image, plate: list[int], skip: int) -> dict[str, int]:
    """Pixels between a plate and the text drawn on it, on each side.

    ``skip`` leaves out the plate's border ring. The plate colour is read left of the text.
    """
    x, y, w, h = plate
    pixels = np.asarray(frame.convert("RGB"))[y + skip : y + h - skip, x + skip : x + w - skip]
    fill = pixels[pixels.shape[0] // 2, 4]
    ys, xs = np.nonzero((pixels != fill).any(axis=2))
    return {
        "left": skip + int(xs.min()),
        "right": w - 2 * skip - 1 - int(xs.max()) + skip,
        "top": skip + int(ys.min()),
        "bottom": h - 2 * skip - 1 - int(ys.max()) + skip,
    }


def _bubble_skip(layout: str) -> int:
    return BUBBLE_OUTSET if layout == "dialog_stage" else 0


@pytest.mark.parametrize(("layout", "mode"), TEMPLATES)
@pytest.mark.parametrize(("text", "line_count"), [(ONE_LINE, 1), (TWO_LINES, 2)])
def test_29_caption_text_keeps_a_side_pad_and_sits_in_the_middle(
    studio: Studio, layout: str, mode: str, text: str, line_count: int
) -> None:
    frame, record = _caption_frame(studio, layout, mode, text)
    assert len(record["caption"]["lines"]) == line_count
    gaps = _ink_gaps(frame, record["caption"]["plate"], _bubble_skip(layout))
    assert min(gaps["left"], gaps["right"]) >= PLATE_SIDE_PAD
    assert abs(gaps["left"] - gaps["right"]) <= 2


def test_29_centred_text_is_centred_by_its_pixels_not_its_advance(studio: Studio) -> None:
    font = open_font(studio.registry, studio.video().settings.caption.font_id)
    block = fit(font, "본다.", None, width=400, height=200, max_lines=1, sizes=[44], where="t")
    (line,) = block.lines
    # a full stop leaves its right part of the advance empty
    assert line.ink is not None and line.ink[2] < line.width


@pytest.mark.parametrize(("text", "line_count"), [(ONE_LINE, 1), (TWO_LINES, 2)])
def test_29_dialog_bubble_follows_the_preset_and_centres_the_text(
    studio: Studio, text: str, line_count: int
) -> None:
    plates = []
    for position in POSITIONS:
        frame, record = _caption_frame(studio, "dialog_stage", "typewriter", text, position)
        _assert_safe(record)
        x, y, w, h = record["caption"]["plate"]
        assert len(record["caption"]["lines"]) == line_count
        gaps = _ink_gaps(frame, record["caption"]["plate"], BUBBLE_OUTSET)
        assert abs(gaps["top"] - gaps["bottom"]) <= 2
        assert (x, w) == (72, 936)
        plates.append(y)
    assert plates == sorted(set(plates))


def test_29_dialog_bubble_is_drawn_where_the_preset_puts_it(studio: Studio) -> None:
    for position in ("top", "bottom"):
        scene = load("scene_dialog_stage_typewriter.json")
        video = studio.video(scene, layout="dialog_stage", mode="typewriter", position=position)
        parts, layer = studio.inputs(video, scene["id"])
        frame, record = studio.service.compose(video, scene["id"], parts, layer)
        x, y, w, h = record["caption"]["plate"]
        tile = nine_slice(decode_png(parts["skin"], "skin"), w, h).convert("RGB")
        assert tile.size == (w, h)
        rim = BUBBLE_OUTSET
        for edge in ((0, 0, w, rim), (0, h - rim, w, h)):
            seen = frame.convert("RGB").crop((x + edge[0], y + edge[1], x + edge[2], y + edge[3]))
            assert seen.tobytes() == tile.crop(edge).tobytes()


def test_29_bubble_outset_is_the_skin_border() -> None:
    assert BUBBLE_OUTSET == CORNER_CELLS * SKIN_CELL


@pytest.mark.parametrize(("layout", "mode"), TEMPLATES)
def test_29_plates_and_frames_share_one_side_margin(studio: Studio, layout: str, mode: str) -> None:
    _, record = _caption_frame(studio, layout, mode, ONE_LINE)
    x, _, w, _ = record["caption"]["plate"]
    assert (x, FRAME_WIDTH - x - w) == (72, 72)
    if layout != "fixed_stage":
        return
    scene = _caption_scene(ONE_LINE)
    video = studio.video(scene, layout=layout, mode=mode)
    parts, _ = studio.inputs(video, scene["id"])
    _, meta = studio.layers.draw_layer(
        video.settings.format.layout, video.scenes[scene["id"]], (1080, 1920), parts, 0,
        cancel=Token(),
    )
    stage, title, progress = (meta["boxes"][name] for name in ("stage", "title", "progress"))
    assert (stage[0], FRAME_WIDTH - stage[0] - stage[2]) == (60, 60)
    assert (title[0], FRAME_WIDTH - title[0] - title[2]) == (60, 60)
    assert progress[0] == 60
    assert 1920 - (stage[1] + stage[3]) == 60
    assert (stage[0] + 12, FRAME_WIDTH - stage[0] - stage[2] + 12) == (72, 72)


@pytest.mark.parametrize(("layout", "mode"), TEMPLATES)
def test_29_picture_runs_down_into_the_platform_zone(
    studio: Studio, layout: str, mode: str
) -> None:
    scene = _caption_scene(ONE_LINE)
    video = studio.video(scene, layout=layout, mode=mode)
    frame, _ = studio.compose(video, scene["id"])
    manifest = studio.registry.get("template", layout)
    assert isinstance(manifest, TemplateManifest)
    picture = manifest.picture
    assert picture is not None
    assert picture.y + picture.h == (1848 if layout == "fixed_stage" else 1920)
    pixels = np.asarray(frame.convert("RGB"))
    zone = pixels[PLATFORM_ZONE_TOP : picture.y + picture.h, picture.x : picture.x + picture.w]
    # the empty frame was one flat colour down here
    assert (zone != zone[0, 0]).any()


@pytest.mark.parametrize(("layout", "mode"), TEMPLATES)
@pytest.mark.parametrize("anchor", ["top_left", "center", "middle_right"])
def test_29_character_keeps_its_pixel_size_and_feet_in_every_template(
    studio: Studio, layout: str, mode: str, anchor: str
) -> None:
    box, _ = _figure_box(studio, load("scene_fixed_stage.json"), anchor, layout=layout, mode=mode)
    assert box == OLD_FIGURE_BOXES[(layout, anchor)]


@pytest.mark.parametrize(("layout", "mode"), TEMPLATES)
def test_29_bottom_element_stays_above_the_caption_band(
    studio: Studio, layout: str, mode: str
) -> None:
    scene = _caption_scene(ONE_LINE)
    bare = studio.video(scene, layout=layout, mode=mode)
    scene["visual"]["elements"] = [
        {
            "id": "e_0nzvrzf0tp9wba44f6yvh6nzpr",
            "kind": "label",
            "value": "bottom",
            "anchor": "bottom",
            "reveal_line_id": None,
        }
    ]
    shown = studio.video(scene, layout=layout, mode=mode)
    parts, layer = studio.inputs(bare, scene["id"])
    with_label, _ = studio.service.compose(shown, scene["id"], parts, layer)
    without, _ = studio.service.compose(bare, scene["id"], parts, layer)
    box = ImageChops.difference(with_label.convert("RGB"), without.convert("RGB")).getbbox()
    assert box is not None
    assert box[3] <= SAFE_TOP


def test_29_long_identifier_wraps_by_glyph_width(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    text = "load_balancer_max_connections_per_worker"
    scene["lines"][0]["display_text"] = text
    scene["lines"][0]["highlight"] = []
    video = studio.video(scene)
    _, record = studio.compose(video, scene["id"])
    lines = [line["text"] for line in record["caption"]["lines"]]
    assert "".join(lines) == text
    assert len(lines) == 2
    _assert_safe(record)


def test_29_caption_that_cannot_fit_fails_instead_of_clipping(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    scene["lines"][0]["display_text"] = "아주 긴 자막 " * 30
    scene["lines"][0]["highlight"] = []
    video = studio.video(scene)
    with pytest.raises(AppError) as error:
        studio.compose(video, scene["id"])
    assert error.value.code == "text_overflow"


LONG_LABELS = ["가나다라마바사아자차" * 4, "Keeping plants from overheating now", "W" * 40]


@pytest.mark.parametrize("label", LONG_LABELS)
@pytest.mark.parametrize("layout", ["fixed_stage", "full_stage", "dialog_stage"])
@pytest.mark.parametrize("font", ["galmuri11", "galmuri14"])
def test_29_schema_valid_beat_label_renders_in_the_progress_box(
    studio: Studio, layout: str, label: str, font: str
) -> None:
    scene = load("scene_text_edge.json")
    scene["beat_label"] = label
    assert len(label) <= 40
    video = studio.video(scene, layout=layout, font=font)
    assert video.settings.format.progress_mode.value == "numbered"
    _, record = studio.compose(video, scene["id"])
    assert record is not None
    path = studio.still(video, scene["id"])
    assert path.exists()


def test_29_long_beat_label_is_cut_with_an_ellipsis_inside_the_box(studio: Studio) -> None:
    face = open_font(studio.registry, studio.registry.pin("font", "galmuri11"))
    label = "Keeping plants from overheating now"
    block = fit(
        face, label, None, width=236, height=56, max_lines=1,
        sizes=face.sizes(33, 22), where="progress", clip=True,
    )
    drawn = block.lines[0].text
    assert drawn.endswith(ELLIPSIS) and label.startswith(drawn[:-1])
    assert block.size == 22 and block.lines[0].width <= 236
    with pytest.raises(AppError) as caught:
        fit(
            face, label, None, width=236, height=56, max_lines=1,
            sizes=face.sizes(33, 22), where="progress",
        )
    assert caught.value.code == "text_overflow"


def test_29_missing_glyph_fails_without_font_fallback(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    scene["lines"][0]["display_text"] = "설명 \U0001f600 끝"
    scene["lines"][0]["highlight"] = []
    video = studio.video(scene)
    with pytest.raises(AppError) as error:
        studio.compose(video, scene["id"])
    assert error.value.code == "font_missing_glyph"
    assert error.value.detail["code_points"] == ["U+1F600"]


def test_29_decomposed_jamo_is_drawn_as_syllables(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    scene["lines"][0]["display_text"] = "\u1100\u1161\u11a8\u1109\u1175\u11ab 확인"
    scene["lines"][0]["highlight"] = [{"start": 0, "end": 3}]
    video = studio.video(scene)
    _, record = studio.compose(video, scene["id"])
    assert record["caption"]["lines"][0]["text"] == "각신 확인"


def test_14_highlight_is_underlined_not_only_coloured(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    marked = studio.video(scene)
    plain_scene = copy.deepcopy(scene)
    plain_scene["lines"][0]["highlight"] = []
    plain = studio.video(plain_scene)
    frame, record = studio.service.compose(marked, scene["id"], *studio.inputs(marked, scene["id"]))
    plain_frame, _ = studio.service.compose(
        plain, scene["id"], *studio.inputs(plain, scene["id"])
    )
    x, y, w, _ = record["caption"]["lines"][0]["box"]
    size = record["caption"]["size"]
    band = (x, y + size, x + w, y + size * 5 // 4)
    assert frame.crop(band).tobytes() != plain_frame.crop(band).tobytes()


def test_29_typewriter_needs_a_dialog_box_template(studio: Studio) -> None:
    scene = load("scene_dialog_stage_typewriter.json")
    video = studio.video(scene, layout="fixed_stage", mode="typewriter")
    with pytest.raises(AppError) as error:
        studio.still(video, scene["id"])
    assert error.value.code == "typewriter_layout"


def test_29_timing_artifact_replaces_the_estimate(studio: Studio) -> None:
    video = Video.model_validate(load("video_ko_just_three.json"))
    timing = Timing.model_validate(load("timing_sentence_fallback.json"))
    estimated = _record(studio.still(video, timing.scene_id, name="estimated"))
    measured_path = studio.still(video, timing.scene_id, timing, name="measured")
    measured = _record(measured_path)
    assert estimated["timing"]["source"] == "estimated"
    assert measured["timing"] == {
        "source": "artifact",
        "duration_ms": 2400,
        "lines": [{"line_id": timing.lines[0].line_id, "start_ms": 0, "end_ms": 2000}],
    }
    with Image.open(measured_path) as image:
        assert image.text["timing"] == "artifact"


def test_29_code_element_keeps_line_breaks_and_indent(studio: Studio) -> None:
    from app.services.render.text import fit, open_font

    video = studio.video(load("scene_fixed_stage.json"))
    font = open_font(studio.registry, video.settings.caption.font_id)
    source = "if ok:\n    x = 1\n\ny = 2"
    block = fit(
        font, source, None, width=600, height=1920, max_lines=8, sizes=[44, 33], where="t",
        code=True,
    )
    assert [line.text for line in block.lines] == ["if ok:", "    x = 1", "", "y = 2"]


def test_29_code_element_draws_left_aligned_lines(studio: Studio) -> None:
    scene = load("scene_fixed_stage.json")
    element = {
        "id": "e_0nzvrzf0tp9wba44f6yvh6nzpr",
        "kind": "code",
        "value": "a = 1\nb = 22",
        "anchor": "top",
        "reveal_line_id": None,
    }
    scene["visual"]["elements"] = [element]
    flat = copy.deepcopy(scene)
    flat["visual"]["elements"][0]["value"] = "a = 1 b = 22"
    frames = []
    for item in (scene, flat):
        video = studio.video(item)
        frame, _ = studio.service.compose(video, item["id"], *studio.inputs(video, item["id"]))
        frames.append(frame.crop((90, 260, 990, 600)).tobytes())
    assert frames[0] != frames[1]


@pytest.mark.parametrize(
    ("name", "layout", "mode", "place"),
    [
        ("scene_fixed_stage.json", "fixed_stage", "sentence", None),
        ("scene_fixed_stage.json", "fixed_stage", "sentence", {"x": 48, "y": 600, "w": 594}),
        ("scene_dialog_stage_typewriter.json", "dialog_stage", "typewriter", None),
    ],
)
def test_29_still_ignores_stored_second_caption(
    studio: Studio, name: str, layout: str, mode: str, place: dict[str, Any] | None
) -> None:
    plain_scene = load(name)
    legacy_scene = copy.deepcopy(plain_scene)
    legacy_scene["lines"][0]["extra_texts"] = [{"language": "en", "text": "Second caption."}]
    extra = {
        "font_id": studio.registry.pin("font", "galmuri14").model_dump(),
        "language": "en",
        "mode": "sentence",
        "position": "top",
    }
    scene_id = plain_scene["id"]
    plain = studio.video(plain_scene, layout=layout, mode=mode, place=place)
    legacy = studio.video(legacy_scene, layout=layout, mode=mode, place=place, extra=extra)

    plain_path = studio.still(plain, scene_id, name="plain")
    legacy_path = studio.still(legacy, scene_id, name="legacy")
    assert plain_path.read_bytes() == legacy_path.read_bytes()
    assert _record(plain_path) == _record(legacy_path)

    plain_frame, plain_record = studio.compose(plain, scene_id)
    legacy_frame, legacy_record = studio.compose(legacy, scene_id)
    assert plain_frame.tobytes() == legacy_frame.tobytes()
    assert plain_record == legacy_record


REFERENCES = Path(__file__).resolve().parent / "stills"
REFERENCE_CASES = [
    ("fixed_stage_day.png", "scene_fixed_stage.json", "fixed_stage", "sentence", "day", None),
    (
        "dialog_stage_arcade.png",
        "scene_dialog_stage_typewriter.json",
        "dialog_stage",
        "typewriter",
        "arcade",
        "bg_castle",
    ),
]


@pytest.mark.parametrize(("reference", "name", "layout", "mode", "theme", "background"),
                         REFERENCE_CASES)
def test_29_still_matches_reviewed_reference_png(
    studio: Studio,
    reference: str,
    name: str,
    layout: str,
    mode: str,
    theme: str,
    background: str | None,
) -> None:
    scene = load(name)
    if background is not None:
        scene["visual"]["background_id"] = background
    video = studio.video(scene, layout=layout, mode=mode, theme=theme)
    path = studio.still(video, scene["id"])
    with Image.open(path) as rendered, Image.open(REFERENCES / reference) as expected:
        assert rendered.convert("RGB").tobytes() == expected.convert("RGB").tobytes()
