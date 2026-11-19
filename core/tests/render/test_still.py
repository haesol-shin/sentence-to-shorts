"""Scene stills: fixture scenes, determinism, themes, caption safety and glyphs."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from app.caption_layout import inside, safe_area
from app.ports import AppError
from app.schemas.artifact import Timing
from app.schemas.common import Box
from app.schemas.video import Video
from tests.render.conftest import Studio, load

FIXTURE_SCENES = [
    ("scene_fixed_stage.json", "fixed_stage", "sentence", "presenter"),
    ("scene_full_stage.json", "full_stage", "phrase", "subject"),
    ("scene_dialog_stage_typewriter.json", "dialog_stage", "typewriter", "presenter"),
    ("scene_text_edge.json", "fixed_stage", "sentence", "presenter"),
]
POSITION_LAYOUTS = ["fixed_stage", "full_stage"]
POSITIONS = ["top", "upper", "middle", "lower", "bottom"]
THEME_BACKGROUNDS = {"day": "bg_village", "moonlight": "bg_city_night", "arcade": "bg_castle"}

TWO_LINE_KO_11 = (
    "커피를 고르는 기준은 세 가지뿐이다. "
    "좋은 원두와 물의 온도, 그리고 비율이 만든다. 정말로"
)
TWO_LINE_KO_14 = (
    "커피를 고르는 기준은 세 가지뿐이다. "
    "좋은 원두와 물의 온도, 그리고 비율이 만든다."
)
TWO_LINE_EN = (
    "The only criteria for choosing coffee are freshness, roast date, and grind size."
)
TWO_LAYER_SIZES = [
    ("galmuri11", TWO_LINE_KO_11, TWO_LINE_EN, "bottom", "top", (33, 33), (2, 2)),
    ("galmuri11", TWO_LINE_KO_11, TWO_LINE_EN, "upper", "lower", (22, 22), (2, 2)),
    ("galmuri11", "짧은 자막", "Short line", "bottom", "top", (66, 66), (1, 1)),
    ("galmuri14", TWO_LINE_KO_14, TWO_LINE_EN, "bottom", "top", (42, 28), (2, 2)),
    ("galmuri14", "짧은 자막", "Short line", "bottom", "top", (70, 70), (1, 1)),
]


def _extra(
    studio: Studio,
    font: str,
    position: str,
    *,
    language: str = "en",
    mode: str = "sentence",
) -> dict:
    return {
        "language": language,
        "mode": mode,
        "font_id": studio.registry.pin("font", font).model_dump(),
        "position": position,
    }


def _two_layer_scene(display_text: str, translated: str = TWO_LINE_EN) -> dict:
    scene = copy.deepcopy(load("scene_fixed_stage.json"))
    scene["lines"][0]["display_text"] = display_text
    scene["lines"][0]["speech_text"] = display_text
    scene["lines"][0]["extra_texts"] = [{"language": "en", "text": translated}]
    return scene


def _assert_layer_safe(caption: dict) -> None:
    plate = _box(caption["plate"])
    assert inside(plate, safe_area())
    for line in caption["lines"]:
        assert inside(_box(line["box"]), plate)


def _assert_extra_safe(record: dict) -> None:
    _assert_layer_safe(record["caption"])
    _assert_layer_safe(record["caption_extra"])
    gap = max(
        record["caption"]["plate"][1]
        - (record["caption_extra"]["plate"][1] + record["caption_extra"]["plate"][3]),
        record["caption_extra"]["plate"][1]
        - (record["caption"]["plate"][1] + record["caption"]["plate"][3]),
    )
    assert gap >= 8


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
    record = _record(path)
    assert record["caption"]["lines"][0]["text"] == video.scenes[video.scene_order[0]].lines[
        0
    ].display_text


def test_29_same_input_gives_same_png_digest(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    video = studio.video(scene)
    first = studio.still(video, scene["id"], name="first")
    second = studio.still(video, scene["id"], name="second")
    digest = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)]
    assert digest[0] == digest[1]


def test_6_theme_change_changes_background_box_and_palette(studio: Studio) -> None:
    frames = {}
    plates = {}
    for theme, background in THEME_BACKGROUNDS.items():
        scene = load("scene_fixed_stage.json")
        scene["visual"]["background_id"] = background
        video = studio.video(scene, theme=theme)
        path = studio.still(video, scene["id"], name=theme)
        frames[theme] = Image.open(path).convert("RGB")
        plates[theme] = _record(path)["caption"]["plate"]
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
        record = _record(studio.still(video, scene["id"], name=name))
        _assert_safe(record)


def test_29_plate_follows_the_text_through_each_position(studio: Studio) -> None:
    for layout in POSITION_LAYOUTS:
        plate_rows = []
        for position in POSITIONS:
            scene = load("scene_fixed_stage.json")
            video = studio.video(scene, layout=layout, position=position)
            path = studio.still(video, scene["id"], name=f"{layout}_{position}")
            record = _record(path)
            _assert_safe(record)
            plate_rows.append(record["caption"]["plate"][1])
        assert plate_rows == sorted(plate_rows)
        assert plate_rows[0] < plate_rows[-1]


def test_29_dialog_bubble_stays_while_the_text_moves(studio: Studio) -> None:
    frames, records = {}, {}
    for position in ("top", "bottom"):
        scene = load("scene_dialog_stage_typewriter.json")
        video = studio.video(scene, layout="dialog_stage", mode="typewriter", position=position)
        path = studio.still(video, scene["id"], name=position)
        frames[position] = Image.open(path).convert("RGB")
        records[position] = _record(path)
    bubble = (61, 521, 479, 530)  # preview rows of the speech bubble's top border
    assert frames["top"].crop(bubble).tobytes() == frames["bottom"].crop(bubble).tobytes()
    assert records["top"]["caption"]["plate"] == records["bottom"]["caption"]["plate"]
    top_line = records["top"]["caption"]["lines"][0]["box"]
    bottom_line = records["bottom"]["caption"]["lines"][0]["box"]
    assert top_line[1] < bottom_line[1]
    for record in records.values():
        _assert_safe(record)


def test_29_long_identifier_wraps_by_glyph_width(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    text = "load_balancer_max_connections_per_worker"
    scene["lines"][0]["display_text"] = text
    scene["lines"][0]["highlight"] = []
    video = studio.video(scene)
    record = _record(studio.still(video, scene["id"]))
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
        studio.still(video, scene["id"])
    assert error.value.code == "text_overflow"


def test_29_missing_glyph_fails_without_font_fallback(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    scene["lines"][0]["display_text"] = "설명 \U0001f600 끝"
    scene["lines"][0]["highlight"] = []
    video = studio.video(scene)
    with pytest.raises(AppError) as error:
        studio.still(video, scene["id"])
    assert error.value.code == "font_missing_glyph"
    assert error.value.detail["code_points"] == ["U+1F600"]


def test_29_decomposed_jamo_is_drawn_as_syllables(studio: Studio) -> None:
    scene = load("scene_text_edge.json")
    scene["lines"][0]["display_text"] = "\u1100\u1161\u11a8\u1109\u1175\u11ab 확인"
    scene["lines"][0]["highlight"] = [{"start": 0, "end": 3}]
    video = studio.video(scene)
    record = _record(studio.still(video, scene["id"]))
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
    (
        "font",
        "display",
        "translated",
        "primary_position",
        "extra_position",
        "sizes",
        "line_counts",
    ),
    TWO_LAYER_SIZES,
)
def test_29_two_layers_share_the_safe_band(
    studio: Studio,
    font: str,
    display: str,
    translated: str,
    primary_position: str,
    extra_position: str,
    sizes: tuple[int, int],
    line_counts: tuple[int, int],
) -> None:
    scene = _two_layer_scene(display, translated)
    video = studio.video(
        scene,
        font=font,
        position=primary_position,
        extra=_extra(studio, font, extra_position),
    )
    record = _record(studio.still(video, scene["id"]))
    caption = record["caption"]
    extra = record["caption_extra"]
    assert (caption["size"], extra["size"]) == sizes
    assert (len(caption["lines"]), len(extra["lines"])) == line_counts
    assert (extra["language"], extra["font"], extra["position"]) == (
        "en",
        font,
        extra_position,
    )
    _assert_extra_safe(record)


@pytest.mark.parametrize(
    ("font", "display", "primary_position", "extra_position"),
    [
        ("galmuri14", TWO_LINE_KO_14, "upper", "lower"),
        ("galmuri11", TWO_LINE_KO_11, "middle", "bottom"),
        ("galmuri11", TWO_LINE_KO_11, "top", "middle"),
    ],
)
def test_29_two_layer_positions_that_collide_fail(
    studio: Studio,
    font: str,
    display: str,
    primary_position: str,
    extra_position: str,
) -> None:
    scene = _two_layer_scene(display)
    video = studio.video(
        scene,
        font=font,
        position=primary_position,
        extra=_extra(studio, font, extra_position),
    )
    with pytest.raises(AppError) as error:
        studio.still(video, scene["id"])
    assert error.value.code == "caption_overlap"


def test_29_two_layers_need_the_second_language_text(studio: Studio) -> None:
    scene = _two_layer_scene(TWO_LINE_KO_11)
    del scene["lines"][0]["extra_texts"]
    video = studio.video(scene, extra=_extra(studio, "galmuri11", "top"))
    with pytest.raises(AppError) as error:
        studio.still(video, scene["id"])
    assert error.value.code == "caption_text_missing"


def test_29_two_layers_need_a_moving_plate_template(studio: Studio) -> None:
    scene = load("scene_dialog_stage_typewriter.json")
    scene["lines"][0]["extra_texts"] = [{"language": "en", "text": "Second."}]
    video = studio.video(
        scene,
        layout="dialog_stage",
        mode="typewriter",
        extra=_extra(studio, "galmuri11", "top"),
    )
    with pytest.raises(AppError) as error:
        studio.still(video, scene["id"])
    assert error.value.code == "caption_layer_unsupported"


def test_29_two_layers_need_a_sentence_second_layer(studio: Studio) -> None:
    scene = _two_layer_scene(TWO_LINE_KO_11)
    video = studio.video(
        scene,
        extra=_extra(studio, "galmuri11", "top", mode="phrase"),
    )
    with pytest.raises(AppError) as error:
        studio.still(video, scene["id"])
    assert error.value.code == "caption_mode_language"


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
