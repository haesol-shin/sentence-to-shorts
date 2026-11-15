"""Scene still and clip rendering contract.

A still is laid out once on the 1080x1920 output frame and then reduced to the
540x960 preview, so the preview shows the same caption lines as the output.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
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
from app.schemas.scene import Anchor, Element, ElementKind, Scene
from app.schemas.settings import ProgressMode
from app.schemas.style_manifest import AssetKind, Palette, Theme
from app.schemas.template_manifest import TemplateManifest
from app.schemas.video import Video
from app.services.render.pixel import (
    PART_LAYERS,
    StylePackage,
    decode_png,
    open_style,
)
from app.services.render.sprites import rasterize
from app.services.render.text import CaptionFont, draw_block, fit, open_font

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

    def _character(
        self, frame: Image.Image, video: Video, scene: Scene, parts: dict[str, bytes], res: Resolved
    ) -> None:
        assert scene.visual is not None
        if not scene.visual.characters:
            return
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
        clip = Image.new("RGBA", (region.w, region.h), (0, 0, 0, 0))
        clip.alpha_composite(
            figure,
            (anchor.x - figure.width // 2 - region.x, anchor.y - figure.height - region.y),
        )
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

    def _elements(self, frame: Image.Image, scene: Scene, res: Resolved) -> list[str]:
        """Draw label, code and icon elements; return the ids that are not drawn."""
        assert scene.visual is not None
        region = res.template.regions.visual
        cursors: dict[Anchor, int] = {}
        skipped: list[str] = []
        width = region.w * 3 // 4
        for element in scene.visual.elements:
            if element.kind == ElementKind.material:
                skipped.append(element.id)
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
            frame.alpha_composite(image, (x, y))
        return skipped

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

    def _caption(
        self, frame: Image.Image, video: Video, scene: Scene, res: Resolved, framed: bool
    ) -> dict[str, Any]:
        caption = video.settings.caption
        region = res.template.regions.caption
        palette = res.palette
        draw = ImageDraw.Draw(frame)
        draw.fontmode = "1"
        if not framed:
            draw.rectangle(
                (region.x, region.y, region.x + region.w - 1, region.y + region.h - 1),
                fill=palette.caption_box,
            )
        inner = _inset(region, DIALOG_CAPTION_INSET if res.template.dialog_box else CAPTION_INSET)
        line = scene.lines[0]
        pixel = res.font.pixel_size or 12
        block = fit(
            res.font,
            line.display_text,
            line.highlight if caption.highlight else None,
            width=inner.w,
            height=inner.h,
            max_lines=CAPTION_MAX_LINES,
            sizes=res.font.sizes(pixel * 6, pixel * 2),
            where=f"caption:{line.id}",
        )
        valign = {"top": "top", "middle": "middle", "bottom": "bottom"}[caption.position.value]
        boxes = draw_block(
            draw, res.font, block, inner,
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

    def compose(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
    ) -> tuple[Image.Image, dict[str, Any]]:
        """The 1080x1920 frame of a scene and its layout record."""
        scene = video.scenes.get(scene_id)
        if scene is None:
            raise AppError("scene_not_found", detail={"scene_id": scene_id})
        if scene.visual is None:
            raise AppError("scene_visual_missing", detail={"scene_id": scene_id})
        res = self._resolve(video)
        frame = Image.new("RGBA", OUTPUT, (*_rgb(res.palette.bg), 255))
        self._background(frame, scene, res)
        if layer is not None:
            overlay = decode_png(layer, "layer")
            if overlay.size != OUTPUT:
                raise AppError("render_input_invalid", detail={"input": "layer", "reason": "size"})
            frame.alpha_composite(overlay)
        self._character(frame, video, scene, parts, res)
        skipped = self._elements(frame, scene, res)
        self._progress(frame, video, scene, res)
        self._title(frame, video, res)
        caption = self._caption(frame, video, scene, res, framed=layer is not None)
        record = {
            "scene_id": scene.id,
            "layout_size": list(OUTPUT),
            "caption": caption,
            "elements_not_drawn": skipped,
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
        """Write a silent mp4 clip to the job folder."""
        raise NotImplementedError


def create(settings: AppSettings, deps: ServiceDeps) -> RenderService:
    return RenderService(deps.media, deps.artifact_store, deps.catalog)


__all__ = ["RenderService", "create"]
