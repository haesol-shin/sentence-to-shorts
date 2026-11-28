"""Run caption painters in the sandbox and validate the returned geometry."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from app.caption_layout import inside
from app.ports import AppError, CancelToken, CatalogPort, SandboxPort, UnknownCatalogId
from app.schemas.caption_style_manifest import CaptionStyleManifest
from app.schemas.common import Box, PinnedRef
from app.schemas.sandbox_io import SandboxKind, SandboxLimits, SandboxRequest
from app.schemas.style_manifest import Palette
from app.services.render.pixel import decode_png
from app.services.render.text import TextBlock

_DEFAULT = "plate"
_CALL_LIMIT = 20


def caption_style_ref(catalog: CatalogPort, ref: PinnedRef | None) -> PinnedRef | None:
    if ref is not None:
        return ref
    try:
        return catalog.pin("caption_style", _DEFAULT)
    except UnknownCatalogId:
        return None


def caption_program(catalog: CatalogPort, ref: PinnedRef) -> str | None:
    try:
        manifest = catalog.get("caption_style", ref.id, ref.revision)
        path = catalog.package_dir("caption_style", ref)
        if isinstance(manifest, CaptionStyleManifest):
            return (path / manifest.renderer.program).read_text(encoding="utf-8")
    except (UnknownCatalogId, OSError, UnicodeError):
        pass
    return None


def _local_box(raw: object, bounds: Box) -> Box | None:
    if (
        not isinstance(raw, (tuple, list))
        or len(raw) != 4
        or not all(type(value) is int for value in raw)
    ):
        return None
    x, y, w, h = raw
    if min(x, y) < 0 or min(w, h) < 1:
        return None
    box = Box(x=x, y=y, w=w, h=h)
    return box if inside(box, bounds) else None


@dataclass(frozen=True)
class PaintedBox:
    image: Image.Image
    box: Box
    text_area: Box
    transparent: bool


def _validated_box(png: bytes, meta: dict[str, object], w: int, h: int) -> PaintedBox:
    image = decode_png(png, "caption_box")
    bounds = Box(x=0, y=0, w=w, h=h)
    box = _local_box(meta.get("box"), bounds)
    text_area = _local_box(meta.get("text_area"), bounds)
    alpha = image.getbbox()
    if image.size != (w, h) or text_area is None:
        raise AppError("sandbox_output_invalid", detail={"reason": "caption_geometry"})
    if alpha is None and meta.get("box") == [0, 0, 0, 0]:
        box = bounds
    if box is None or not inside(text_area, box):
        raise AppError("sandbox_output_invalid", detail={"reason": "caption_geometry"})
    if alpha is not None:
        x0, y0, x1, y1 = alpha
        if not inside(Box(x=x0, y=y0, w=x1 - x0, h=y1 - y0), box):
            raise AppError("sandbox_output_invalid", detail={"reason": "caption_pixels"})
    return PaintedBox(image=image, box=box, text_area=text_area, transparent=alpha is None)


class SceneBoxes:
    def __init__(self, program: str, sandbox: SandboxPort, cancel: CancelToken) -> None:
        self.program = program
        self.sandbox = sandbox
        self.cancel = cancel
        self.cache: dict[tuple[object, ...], PaintedBox | str] = {}

    def paint(self, plate: Box, block: TextBlock, palette: Palette, align: str) -> PaintedBox | str:
        w, h = plate.w, plate.h
        widths = tuple(max(1, line.width) for line in block.lines)
        key = (
            w, h, block.size, block.line_height, palette.caption_text, palette.caption_box,
            align, widths,
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if len(self.cache) == _CALL_LIMIT:
            return "caption_box_limit"
        request = SandboxRequest(
            protocol=1,
            request_id=f"{len(self.cache):016x}",
            kind=SandboxKind.caption_box,
            code=self.program,
            input={
                "plate": {"w": w, "h": h},
                "spec": {
                    "size_px": block.size,
                    "line_height": block.line_height,
                    "text_color": palette.caption_text,
                    "box_color": palette.caption_box,
                    "align": align,
                    "lines": [{"w": width, "h": block.line_height} for width in widths],
                },
                "canvas": {"width": w, "height": h},
            },
            assets=[],
            seed=0,
            limits=SandboxLimits(max_files=1, max_png_side=max(w, h, 16), max_wav_ms=500),
        )
        try:
            result = self.sandbox.run(request, cancel=self.cancel)
            png = result.files.get("box")
            meta = result.meta.get("program")
            if png is None or not isinstance(meta, dict):
                raise AppError("sandbox_output_invalid", detail={"reason": "caption_result"})
            rendered: PaintedBox | str = _validated_box(png, meta, w, h)
        except AppError as error:
            self.cancel.raise_if_set()
            rendered = error.code
        self.cache[key] = rendered
        return rendered


def translated(box: Box, x: int, y: int) -> Box:
    return Box(x=box.x + x, y=box.y + y, w=box.w, h=box.h)


def edges(box: Box) -> tuple[int, int, int, int]:
    return box.x, box.y, box.x + box.w, box.y + box.h


def _linear(byte: int) -> float:
    channel = byte / 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


_LINEAR = tuple(_linear(channel) for channel in range(256))


def _luminance(rgb: tuple[int, ...]) -> float:
    red, green, blue = rgb[:3]
    return 0.2126 * _LINEAR[red] + 0.7152 * _LINEAR[green] + 0.0722 * _LINEAR[blue]


def readable(backdrop: Image.Image, text_mask: Image.Image, rgb: tuple[int, int, int]) -> bool:
    """Check the composited pixels under the glyphs, not decorations or open corners."""
    text = _luminance(rgb) + 0.05
    bounds = text_mask.getbbox()
    if bounds is None:
        return True
    pixels = backdrop.load()
    mask = text_mask.load()
    assert pixels is not None and mask is not None
    left, top, right, bottom = bounds
    checked: dict[tuple[int, ...], bool] = {}
    for y in range(top, bottom):
        for x in range(left, right):
            if not mask[x, y][3]:
                continue
            pixel = pixels[x, y]
            if pixel not in checked:
                level = _luminance(pixel) + 0.05
                checked[pixel] = max(text, level) >= 4.5 * min(text, level)
            if not checked[pixel]:
                return False
    return True
