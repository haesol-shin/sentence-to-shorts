"""Scene still and clip rendering contract.

A still is laid out once on the 1080x1920 output frame and then reduced to the
540x960 preview. The still keeps the frame under the player's timed caption;
the clip draws the caption on every frame from the scene's timing.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, PngImagePlugin

from app.caption_layout import (
    CAPTION_MAX_LINES,
    PLATE_PAD,
    PLATE_SIDE_PAD,
    SAFE_HEIGHT,
    bubble_box,
    caption_inner,
    caption_text_size,
    draws_bubble,
    fixed_text_box,
    inside,
    place_pair,
    place_pair_with_primary,
    placed_box,
    plate_box,
    safe_area,
    separated,
    side_padded,
    text_box,
)
from app.ports import (
    FPS,
    AppError,
    AppSettings,
    ArtifactStore,
    CatalogPort,
    JobContext,
    MediaPort,
    SandboxPort,
    ServiceDeps,
    UnknownCatalogId,
)
from app.schemas.artifact import Timing
from app.schemas.caption_language_manifest import CaptionLanguageManifest
from app.schemas.common import Box, CaptionMode, CharacterRole
from app.schemas.scene import Anchor, Element, ElementKind, Scene
from app.schemas.script import Line, Span
from app.schemas.settings import CaptionLayer, CaptionPosition, ProgressMode
from app.schemas.style_manifest import AssetKind, Palette, Theme
from app.schemas.template_manifest import TemplateManifest
from app.schemas.video import Video
from app.services.render.caption_boxes import (
    SceneBoxes,
    caption_program,
    caption_style_ref,
    edges,
    readable,
    translated,
)
from app.services.render.layers import place_box
from app.services.render.motion import (
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
CAPTION_BLOCK_LIMIT = SAFE_HEIGHT - 2 * PLATE_PAD


def _fill_plate(draw: ImageDraw.ImageDraw, box: Box, color: str) -> None:
    draw.rectangle((box.x, box.y, box.x + box.w - 1, box.y + box.h - 1), fill=color)


def _caption_sizes(font: CaptionFont) -> list[int]:
    """Candidate caption sizes: six font pixels down to two."""
    pixel = font.pixel_size or 12
    return font.sizes(pixel * 6, pixel * 2)


def _caption_blocks(
    font: CaptionFont,
    text: str,
    highlight: list[Span] | None,
    *,
    width: int,
    height: int,
    max_lines: int,
    where: str,
) -> list[TextBlock | None]:
    """One layout per caption size; ``None`` where that size does not fit.

    Two layers choose their ranks together, so each size needs its own block
    before the joint search picks a pair.
    """
    blocks: list[TextBlock | None] = []
    for size in _caption_sizes(font):
        try:
            blocks.append(
                fit(
                    font,
                    text,
                    highlight,
                    width=width,
                    height=height,
                    max_lines=max_lines,
                    sizes=[size],
                    where=where,
                )
            )
        except AppError as error:
            if error.code != "text_overflow":
                raise
            blocks.append(None)
    return blocks

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
        lines.append(TextLine(units=shown, width=line.width, ink=line.ink))
    return TextBlock(size=block.size, line_height=block.line_height, lines=tuple(lines))


@dataclass(frozen=True)
class ResolvedLayer:
    """A second caption language: its catalog language, mode, font and position."""

    language: str
    mode: CaptionMode
    font: CaptionFont
    position: CaptionPosition


@dataclass(frozen=True)
class Resolved:
    """Catalog entries a still needs, resolved from the video's pinned refs."""

    style: StylePackage
    theme: Theme
    template: TemplateManifest
    font: CaptionFont
    extra: ResolvedLayer | None

    @property
    def palette(self) -> Palette:
        return self.theme.palette


def _caption_inner(res: Resolved) -> Box:
    """The plate area of a builtin plate template: the caption region without its insets."""
    return caption_inner(res.template.regions.caption, dialog=False)


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
    blocks: dict[tuple[str, int, tuple[int, int] | None], TextBlock] = field(
        default_factory=dict
    )
    candidates: dict[
        tuple[str, int, tuple[int, int] | None], list[TextBlock | None]
    ] = field(default_factory=dict)
    caption_fallback: str | None = None
    """Why the caption left its stored place: ``text_overflow`` or ``place_outside``."""
    caption_boxes: SceneBoxes | None = None


@dataclass(frozen=True)
class StyledCaption:
    plate: Box
    block: TextBlock
    lines: list[Box]
    box: Box | None


def _estimated_timing(scene: Scene) -> dict[str, Any]:
    """No measured timing yet. Expected lengths have one home, ``VoiceService.estimate_ms``,
    so the still records only that its timing is an estimate and draws the same frame."""
    return {"source": "estimated", "lines": [{"line_id": line.id} for line in scene.lines]}


def _artifact_timing(scene: Scene, timing: Timing) -> dict[str, Any]:
    line_ids = [line.id for line in scene.lines]
    if timing.scene_id != scene.id or [line.line_id for line in timing.lines] != line_ids:
        raise AppError("timing_mismatch", detail={"scene_id": scene.id})
    for line in timing.lines:
        if line.caption.mode_used is CaptionMode.typewriter and not line.caption.phrases:
            raise AppError(
                "timing_mismatch",
                detail={"scene_id": scene.id, "line_id": line.line_id},
            )
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
        self, media: MediaPort, artifacts: ArtifactStore, catalog: CatalogPort,
        sandbox: SandboxPort | None = None,
    ) -> None:
        self.media = media
        self.artifacts = artifacts
        self.catalog = catalog
        self.sandbox = sandbox

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
            extra=self._extra_layer(settings.caption.extra, template, style.manifest.fonts),
        )

    def _extra_layer(
        self, layers: list[CaptionLayer], template: TemplateManifest, fonts: list[str]
    ) -> ResolvedLayer | None:
        """Resolve the second caption language and reject a layer it cannot draw."""
        if not layers:
            return None
        layer = layers[0]
        if template.dialog_box or template.renderer.kind != "builtin":
            raise AppError(
                "caption_layer_unsupported", detail={"template": template.id}
            )
        if layer.mode is not CaptionMode.sentence:
            raise AppError(
                "caption_mode_language", detail={"mode": layer.mode.value}
            )
        try:
            language = self.catalog.get("caption_language", layer.language)
        except UnknownCatalogId as error:
            raise AppError(
                "unknown_catalog_id",
                detail={"kind": "caption_language", "id": layer.language},
            ) from error
        if not isinstance(language, CaptionLanguageManifest):
            raise AppError(
                "unknown_catalog_id",
                detail={"kind": "caption_language", "id": layer.language},
            )
        if layer.font_id.id not in fonts:
            raise AppError(
                "unknown_catalog_id", detail={"kind": "font", "id": layer.font_id.id}
            )
        return ResolvedLayer(
            language=layer.language,
            mode=layer.mode,
            font=open_font(self.catalog, layer.font_id),
            position=layer.position,
        )

    def _background(self, frame: Image.Image, scene: Scene, res: Resolved) -> None:
        assert scene.visual is not None
        sprite = res.style.sprite(scene.visual.background_id, {AssetKind.background})
        image = rasterize(sprite)
        region = res.template.picture or res.template.regions.visual
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
        anchor = res.template.character_anchors.point(scene.visual.characters[0].anchor)
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
            clip=not code,
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
            if x < 0 or y < 0 or not inside(placed, region):
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
            clip=True,
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
            clip=True,
        )
        draw_block(
            draw, res.font, block, inner,
            color=_rgb(res.palette.ink), highlight_color=_rgb(res.palette.accent),
        )

    @staticmethod
    def _extra_text(line: Line, language: str) -> str:
        """The line's text in the extra caption language."""

        for item in line.extra_texts:
            if item.language == language:
                return item.text
        raise AppError(
            "caption_text_missing", detail={"line_id": line.id, "language": language}
        )

    def _caption_text_width(self, plan: ScenePlan, layer: str) -> int:
        """Text width of one layer: the stored place wins over the template region."""
        caption = plan.video.settings.caption
        res = plan.res
        if (
            layer == "primary"
            and plan.caption_fallback is None
            and caption.place is not None
            and res.template.renderer.kind == "builtin"
            and not draws_bubble(res.template)
        ):
            return max(1, caption.place.w - 2 * PLATE_SIDE_PAD)
        return caption_text_size(res.template)[0]

    def _caption_block(
        self,
        plan: ScenePlan,
        line_index: int,
        phrase: tuple[int, int] | None,
        layer: str = "primary",
    ) -> TextBlock:
        """Lay out a whole line or one phrase of one caption layer once per clip."""
        key = (layer, line_index, phrase)
        block = plan.blocks.get(key)
        if block is not None:
            return block
        res = plan.res
        caption = plan.video.settings.caption
        line = plan.scene.lines[line_index]
        text_width = self._caption_text_width(plan, layer)
        if layer == "extra":
            assert res.extra is not None
            font = res.extra.font
            text = self._extra_text(line, res.extra.language)
            highlight: list[Span] | None = None
            height = CAPTION_BLOCK_LIMIT
            where = f"caption_extra:{line.id}"
        else:
            font = res.font
            text = line.display_text
            highlight = (
                list(line.highlight) if caption.highlight else []
            )
            if phrase is not None:
                text, highlight = _phrase_text(text, highlight, *phrase)
            wide = res.extra is not None or caption.place is not None
            height = CAPTION_BLOCK_LIMIT if wide else caption_text_size(res.template)[1]
            where = f"caption:{line.id}"
        block = self._fit_caption(
            plan, layer, font, text, highlight, text_width, height, where
        )
        plan.blocks[key] = block
        return block

    def _fit_caption(
        self,
        plan: ScenePlan,
        layer: str,
        font: CaptionFont,
        text: str,
        highlight: list[Span] | None,
        width: int,
        height: int,
        where: str,
    ) -> TextBlock:
        """Fit one block; a placed primary that cannot fit falls back to the band."""
        try:
            return fit(
                font,
                text,
                highlight or None,
                width=width,
                height=height,
                max_lines=CAPTION_MAX_LINES,
                sizes=_caption_sizes(font),
                where=where,
            )
        except AppError as error:
            if (
                error.code != "text_overflow"
                or layer != "primary"
                or plan.video.settings.caption.place is None
                or plan.caption_fallback is not None
            ):
                raise
            plan.caption_fallback = "text_overflow"
            return fit(
                font,
                text,
                highlight or None,
                width=caption_text_size(plan.res.template)[0],
                height=CAPTION_BLOCK_LIMIT,
                max_lines=CAPTION_MAX_LINES,
                sizes=_caption_sizes(font),
                where=where,
            )

    def _caption_candidates(
        self, plan: ScenePlan, layer: str, line_index: int, phrase: tuple[int, int] | None
    ) -> list[TextBlock | None]:
        """One layout per size rank, shared by the joint two-layer search."""
        key = (layer, line_index, phrase)
        cached = plan.candidates.get(key)
        if cached is not None:
            return cached
        res = plan.res
        line = plan.scene.lines[line_index]
        caption = plan.video.settings.caption
        text_width = self._caption_text_width(plan, layer)
        if layer == "extra":
            assert res.extra is not None
            font = res.extra.font
            text = self._extra_text(line, res.extra.language)
            highlight: list[Span] | None = None
            where = f"caption_extra:{line.id}"
        else:
            font = res.font
            text = line.display_text
            highlight = (
                list(line.highlight) if caption.highlight else []
            )
            if phrase is not None:
                text, highlight = _phrase_text(text, highlight, *phrase)
            where = f"caption:{line.id}"
        candidates = _caption_blocks(
            font,
            text,
            highlight or None,
            width=text_width,
            height=CAPTION_BLOCK_LIMIT,
            max_lines=CAPTION_MAX_LINES,
            where=where,
        )
        if (
            all(block is None for block in candidates)
            and layer == "primary"
            and caption.place is not None
            and plan.caption_fallback is None
        ):
            plan.caption_fallback = "text_overflow"
            candidates = _caption_blocks(
                font,
                text,
                highlight or None,
                width=caption_text_size(res.template)[0],
                height=CAPTION_BLOCK_LIMIT,
                max_lines=CAPTION_MAX_LINES,
                where=where,
            )
        plan.candidates[key] = candidates
        return candidates

    def _caption_pair(
        self,
        frame: Image.Image,
        draw: ImageDraw.ImageDraw,
        plan: ScenePlan,
        state: CaptionState,
        phrase: tuple[int, int] | None,
        *,
        visible: bool,
    ) -> dict[str, Any]:
        """Draw the primary and the extra language caption in one safe band.

        A stored place pins the primary plate. If no extra position keeps clear
        of it, the extra layer is dropped and the record says so: one chosen
        value does not fail the whole render.
        """
        caption = plan.video.settings.caption
        res = plan.res
        extra = res.extra
        assert extra is not None
        palette = res.palette
        line = plan.scene.lines[state.line]
        primary_blocks = self._caption_candidates(plan, "primary", state.line, phrase)
        extra_blocks = self._caption_candidates(plan, "extra", state.line, None)
        if not any(block is not None for block in primary_blocks):
            raise AppError(
                "text_overflow", detail={"where": f"caption:{line.id}", "font": res.font.id}
            )
        if not any(block is not None for block in extra_blocks):
            raise AppError(
                "text_overflow",
                detail={"where": f"caption_extra:{line.id}", "font": extra.font.id},
            )
        inner = _caption_inner(res)
        primary_heights = [None if block is None else block.height for block in primary_blocks]
        extra_heights = [None if block is None else block.height for block in extra_blocks]
        place = caption.place if plan.caption_fallback is None else None
        pair = None
        if place is not None:
            pair = place_pair_with_primary(
                inner, place, primary_heights, extra_heights, extra.position
            )
            if pair is None:
                largest = next(block for block in primary_blocks if block is not None)
                plate = placed_box(place, largest.height)
                if plate is not None:
                    return self._caption_alone(
                        frame, draw, plan, state, phrase, largest, plate, "no_room", visible
                    )
                plan.caption_fallback = "place_outside"
                place = None
        if pair is None:
            pair = place_pair(
                inner, primary_heights, caption.position, extra_heights, extra.position
            )
        if pair is None:
            raise AppError(
                "caption_overlap",
                detail={
                    "line_id": line.id,
                    "positions": [caption.position.value, extra.position.value],
                },
            )
        primary = primary_blocks[pair.primary_rank]
        extra_block = extra_blocks[pair.extra_rank]
        assert primary is not None and extra_block is not None
        primary_record, primary_plate = self._primary_plate(
            frame, draw, plan, state, phrase, primary, pair.primary,
            placed=place is not None, visible=visible,
        )
        if not separated(primary_plate, pair.extra):
            primary_record["caption_extra_skipped"] = "no_room"
            return primary_record
        _fill_plate(draw, pair.extra, palette.caption_box)
        extra_boxes = draw_block(
            draw, extra.font, extra_block, text_box(pair.extra, extra_block.height),
            color=_rgb(palette.caption_text), highlight_color=_rgb(palette.accent),
        )
        if not all(inside(box, pair.extra) for box in extra_boxes):
            raise AppError("caption_unsafe", detail={"line_id": line.id})
        primary_record["caption_extra"] = self._caption_record(
            line, extra_block, extra_boxes, pair.extra, extra.mode, extra.font,
            extra.position, extra.language,
        )
        return primary_record

    def _caption_alone(
        self,
        frame: Image.Image,
        draw: ImageDraw.ImageDraw,
        plan: ScenePlan,
        state: CaptionState,
        phrase: tuple[int, int] | None,
        block: TextBlock,
        plate: Box,
        reason: str,
        visible: bool,
    ) -> dict[str, Any]:
        record, _ = self._primary_plate(
            frame, draw, plan, state, phrase, block, plate, placed=True, visible=visible,
        )
        record["caption_extra_skipped"] = reason
        return record

    def _styled_caption(
        self,
        frame: Image.Image,
        plan: ScenePlan,
        state: CaptionState,
        phrase: tuple[int, int] | None,
        block: TextBlock,
        plate: Box,
        align: str,
        visible: bool,
    ) -> StyledCaption | str:
        painter = plan.caption_boxes
        if painter is None:
            return "no_ctx"
        palette = plan.res.palette
        candidate = block
        candidates: Iterator[TextBlock] | None = None
        while True:
            painted = painter.paint(plate, candidate, palette, align)
            if isinstance(painted, str):
                return painted
            area = painted.text_area
            fits = candidate.height <= area.h and all(
                line.width <= area.w for line in candidate.lines
            )
            boxes: list[Box] = []
            scratch = Image.new("RGBA", (plate.w, plate.h))
            shown = candidate if state.typed is None else _typed(candidate, state.typed)
            if fits:
                pen = ImageDraw.Draw(scratch)
                pen.fontmode = "1"
                boxes = self._draw_caption(
                    pen, plan.res.font, shown, area, align,
                    color=_rgb(palette.caption_text), highlight_color=_rgb(palette.accent),
                    side_pad=0,
                )
            if fits and all(inside(box, area) for box in boxes):
                if not painted.transparent:
                    backdrop = frame.crop(edges(plate))
                    backdrop.alpha_composite(painted.image)
                    if not readable(backdrop, scratch, _rgb(palette.caption_text)):
                        return "caption_contrast"
                if visible:
                    frame.alpha_composite(painted.image, (plate.x, plate.y))
                    frame.alpha_composite(scratch, (plate.x, plate.y))
                return StyledCaption(
                    plate, shown, [translated(box, plate.x, plate.y) for box in boxes],
                    None if painted.transparent else translated(painted.box, plate.x, plate.y),
                )
            if candidates is None:
                candidates = (
                    value for value in self._caption_candidates(plan, "primary", state.line, phrase)
                    if value is not None and value.size < block.size
                )
            candidate = next(candidates, None)
            if candidate is None:
                return "caption_text_area"

    def _primary_plate(
        self,
        frame: Image.Image,
        draw: ImageDraw.ImageDraw,
        plan: ScenePlan,
        state: CaptionState,
        phrase: tuple[int, int] | None,
        block: TextBlock,
        plate: Box,
        *,
        placed: bool,
        visible: bool,
    ) -> tuple[dict[str, Any], Box]:
        caption = plan.video.settings.caption
        res = plan.res
        line = plan.scene.lines[state.line]
        align = caption.place.align if placed and caption.place is not None else "center"
        reason = plan.caption_fallback
        result: StyledCaption | str | None = None
        if caption.style is not None and caption.style.id != "plate" and reason is None:
            result = self._styled_caption(frame, plan, state, phrase, block, plate, align, visible)
            if isinstance(result, str):
                reason = result
                block = self._band_block(plan, line, phrase)
                plate = plate_box(_caption_inner(res), block.height, caption.position)
                align = "center"
        if not isinstance(result, StyledCaption):
            if state.typed is not None:
                block = _typed(block, state.typed)
            _fill_plate(draw, plate, res.palette.caption_box)
            boxes = self._draw_caption(
                draw, res.font, block, text_box(plate, block.height), align,
                color=_rgb(res.palette.caption_text), highlight_color=_rgb(res.palette.accent),
            )
            if not all(inside(box, plate) for box in boxes):
                raise AppError("caption_unsafe", detail={"line_id": line.id})
            result = StyledCaption(plate, block, boxes, plate)
        record = self._caption_record(
            line, result.block, result.lines, result.plate, caption.mode, res.font,
            caption.position, None,
        )
        box = result.box
        record["box"] = None if box is None else [box.x, box.y, box.w, box.h]
        if reason is not None:
            record["caption_fallback"] = reason
            record["caption_message"] = "상자를 그리지 못해 기본 모양으로 내보냈어요"
        return record, result.plate

    @staticmethod
    def _band_block(plan: ScenePlan, line: Line, phrase: tuple[int, int] | None) -> TextBlock:
        caption = plan.video.settings.caption
        text = line.display_text
        highlight = list(line.highlight) if caption.highlight else []
        if phrase is not None:
            text, highlight = _phrase_text(text, highlight, *phrase)
        return fit(
            plan.res.font, text, highlight, width=caption_text_size(plan.res.template)[0],
            height=CAPTION_BLOCK_LIMIT, max_lines=CAPTION_MAX_LINES,
            sizes=_caption_sizes(plan.res.font), where=f"caption:{line.id}",
        )

    @staticmethod
    def _draw_caption(
        draw: ImageDraw.ImageDraw,
        font: CaptionFont,
        block: TextBlock,
        text: Box,
        align: str,
        *,
        color: tuple[int, int, int],
        highlight_color: tuple[int, int, int],
        side_pad: int = PLATE_SIDE_PAD,
    ) -> list[Box]:
        """Draw one block at the place alignment, inside ``text``.

        Left and right alignment keep the same side pad the wrapping uses, so a
        glyph is never drawn on the plate edge.
        """
        if align == "right":
            boxes: list[Box] = []
            right = text.x + text.w - side_pad
            top = text.y + max(0, text.h - block.height) // 2
            for line in block.lines:
                offset = line.ink[2] if line.ink is not None else line.width
                left = right - offset
                single = TextBlock(
                    size=block.size, line_height=block.line_height, lines=(line,)
                )
                boxes.extend(
                    draw_block(
                        draw, font, single,
                        Box(x=left, y=top, w=max(1, line.width), h=block.line_height),
                        color=color, highlight_color=highlight_color, align="left",
                    )
                )
                top += block.line_height
            return boxes
        if align == "left":
            text = Box(
                x=text.x + side_pad,
                y=text.y,
                w=max(1, text.w - 2 * side_pad),
                h=text.h,
            )
        return draw_block(
            draw, font, block, text,
            color=color, highlight_color=highlight_color,
            align="left" if align == "left" else "center",
        )

    @staticmethod
    def _caption_record(
        line: Line,
        block: TextBlock,
        boxes: list[Box],
        plate: Box,
        mode: CaptionMode,
        font: CaptionFont,
        position: CaptionPosition,
        language: str | None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "line_id": line.id,
            "mode": mode.value,
            "font": font.id,
            "position": position.value,
            "plate": [plate.x, plate.y, plate.w, plate.h],
            "size": block.size,
            "lines": [
                {"text": text_line.text, "box": [box.x, box.y, box.w, box.h]}
                for text_line, box in zip(block.lines, boxes, strict=True)
            ],
        }
        if language is not None:
            record["language"] = language
        return record

    def _caption(
        self,
        frame: Image.Image,
        plan: ScenePlan,
        state: CaptionState,
        *,
        draw: bool = True,
        ctx: JobContext | None = None,
    ) -> dict[str, Any]:
        """Lay out the caption; a still keeps the record but not the pixels."""
        caption = plan.video.settings.caption
        res = plan.res
        template = res.template
        region = template.regions.caption
        palette = res.palette
        target = frame if draw else Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        pen = ImageDraw.Draw(target)
        pen.fontmode = "1"
        line = plan.scene.lines[state.line]
        phrase = state.phrase
        if phrase is not None and not line.display_text[phrase[0]:phrase[1]].strip():
            phrase = None
        if res.extra is not None:
            return self._caption_pair(frame, pen, plan, state, phrase, visible=draw)
        block = self._caption_block(plan, state.line, phrase)
        if template.renderer.kind == "builtin" and not draws_bubble(template):
            return self._caption_builtin(frame, pen, plan, state, phrase, block, draw)
        if state.typed is not None:
            block = _typed(block, state.typed)
        valign = "middle"
        if draws_bubble(template):
            plate = bubble_box(region, caption.position)
            text = plate
            valign = "ink"
        else:
            plate = region
            inner = side_padded(caption_inner(region, dialog=template.dialog_box))
            text = fixed_text_box(inner, block.height, caption.position)
            if not plan.framed:
                pen.rectangle(
                    (region.x, region.y, region.x + region.w - 1, region.y + region.h - 1),
                    fill=palette.caption_box,
                )
        boxes = draw_block(
            pen, res.font, block, text, valign=valign,
            color=_rgb(palette.caption_text), highlight_color=_rgb(palette.accent),
        )
        if not inside(plate, safe_area()) or not all(inside(box, plate) for box in boxes):
            raise AppError("caption_unsafe", detail={"line_id": line.id})
        record = self._caption_record(
            line, block, boxes, plate, caption.mode, res.font, caption.position, None
        )
        if caption.style is not None or caption.place is not None:
            record["caption_message"] = (
                "이 무대는 말풍선을 씁니다" if draws_bubble(template)
                else "이 무대는 상자가 고정입니다"
            )
        return record

    def _caption_builtin(
        self,
        frame: Image.Image,
        pen: ImageDraw.ImageDraw,
        plan: ScenePlan,
        state: CaptionState,
        phrase: tuple[int, int] | None,
        block: TextBlock,
        visible: bool,
    ) -> dict[str, Any]:
        caption = plan.video.settings.caption
        plate = None
        if caption.place is not None and plan.caption_fallback is None:
            plate = placed_box(caption.place, block.height)
            if plate is None:
                plan.caption_fallback = "place_outside"
        placed = plate is not None
        if plate is None:
            plate = plate_box(_caption_inner(plan.res), block.height, caption.position)
        record, _ = self._primary_plate(
            frame, pen, plan, state, phrase, block, plate, placed=placed, visible=visible,
        )
        return record

    def _plan(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
        ctx: JobContext | None = None,
    ) -> ScenePlan:
        """Draw the layers that stay still for the whole scene once."""
        scene = video.scenes.get(scene_id)
        if scene is None:
            raise AppError("scene_not_found", detail={"scene_id": scene_id})
        if scene.visual is None:
            raise AppError("scene_visual_missing", detail={"scene_id": scene_id})
        res = self._resolve(video)
        painter = self._caption_painter(video, res, ctx)
        base = Image.new("RGBA", OUTPUT, (*_rgb(res.palette.bg), 255))
        self._background(base, scene, res)
        if layer is not None:
            overlay = decode_png(layer, "layer")
            if overlay.size != OUTPUT:
                raise AppError("render_input_invalid", detail={"input": "layer", "reason": "size"})
            base.alpha_composite(overlay)
        if draws_bubble(res.template):
            if "skin" not in parts:
                raise AppError(
                    "render_input_invalid", detail={"input": "skin", "reason": "missing"}
                )
            bubble = bubble_box(res.template.regions.caption, video.settings.caption.position)
            place_box(base, decode_png(parts["skin"], "skin"), bubble)
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
            caption_boxes=painter,
        )

    def _caption_painter(
        self, video: Video, res: Resolved, ctx: JobContext | None,
    ) -> SceneBoxes | None:
        if (
            ctx is None or self.sandbox is None or res.template.renderer.kind != "builtin"
            or draws_bubble(res.template)
        ):
            return None
        ref = caption_style_ref(self.catalog, video.settings.caption.style)
        if ref is None or ref.id == "plate":
            return None
        program = caption_program(self.catalog, ref)
        return SceneBoxes(program, self.sandbox, ctx.cancel) if program is not None else None

    def _draw(
        self, plan: ScenePlan, pose: Pose, *, draw_caption: bool = True,
        ctx: JobContext | None = None,
    ) -> tuple[Image.Image, dict[str, Any]]:
        """One 1080x1920 frame in the still's layer order: background and layer,
        character, elements, progress and title, caption, then the fade."""
        frame = plan.base.copy()
        self._paste_figure(frame, plan, pose)
        self._paste_elements(frame, plan, pose)
        if plan.top is not None:
            frame.alpha_composite(plan.top, plan.top_at)
        caption = self._caption(frame, plan, pose.caption, draw=draw_caption, ctx=ctx)
        if pose.fade < OPAQUE:
            black = Image.new("RGBA", OUTPUT, (0, 0, 0, 255))
            frame = Image.blend(black, frame, pose.fade / OPAQUE)
        return frame, caption

    def _rest(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
        *,
        captions: bool,
        ctx: JobContext | None = None,
    ) -> tuple[Image.Image, dict[str, Any]]:
        plan = self._plan(video, scene_id, parts, layer, ctx)
        frame, caption = self._draw(
            plan, rest_pose(plan.scene), draw_caption=captions, ctx=ctx
        )
        extra = caption.pop("caption_extra", None)
        record = {
            "scene_id": plan.scene.id,
            "layout_size": list(OUTPUT),
            "caption": caption,
            "elements_not_drawn": plan.skipped,
        }
        if extra is not None:
            record["caption_extra"] = extra
        return frame, record

    def compose(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
    ) -> tuple[Image.Image, dict[str, Any]]:
        """The 1080x1920 rest frame of a scene and its layout record."""
        return self._rest(video, scene_id, parts, layer, captions=True)

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

        The still is the frame under the player's timed caption: the screen and
        the clip draw the caption, so the PNG keeps none while the layout record
        still names its plate and lines. Without a timing artifact the record
        and the PNG text chunk say the timing is estimated.
        """
        ctx.cancel.raise_if_set()
        frame, record = self._rest(video, scene_id, parts, layer, captions=False, ctx=ctx)
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
        plan = self._plan(video, scene_id, parts, layer, ctx)
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
        travel = region.w if anchor is not None and anchor.value.endswith("right") else -region.w

        def frames() -> Iterator[bytes]:
            previous: Pose | None = None
            data = b""
            for pose in poses(scene, timing, typed_units, travel):
                ctx.cancel.raise_if_set()
                if pose != previous:
                    image, _ = self._draw(plan, pose, ctx=ctx)
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
    return RenderService(deps.media, deps.artifact_store, deps.catalog, deps.sandbox)


__all__ = ["RenderService", "create"]
