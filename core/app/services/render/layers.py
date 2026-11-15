"""Builtin template modules: one RGBA layer with the regions and the theme box skin.

The skin arrives as the ``skin`` part, a grid image with one pixel per cell.
It is drawn as a nine-slice box: the outer three cells on each side keep their
shape and the centre cell fills the inside.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from app.ports import AppError, CancelToken, CatalogPort, UnknownCatalogId
from app.schemas.common import Box, PinnedRef
from app.schemas.scene import Scene
from app.schemas.template_manifest import TemplateManifest
from app.services.render.pixel import decode_png, encode_png

FRAME = (1080, 1920)
SKIN_CELL = 6
CORNER_CELLS = 3
STAGE_OUTSET = 2 * SKIN_CELL
DIALOG_OUTSET = 3 * SKIN_CELL
BUILTIN_TEMPLATE_MODULES = ("fixed_stage", "full_stage", "dialog_stage")


def _source_index(index: int, count: int, size: int) -> int:
    if index < CORNER_CELLS:
        return index
    if index >= count - CORNER_CELLS:
        return size - (count - index)
    return size // 2


def nine_slice(skin: Image.Image, width: int, height: int, *, hollow: bool = False) -> Image.Image:
    """Grow the skin grid to ``width`` x ``height`` pixels at ``SKIN_CELL`` per cell."""
    if skin.width < 2 * CORNER_CELLS + 1 or skin.height < 2 * CORNER_CELLS + 1:
        raise AppError("render_input_invalid", detail={"input": "skin", "reason": "too_small"})
    cols = max(2 * CORNER_CELLS + 1, width // SKIN_CELL)
    rows = max(2 * CORNER_CELLS + 1, height // SKIN_CELL)
    grid = Image.new("RGBA", (cols, rows), (0, 0, 0, 0))
    for row in range(rows):
        source_row = _source_index(row, rows, skin.height)
        for col in range(cols):
            inside = CORNER_CELLS <= row < rows - CORNER_CELLS and (
                CORNER_CELLS <= col < cols - CORNER_CELLS
            )
            if hollow and inside:
                continue
            source_col = _source_index(col, cols, skin.width)
            grid.putpixel((col, row), skin.getpixel((source_col, source_row)))
    return grid.resize((cols * SKIN_CELL, rows * SKIN_CELL), Image.Resampling.NEAREST)


def _place(layer: Image.Image, skin: Image.Image, box: Box, *, hollow: bool = False) -> list[int]:
    tile = nine_slice(skin, box.w, box.h, hollow=hollow)
    left = box.x + (box.w - tile.width) // 2
    top = box.y + (box.h - tile.height) // 2
    layer.alpha_composite(tile, (left, top))
    return [left, top, tile.width, tile.height]


def _outset(box: Box, amount: int) -> Box:
    x = max(0, box.x - amount)
    y = max(0, box.y - amount)
    return Box(
        x=x,
        y=y,
        w=min(FRAME[0], box.x + box.w + amount) - x,
        h=min(FRAME[1], box.y + box.h + amount) - y,
    )


class BuiltinLayerDrawer:
    """``LayerDrawer`` for the builtin ``fixed_stage``, ``full_stage`` and ``dialog_stage``."""

    def __init__(self, catalog: CatalogPort) -> None:
        self.catalog = catalog

    def _manifest(self, ref: PinnedRef) -> TemplateManifest:
        try:
            manifest = self.catalog.get("template", ref.id, ref.revision)
        except UnknownCatalogId as error:
            raise AppError(
                "unknown_catalog_id", detail={"kind": "template", "id": ref.id}
            ) from error
        if (
            not isinstance(manifest, TemplateManifest)
            or manifest.renderer.kind != "builtin"
            or manifest.renderer.module not in BUILTIN_TEMPLATE_MODULES
        ):
            raise AppError("unknown_catalog_id", detail={"kind": "template", "id": ref.id})
        return manifest

    def draw_layer(
        self,
        template: PinnedRef,
        scene: Scene,
        canvas: tuple[int, int],
        parts: dict[str, bytes],
        seed: int,
        *,
        cancel: CancelToken,
    ) -> tuple[bytes | None, dict[str, Any]]:
        """Draw boxes for the template regions; ``seed`` does not change builtin layers."""
        cancel.raise_if_set()
        if tuple(canvas) != FRAME:
            raise AppError("render_input_invalid", detail={"input": "canvas"})
        manifest = self._manifest(template)
        if "skin" not in parts:
            raise AppError("render_input_invalid", detail={"input": "skin", "reason": "missing"})
        skin = decode_png(parts["skin"], "skin")
        regions = manifest.regions
        layer = Image.new("RGBA", FRAME, (0, 0, 0, 0))
        boxes: dict[str, list[int]] = {}
        module = manifest.renderer.module
        if module == "fixed_stage":
            boxes["stage"] = _place(layer, skin, _outset(regions.visual, STAGE_OUTSET), hollow=True)
            for name in ("title", "progress"):
                region = getattr(regions, name)
                if region is not None:
                    boxes[name] = _place(layer, skin, region)
        if module == "dialog_stage":
            boxes["caption"] = _place(layer, skin, _outset(regions.caption, DIALOG_OUTSET))
        else:
            boxes["caption"] = _place(layer, skin, regions.caption)
        return encode_png(layer), {"module": module, "boxes": boxes}


__all__ = ["BUILTIN_TEMPLATE_MODULES", "BuiltinLayerDrawer", "nine_slice"]
