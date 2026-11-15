"""Store generated style assets in the sprite grid format the renderer reads.

The renderer opens every style asset as a JSON sprite grid: rows of one-character
palette keys, ``.`` for transparent cells, drawn at ``scale`` pixels per cell, at
most 128 cells a side. A generated PNG is turned into that grid once, when the
style is accepted; the shape checks then run on the grid drawn back, so the
stored package is exactly what was checked.
"""

from __future__ import annotations

import json
import math
import string

from PIL import Image

from app.ports import AppError

MAX_GRID = 128
MAX_SCALE = 32
TRANSPARENT = "."
ALPHA_CUTOFF = 128
KEYS = [
    key
    for key in string.ascii_letters + string.digits + string.punctuation
    if key not in (".", "_", '"', "\\")
] + [chr(code) for code in range(0x100, 0x200)]
MAX_COLORS = 255


def _scale(image: Image.Image) -> int:
    scale = max(1, math.ceil(max(image.size) / MAX_GRID))
    if scale > MAX_SCALE:
        raise AppError("sandbox_output_invalid", detail={"reason": "asset is too large for a grid"})
    return scale


def encode(image: Image.Image, sprite_id: str, *, scale: int | None = None) -> bytes:
    """A sprite grid of ``image`` sampled every ``scale`` pixels (default: the fitting scale)."""
    scale = scale or _scale(image)
    width, height = math.ceil(image.width / scale), math.ceil(image.height / scale)
    if width > MAX_GRID or height > MAX_GRID:
        raise AppError("sandbox_output_invalid", detail={"reason": "asset is too large for a grid"})
    grid = image.convert("RGBA").resize((width, height), Image.Resampling.NEAREST)
    alpha = grid.getchannel("A")
    rgb = grid.convert("RGB")
    if len(rgb.getcolors(width * height) or []) > MAX_COLORS:
        rgb = rgb.quantize(MAX_COLORS).convert("RGB")
    palette: dict[tuple[int, int, int], str] = {}
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            if alpha.getpixel((x, y)) < ALPHA_CUTOFF:  # type: ignore[operator]
                row.append(TRANSPARENT)
                continue
            color = rgb.getpixel((x, y))
            assert isinstance(color, tuple)
            key = palette.get(color)  # type: ignore[arg-type]
            if key is None:
                key = KEYS[len(palette)]
                palette[color] = key  # type: ignore[index]
            row.append(key)
        rows.append("".join(row))
    sprite = {
        "schema_version": 1,
        "id": sprite_id,
        "width": width,
        "height": height,
        "scale": scale,
        "origin": {"x": 0, "y": 0},
        "palette": {key: list(color) for color, key in palette.items()},
        "rows": rows,
    }
    return (json.dumps(sprite, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def rasterize(data: bytes, *, cell: int | None = None) -> Image.Image:
    """Draw a stored grid at ``cell`` pixels per cell (default: its scale)."""
    try:
        sprite = json.loads(data)
        palette = {key: tuple(rgb) for key, rgb in sprite["palette"].items()}
        width, height, scale = sprite["width"], sprite["height"], sprite["scale"]
        rows = sprite["rows"]
        pixels = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for y, row in enumerate(rows):
            for x, key in enumerate(row):
                if key != TRANSPARENT:
                    pixels.putpixel((x, y), (*palette[key], 255))
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise AppError("internal", detail={"reason": "stored sprite is unreadable"}) from error
    size = cell or scale
    return pixels.resize((width * size, height * size), Image.Resampling.NEAREST)


__all__ = ["encode", "rasterize"]
