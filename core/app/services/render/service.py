"""Scene still and clip rendering contract.

A still is laid out once on the 1080x1920 output frame and then reduced to the
540x960 preview, so the preview shows the same caption lines as the output. A
clip draws every frame with the same function, posed by the scene's timing.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, PngImagePlugin

from app.ports import (
    AppError,
    AppSettings,
    ArtifactStore,
    CatalogPort,
    JobContext,
    MediaPort,
    ServiceDeps,
    UnknownCatalogId,
)
from app.schemas.artifact import Timing
from app.schemas.common import Box, CaptionMode, CharacterRole
from app.schemas.scene import Anchor, Element, ElementKind, PlacementAnchor, Scene
from app.schemas.script import Span
from app.schemas.settings import ProgressMode
from app.schemas.style_manifest import AssetKind, Palette, Theme
from app.schemas.template_manifest import TemplateManifest
from app.schemas.video import Video
from app.services.render.motion import (
    FPS,
    OPAQUE,
    SCALE_STEP,
    CaptionState,
    Pose,
    poses,
    rest_pose,
)
from app.services.render.pixel import (
    PART_LAYERS,
    StylePackage,
    decode_png,
    open_style,
)
from app.services.render.sprites import rasterize
from app.services.render.text import (
    CaptionFont,
    TextBlock,
    TextLine,
    draw_block,
    fit,
    open_font,
)

OUTPUT = (1080, 1920)
PREVIEW = (540, 960)
SAFE_CAPTION_TOP = 1030
SAFE_CAPTION_BOTTOM = 1230
CAPTION_MAX_LINES = 2
CAPTION_INSET = 24
DIALOG_CAPTION_INSET = 12
CHARACTER_HEIGHT_RATIO = (11, 20)
ELEMENT_MARGIN = 24
ELEMENT_PAD = 18
ELEMENT_OUTLINE = 6
ICON_CELL = 12
PROGRESS_FALLBACK = (24, 24, 312, 72)
STILL_DIR = "still"
CLIP_DIR = "clip"
LABEL_MAX_LINES = 3
CODE_MAX_LINES = 8


def _rgb(value: str) -> tuple[int, int, int]:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def _inset(box: Box, amount: int) -> Box:
    return Box(x=box.x + amount, y=box.y + amount, w=box.w - 2 * amount, h=box.h - 2 * amount)


def _contains(outer: Box, inner: Box) -> bool:
    return (
        inner.x >= outer.x
        and inner.y >= outer.y
        and inner.x + inner.w <= outer.x + outer.w
        and inner.y + inner.h <= outer.y + outer.h
    )


def _composite(dst: Image.Image, src: Image.Image, x: int, y: int) -> None:
    """``alpha_composite`` that also takes a position left of or above ``dst``."""
    left, top = max(0, -x), max(0, -y)
    if left >= src.width or top >= src.height:
        return
    if left or top:
        src = src.crop((left, top, src.width, src.height))
    dst.alpha_composite(src, (x + left, y + top))


def _phrase_text(
    text: str, highlight: list[Span], start: int, end: int
) -> tuple[str, list[Span]]:
    """One phrase of a line without its edge spaces, with highlights moved onto it."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    spans = [
        Span(start=max(span.start, start) - start, end=min(span.end, end) - start)
        for span in highlight
        if span.start < end and span.end > start
    ]
    return text[start:end], spans


def _typed(block: TextBlock, count: int) -> TextBlock:
    """The first ``count`` graphemes of a laid-out block. Lines keep their full
    width, so typed text stays where the finished line will be."""
    lines: list[TextLine] = []
    remaining = count
    for line in block.lines:
        shown = line.units[:max(0, remaining)]
        remaining -= len(line.units)
        lines.append(TextLine(units=shown, width=line.width))
    return TextBlock(size=block.size, line_height=block.line_height, lines=tuple(lines))


@dataclass(frozen=True)
class Resolved:
    """Catalog entries a still needs, resolved from the video's pinned refs."""

    style: StylePackage
    theme: Theme
    template: TemplateManifest
    font: CaptionFont

    @property
    def palette(self) -> Palette:
        return self.theme.palette


def _caption_inner(res: Resolved) -> Box:
    region = res.template.regions.caption
    return _inset(region, DIALOG_CAPTION_INSET if res.template.dialog_box else CAPTION_INSET)


@dataclass(frozen=True)
class PlacedElement:
    image: Image.Image
    x: int
    y: int


@dataclass
class ScenePlan:
    """Parts of a scene frame that stay the same while its clip plays."""

    video: Video
    scene: Scene
    res: Resolved
    framed: bool
    base: Image.Image
    figure: Image.Image | None
    figure_at: tuple[int, int]
    elements: list[PlacedElement | None]
    skipped: list[str]
    top: Image.Image | None
    top_at: tuple[int, int]
    blocks: dict[tuple[int, tuple[int, int] | None], TextBlock] = field(default_factory=dict)


def _estimated_timing(scene: Scene) -> dict[str, Any]:
    """No measured timing yet. Expected lengths have one home, ``VoiceService.estimate_ms``,
    so the still records only that its timing is an estimate and draws the same frame."""
    return {"source": "estimated", "lines": [{"line_id": line.id} for line in scene.lines]}


def _artifact_timing(scene: Scene, timing: Timing) -> dict[str, Any]:
    line_ids = [line.id for line in scene.lines]
    if timing.scene_id != scene.id or [line.line_id for line in timing.lines] != line_ids:
        raise AppError("timing_mismatch", detail={"scene_id": scene.id})
    return {
        "source": "artifact",
        "duration_ms": timing.duration_ms,
        "lines": [
            {"line_id": line.line_id, "start_ms": line.start_ms, "end_ms": line.end_ms}
            for line in timing.lines
        ],
    }


class RenderService:
    def __init__(
        self, media: MediaPort, artifacts: ArtifactStore, catalog: CatalogPort
    ) -> None:
        self.media = media
        self.artifacts = artifacts
        self.catalog = catalog

    def _resolve(self, video: Video) -> Resolved:
        settings = video.settings
        style = open_style(self.catalog, settings.visual.art_style)
        theme = style.theme(settings.visual.theme_id)
        layout = settings.format.layout
        try:
            template = self.catalog.get("template", layout.id, layout.revision)
        except UnknownCatalogId as error:
            raise AppError(
                "unknown_catalog_id", detail={"kind": "template", "id": layout.id}
            ) from error
        if not isinstance(template, TemplateManifest):
            raise AppError("unknown_catalog_id", detail={"kind": "template", "id": layout.id})
        font_ref = settings.caption.font_id
        if font_ref.id not in style.manifest.fonts:
            raise AppError("unknown_catalog_id", detail={"kind": "font", "id": font_ref.id})
        mode = settings.caption.mode
        if mode == CaptionMode.typewriter and not template.dialog_box:
            raise AppError("typewriter_layout", detail={"template": template.id})
        if mode not in template.caption_modes:
            raise AppError("caption_mode", detail={"template": template.id, "mode": mode})
        return Resolved(
            style=style,
            theme=theme,
            template=template,
            font=open_font(self.catalog, font_ref),
        )

    def _background(self, frame: Image.Image, scene: Scene, res: Resolved) -> None:
        assert scene.visual is not None
        sprite = res.style.sprite(scene.visual.background_id, {AssetKind.background})
        image = rasterize(sprite)
        region = res.template.regions.visual
        factor = max(math.ceil(region.w / image.width), math.ceil(region.h / image.height), 1)
        scaled = image.resize(
            (image.width * factor, image.height * factor), Image.Resampling.NEAREST
        )
        horizon = res.template.character_anchors.center.y
        top = horizon - scaled.height * horizon // OUTPUT[1]
        top = min(region.y, max(region.y + region.h - scaled.height, top))
        left = region.x + (region.w - scaled.width) // 2
        crop = scaled.crop(
            (region.x - left, region.y - top, region.x - left + region.w, region.y - top + region.h)
        )
        frame.alpha_composite(crop, (region.x, region.y))

    def _figure(
        self, video: Video, scene: Scene, parts: dict[str, bytes], res: Resolved
    ) -> tuple[Image.Image | None, tuple[int, int]]:
        """The scaled character and its rest position on the visual region."""
        assert scene.visual is not None
        if not scene.visual.characters:
            return None, (0, 0)
        if video.settings.format.character_role == CharacterRole.none:
            raise AppError("role_none_character", detail={"scene_id": scene.id})
        layers = [decode_png(parts[name], name) for name in PART_LAYERS if name in parts]
        if not layers or "body" not in parts:
            raise AppError("render_input_invalid", detail={"input": "parts", "reason": "missing"})
        size = layers[0].size
        if any(layer.size != size for layer in layers):
            raise AppError("render_input_invalid", detail={"input": "parts", "reason": "size"})
        figure = Image.new("RGBA", size, (0, 0, 0, 0))
        for layer in layers:
            figure.alpha_composite(layer)
        region = res.template.regions.visual
        target = region.h * CHARACTER_HEIGHT_RATIO[0] // CHARACTER_HEIGHT_RATIO[1]
        factor = max(1, target // figure.height)
        figure = figure.resize(
            (figure.width * factor, figure.height * factor), Image.Resampling.NEAREST
        )
        anchor = getattr(res.template.character_anchors, scene.visual.characters[0].anchor)
        rest = (anchor.x - figure.width // 2 - region.x, anchor.y - figure.height - region.y)
        return figure, rest

    def _paste_figure(self, frame: Image.Image, plan: ScenePlan, pose: Pose) -> None:
        """Draw the character clipped to the visual region, scaled from its feet."""
        if plan.figure is None or pose.figure_scale <= 0:
            return
        figure = plan.figure
        x, y = plan.figure_at
        if pose.figure_scale != SCALE_STEP:
            width = max(1, figure.width * pose.figure_scale // SCALE_STEP)
            height = max(1, figure.height * pose.figure_scale // SCALE_STEP)
            x += (figure.width - width) // 2
            y += figure.height - height
            figure = figure.resize((width, height), Image.Resampling.NEAREST)
        region = plan.res.template.regions.visual
        clip = Image.new("RGBA", (region.w, region.h), (0, 0, 0, 0))
        _composite(clip, figure, x + pose.figure_dx, y + pose.figure_dy)
        frame.alpha_composite(clip, (region.x, region.y))

    def _element_image(self, element: Element, res: Resolved, width: int) -> Image.Image:
        palette = res.palette
        if element.kind == ElementKind.asset:
            icon = res.style.sprite(element.value, {AssetKind.icon})
            return rasterize(icon, ICON_CELL)
        pixel = res.font.pixel_size or 12
        code = element.kind == ElementKind.code
        block = fit(
            res.font,
            element.value,
            None,
            width=width - 2 * ELEMENT_PAD - (ELEMENT_OUTLINE if code else 0),
            height=OUTPUT[1],
            max_lines=CODE_MAX_LINES if code else LABEL_MAX_LINES,
            sizes=res.font.sizes(pixel * 4, pixel * 2),
            where=f"element:{element.id}",
            code=code,
        )
        text_w = max(1, max(line.width for line in block.lines))
        box_w = text_w + 2 * ELEMENT_PAD + (ELEMENT_OUTLINE if code else 0)
        image = Image.new("RGBA", (box_w, block.height + 2 * ELEMENT_PAD), (0, 0, 0, 0))
        canvas = ImageDraw.Draw(image)
        canvas.fontmode = "1"
        outline = palette.accent if element.kind == ElementKind.label else palette.ink
        canvas.rectangle(
            (0, 0, image.width - 1, image.height - 1),
            fill=palette.caption_box,
            outline=outline,
            width=ELEMENT_OUTLINE,
        )
        inner = Box(x=ELEMENT_PAD, y=ELEMENT_PAD, w=box_w - 2 * ELEMENT_PAD, h=block.height)
        if code:
            canvas.rectangle(
                (0, 0, 2 * ELEMENT_OUTLINE - 1, image.height - 1), fill=palette.accent
            )
            inner = Box(x=inner.x + ELEMENT_OUTLINE, y=inner.y, w=inner.w - ELEMENT_OUTLINE,
                        h=inner.h)
        draw_block(
            canvas,
            res.font,
            block,
            inner,
            color=_rgb(palette.ink),
            highlight_color=_rgb(palette.accent),
            align="left" if code else "center",
        )
        return image

    def _place_elements(self, scene: Scene, res: Resolved) -> list[PlacedElement | None]:
        """Lay out label, code and icon elements; ``None`` marks an element not drawn."""
        assert scene.visual is not None
        region = res.template.regions.visual
        cursors: dict[Anchor, int] = {}
        placed_all: list[PlacedElement | None] = []
        width = region.w * 3 // 4
        for element in scene.visual.elements:
            if element.kind == ElementKind.material:
                placed_all.append(None)
                continue
            image = self._element_image(element, res, width)
            anchor = element.anchor
            if anchor == Anchor.left:
                x = region.x + ELEMENT_MARGIN
            elif anchor == Anchor.right:
                x = region.x + region.w - ELEMENT_MARGIN - image.width
            else:
                x = region.x + (region.w - image.width) // 2
            if anchor == Anchor.bottom:
                bottom = cursors.get(anchor, region.y + region.h - ELEMENT_MARGIN)
                y = bottom - image.height
                cursors[anchor] = y - ELEMENT_MARGIN
            else:
                start = region.y + (
                    ELEMENT_MARGIN if anchor == Anchor.top else region.h // 4
                )
                y = cursors.get(anchor, start)
                cursors[anchor] = y + image.height + ELEMENT_MARGIN
            placed = Box(x=max(0, x), y=max(0, y), w=image.width, h=image.height)
            if x < 0 or y < 0 or not _contains(region, placed):
                raise AppError("layout_overflow", detail={"element": element.id})
            placed_all.append(PlacedElement(image=image, x=x, y=y))
        return placed_all

    def _paste_elements(self, frame: Image.Image, plan: ScenePlan, pose: Pose) -> None:
        """Draw shown elements; a popping element grows from its own centre."""
        for placed, scale in zip(plan.elements, pose.elements, strict=True):
            if placed is None or scale is None or scale <= 0:
                continue
            image, x, y = placed.image, placed.x, placed.y
            if scale != SCALE_STEP:
                width = max(1, image.width * scale // SCALE_STEP)
                height = max(1, image.height * scale // SCALE_STEP)
                x += (image.width - width) // 2
                y += (image.height - height) // 2
                image = image.resize((width, height), Image.Resampling.NEAREST)
            _composite(frame, image, x, y)

    def _progress(self, frame: Image.Image, video: Video, scene: Scene, res: Resolved) -> None:
        if video.settings.format.progress_mode == ProgressMode.none:
            return
        palette = res.palette
        draw = ImageDraw.Draw(frame)
        draw.fontmode = "1"
        box = res.template.regions.progress
        if box is None:
            region = res.template.regions.visual
            x, y, w, h = PROGRESS_FALLBACK
            box = Box(x=region.x + x, y=region.y + y, w=w, h=h)
            draw.rectangle(
                (box.x, box.y, box.x + box.w - 1, box.y + box.h - 1),
                fill=palette.caption_box,
                outline=palette.accent,
                width=ELEMENT_OUTLINE,
            )
        inner = _inset(box, ELEMENT_OUTLINE)
        pixel = res.font.pixel_size or 12
        block = fit(
            res.font,
            scene.beat_label,
            None,
            width=inner.w,
            height=inner.h,
            max_lines=1,
            sizes=res.font.sizes(pixel * 3, pixel * 2),
            where="progress",
        )
        draw_block(
            draw, res.font, block, inner,
            color=_rgb(palette.accent), highlight_color=_rgb(palette.accent),
        )

    def _title(self, frame: Image.Image, video: Video, res: Resolved) -> None:
        box = res.template.regions.title
        title = video.script.title if video.script is not None else None
        if box is None or not title:
            return
        draw = ImageDraw.Draw(frame)
        draw.fontmode = "1"
        inner = _inset(box, 18)
        pixel = res.font.pixel_size or 12
        block = fit(
            res.font,
            title,
            None,
            width=inner.w,
            height=inner.h,
            max_lines=2,
            sizes=res.font.sizes(pixel * 5, pixel * 2),
            where="title",
        )
        draw_block(
            draw, res.font, block, inner,
            color=_rgb(res.palette.ink), highlight_color=_rgb(res.palette.accent),
        )

    def _caption_block(
        self, plan: ScenePlan, line_index: int, phrase: tuple[int, int] | None
    ) -> TextBlock:
        """Lay out a whole line or one phrase of it once per clip."""
        key = (line_index, phrase)
        block = plan.blocks.get(key)
        if block is not None:
            return block
        res = plan.res
        line = plan.scene.lines[line_index]
        text = line.display_text
        highlight = list(line.highlight) if plan.video.settings.caption.highlight else []
        if phrase is not None:
            text, highlight = _phrase_text(text, highlight, *phrase)
        inner = _caption_inner(res)
        pixel = res.font.pixel_size or 12
        block = fit(
            res.font,
            text,
            highlight or None,
            width=inner.w,
            height=inner.h,
            max_lines=CAPTION_MAX_LINES,
            sizes=res.font.sizes(pixel * 6, pixel * 2),
            where=f"caption:{line.id}",
        )
        plan.blocks[key] = block
        return block

    def _caption(self, frame: Image.Image, plan: ScenePlan, state: CaptionState) -> dict[str, Any]:
        caption = plan.video.settings.caption
        res = plan.res
        region = res.template.regions.caption
        palette = res.palette
        draw = ImageDraw.Draw(frame)
        draw.fontmode = "1"
        if not plan.framed:
            draw.rectangle(
                (region.x, region.y, region.x + region.w - 1, region.y + region.h - 1),
                fill=palette.caption_box,
            )
        line = plan.scene.lines[state.line]
        phrase = state.phrase
        if phrase is not None and not line.display_text[phrase[0]:phrase[1]].strip():
            phrase = None
        block = self._caption_block(plan, state.line, phrase)
        if state.typed is not None:
            block = _typed(block, state.typed)
        valign = {"top": "top", "middle": "middle", "bottom": "bottom"}[caption.position.value]
        boxes = draw_block(
            draw, res.font, block, _caption_inner(res),
            color=_rgb(palette.caption_text), highlight_color=_rgb(palette.accent),
            valign=valign,
        )
        safe = Box(x=0, y=SAFE_CAPTION_TOP, w=OUTPUT[0], h=SAFE_CAPTION_BOTTOM - SAFE_CAPTION_TOP)
        if not all(_contains(safe, box) and _contains(region, box) for box in boxes):
            raise AppError("caption_unsafe", detail={"line_id": line.id})
        return {
            "line_id": line.id,
            "mode": caption.mode.value,
            "font": res.font.id,
            "size": block.size,
            "lines": [
                {"text": text_line.text, "box": [box.x, box.y, box.w, box.h]}
                for text_line, box in zip(block.lines, boxes, strict=True)
            ],
        }

    def _plan(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
    ) -> ScenePlan:
        """Draw the layers that stay still for the whole scene once."""
        scene = video.scenes.get(scene_id)
        if scene is None:
            raise AppError("scene_not_found", detail={"scene_id": scene_id})
        if scene.visual is None:
            raise AppError("scene_visual_missing", detail={"scene_id": scene_id})
        res = self._resolve(video)
        base = Image.new("RGBA", OUTPUT, (*_rgb(res.palette.bg), 255))
        self._background(base, scene, res)
        if layer is not None:
            overlay = decode_png(layer, "layer")
            if overlay.size != OUTPUT:
                raise AppError("render_input_invalid", detail={"input": "layer", "reason": "size"})
            base.alpha_composite(overlay)
        figure, figure_at = self._figure(video, scene, parts, res)
        elements = self._place_elements(scene, res)
        top = Image.new("RGBA", OUTPUT, (0, 0, 0, 0))
        self._progress(top, video, scene, res)
        self._title(top, video, res)
        bbox = top.getbbox()
        return ScenePlan(
            video=video,
            scene=scene,
            res=res,
            framed=layer is not None,
            base=base,
            figure=figure,
            figure_at=figure_at,
            elements=elements,
            skipped=[
                element.id
                for element, placed in zip(scene.visual.elements, elements, strict=True)
                if placed is None
            ],
            top=top.crop(bbox) if bbox else None,
            top_at=(bbox[0], bbox[1]) if bbox else (0, 0),
        )

    def _draw(self, plan: ScenePlan, pose: Pose) -> tuple[Image.Image, dict[str, Any]]:
        """One 1080x1920 frame in the still's layer order: background and layer,
        character, elements, progress and title, caption, then the fade."""
        frame = plan.base.copy()
        self._paste_figure(frame, plan, pose)
        self._paste_elements(frame, plan, pose)
        if plan.top is not None:
            frame.alpha_composite(plan.top, plan.top_at)
        caption = self._caption(frame, plan, pose.caption)
        if pose.fade < OPAQUE:
            black = Image.new("RGBA", OUTPUT, (0, 0, 0, 255))
            frame = Image.blend(black, frame, pose.fade / OPAQUE)
        return frame, caption

    def compose(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
    ) -> tuple[Image.Image, dict[str, Any]]:
        """The 1080x1920 rest frame of a scene and its layout record."""
        plan = self._plan(video, scene_id, parts, layer)
        frame, caption = self._draw(plan, rest_pose(plan.scene))
        record = {
            "scene_id": plan.scene.id,
            "layout_size": list(OUTPUT),
            "caption": caption,
            "elements_not_drawn": plan.skipped,
        }
        return frame, record

    def still(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
        timing: Timing | None,
        *,
        ctx: JobContext,
    ) -> Path:
        """Write a 540x960 PNG still and its layout record to the job folder.

        Without a timing artifact the record and the PNG text chunk say the
        timing is estimated; the drawn frame is the first line's full caption.
        """
        ctx.cancel.raise_if_set()
        frame, record = self.compose(video, scene_id, parts, layer)
        scene = video.scenes[scene_id]
        record["timing"] = (
            _estimated_timing(scene)
            if timing is None
            else _artifact_timing(scene, timing)
        )
        record["size"] = list(PREVIEW)
        ctx.cancel.raise_if_set()
        preview = frame.convert("RGB").reduce(OUTPUT[0] // PREVIEW[0])
        out_dir = ctx.job_dir / STILL_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{scene_id}.png"
        info = PngImagePlugin.PngInfo()
        info.add_text("timing", record["timing"]["source"])
        preview.save(path, format="PNG", pnginfo=info, compress_level=6)
        path.with_suffix(".json").write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def clip(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
        timing: Timing,
        *,
        ctx: JobContext,
    ) -> Path:
        """Write a silent 1080x1920 30 fps mp4 of the scene to the job folder.

        Frames come from the still's drawing function, one pose per frame, and
        stream to the encoder one at a time; a frame equal to the previous one
        is sent again without drawing. The clip has ``frame_count`` frames of
        the timing's length and no audio track: sound joins at the final mux.
        """
        ctx.cancel.raise_if_set()
        plan = self._plan(video, scene_id, parts, layer)
        scene = plan.scene
        _artifact_timing(scene, timing)
        if any(line.end_ms > timing.duration_ms for line in timing.lines):
            raise AppError("timing_mismatch", detail={"scene_id": scene.id})
        # Lay out only what the clip shows, before encoding starts: a phrase line
        # shows its phrases, never the whole line, so a long line whose phrases
        # fit renders. A blank phrase falls back to the whole line.
        typed_units = []
        for index, line in enumerate(timing.lines):
            text = scene.lines[index].display_text
            spans = [(phrase.start_char, phrase.end_char) for phrase in line.caption.phrases]
            phrased = line.caption.mode_used == CaptionMode.phrase and bool(spans)
            shown = [span for span in spans if text[span[0]:span[1]].strip()] if phrased else []
            for span in shown:
                self._caption_block(plan, index, span)
            if phrased and len(shown) == len(spans):
                typed_units.append(0)
                continue
            block = self._caption_block(plan, index, None)
            typed_units.append(sum(len(text_line.units) for text_line in block.lines))
        region = plan.res.template.regions.visual
        assert scene.visual is not None
        anchor = scene.visual.characters[0].anchor if scene.visual.characters else None
        travel = region.w if anchor == PlacementAnchor.right else -region.w

        def frames() -> Iterator[bytes]:
            previous: Pose | None = None
            data = b""
            for pose in poses(scene, timing, typed_units, travel):
                ctx.cancel.raise_if_set()
                if pose != previous:
                    image, _ = self._draw(plan, pose)
                    data = image.convert("RGB").tobytes()
                    previous = pose
                yield data

        out_dir = ctx.job_dir / CLIP_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{scene_id}.mp4"
        self.media.encode_frames(
            frames(), width=OUTPUT[0], height=OUTPUT[1], fps=FPS, out=path, cancel=ctx.cancel
        )
        return path


def create(settings: AppSettings, deps: ServiceDeps) -> RenderService:
    return RenderService(deps.media, deps.artifact_store, deps.catalog)


__all__ = ["RenderService", "create"]
