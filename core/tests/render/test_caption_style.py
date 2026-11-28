"""Caption styles: sandbox-drawn plates, the four checks and the band fallback."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from app.caption_layout import inside
from app.ports import AppError, ValidatedOutput
from app.schemas.common import Box, PinnedRef
from app.services.render import RenderService
from app.services.render.motion import rest_pose
from tests.render.conftest import Ctx, Studio, Token, load

TEXT = "짧은 자막"
Painter = Callable[[dict[str, Any]], tuple[Image.Image, dict[str, Any]]]


class Catalog:
    """The real registry plus one more caption style, ``round``, that reuses the plate package."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def get(self, kind: str, item_id: str, revision: str | None = None) -> Any:
        if kind == "caption_style" and item_id == "round":
            return self.inner.get(kind, "plate").model_copy(update={"id": "round"})
        return self.inner.get(kind, item_id, revision)

    def package_dir(self, kind: str, ref: PinnedRef) -> Path:
        if kind == "caption_style" and ref.id == "round":
            return self.inner.package_dir(kind, self.inner.pin(kind, "plate"))
        return self.inner.package_dir(kind, ref)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class Sandbox:
    def __init__(self, painter: Painter) -> None:
        self.painter = painter
        self.calls = 0

    def run(self, request: Any, *, cancel: Any) -> ValidatedOutput:
        self.calls += 1
        image, meta = self.painter(request.input)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return ValidatedOutput(files={"box": buffer.getvalue()}, meta={"program": meta})


def rounded(spec_input: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    plate = spec_input["plate"]
    w, h = plate["w"], plate["h"]
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle(
        (0, 0, w - 1, h - 1), 12, fill=spec_input["spec"]["box_color"]
    )
    return image, {"box": [0, 0, w, h], "text_area": [8, 4, w - 16, h - 8]}


def _scene() -> dict[str, Any]:
    scene = load("scene_fixed_stage.json")
    scene["lines"][0]["display_text"] = TEXT
    scene["lines"][0]["speech_text"] = TEXT
    scene["lines"][0]["highlight"] = []
    return scene


def _still(studio: Studio, painter: Painter, **kwargs: Any) -> tuple[dict[str, Any], Sandbox]:
    sandbox = Sandbox(painter)
    catalog = Catalog(studio.registry)
    studio.service = RenderService(None, None, catalog, sandbox)  # type: ignore[arg-type]
    scene = _scene()
    ref = catalog.inner.pin("caption_style", "plate").model_dump()
    video = studio.video(scene, style={**ref, "id": "round"}, **kwargs)
    path = studio.still(video, scene["id"])
    return json.loads(path.with_suffix(".json").read_text(encoding="utf-8")), sandbox


def _box(values: list[int]) -> Box:
    return Box(x=values[0], y=values[1], w=values[2], h=values[3])


def test_caption_style_box_is_drawn_by_the_program_and_recorded(studio: Studio) -> None:
    record, sandbox = _still(studio, rounded)
    caption = record["caption"]
    assert sandbox.calls == 1
    assert "caption_fallback" not in caption
    assert caption["box"] == caption["plate"]
    for line in caption["lines"]:
        assert inside(_box(line["box"]), _box(caption["plate"]))


def test_caption_style_failed_program_falls_back_to_the_band_with_a_message(
    studio: Studio,
) -> None:
    def broken(_: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
        raise AppError("sandbox_timeout")

    record, _ = _still(studio, broken)
    assert record["caption"]["caption_fallback"] == "sandbox_timeout"
    assert record["caption"]["caption_message"]


def test_caption_style_text_outside_the_text_area_falls_back(studio: Studio) -> None:
    def tiny(spec_input: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
        image, meta = rounded(spec_input)
        meta["text_area"] = [0, 0, 4, 4]
        return image, meta

    record, _ = _still(studio, tiny)
    assert record["caption"]["caption_fallback"] == "caption_text_area"


def test_caption_style_low_contrast_falls_back(studio: Studio) -> None:
    def same_colour(spec_input: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
        image, meta = rounded(spec_input)
        image.paste(spec_input["spec"]["text_color"], (0, 0, image.width, image.height))
        return image, meta

    record, _ = _still(studio, same_colour)
    assert record["caption"]["caption_fallback"] == "caption_contrast"


def test_caption_style_no_box_skips_the_contrast_check(studio: Studio) -> None:
    def nothing(spec_input: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
        plate = spec_input["plate"]
        return (
            Image.new("RGBA", (plate["w"], plate["h"]), (0, 0, 0, 0)),
            {"box": [0, 0, 0, 0], "text_area": [0, 0, plate["w"], plate["h"]]},
        )

    record, _ = _still(studio, nothing)
    assert "caption_fallback" not in record["caption"]
    assert record["caption"]["box"] is None


def test_caption_style_still_and_clip_share_the_box_coordinates(studio: Studio) -> None:
    """The still record and a clip frame are drawn by one function, fallback included."""
    sandbox = Sandbox(rounded)
    catalog = Catalog(studio.registry)
    studio.service = RenderService(None, None, catalog, sandbox)  # type: ignore[arg-type]
    scene = _scene()
    ref = catalog.inner.pin("caption_style", "plate").model_dump()
    video = studio.video(scene, style={**ref, "id": "round"})
    parts, layer = studio.inputs(video, scene["id"])
    ctx = Ctx(job_dir=studio.root / "job", cancel=Token())
    plan = studio.service._plan(video, scene["id"], parts, layer, ctx)
    _, first = studio.service._draw(plan, rest_pose(plan.scene), ctx=ctx)
    _, second = studio.service._draw(plan, rest_pose(plan.scene), ctx=ctx)
    assert first["box"] == second["box"] == first["plate"]
    still = json.loads(studio.still(video, scene["id"]).with_suffix(".json").read_text("utf-8"))
    assert still["caption"]["box"] == first["box"]


def test_default_band_is_used_without_a_place(studio: Studio) -> None:
    scene = _scene()
    video = studio.video(scene)
    _, record = studio.compose(video, scene["id"])
    _, y, _, h = record["caption"]["plate"]
    assert 1030 <= y and y + h <= 1230
    assert "caption_fallback" not in record["caption"]


def test_caption_without_ctx_uses_the_default_band(studio: Studio) -> None:
    sandbox = Sandbox(rounded)
    catalog = Catalog(studio.registry)
    studio.service = RenderService(None, None, catalog, sandbox)  # type: ignore[arg-type]
    scene = _scene()
    ref = catalog.inner.pin("caption_style", "plate").model_dump()
    video = studio.video(scene, style={**ref, "id": "round"})
    _, record = studio.compose(video, scene["id"])
    assert record["caption"]["caption_fallback"] == "no_ctx"
    assert sandbox.calls == 0


def test_right_aligned_place_keeps_the_side_pad(studio: Studio) -> None:
    scene = _scene()
    video = studio.video(scene, place={"x": 48, "y": 600, "w": 594, "align": "right"})
    _, record = studio.compose(video, scene["id"])
    x, _, w, _ = record["caption"]["plate"]
    for line in record["caption"]["lines"]:
        box_x, _, box_w, _ = line["box"]
        assert box_x + box_w <= x + w
        assert box_x > x + (w - box_w) // 2 + 20

