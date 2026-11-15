"""Pixel sprite grids of builtin art styles, read as data and drawn with Pillow.

A sprite is a JSON grid: each row is a string, each character a palette key.
``.`` is transparent. ``_`` is an erase cell: it is transparent in the sprite
itself and clears the layer below when a pose is applied to a body.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from app.ports import AppError

TRANSPARENT = "."
ERASE = "_"
MAX_GRID = 128
MAX_SCALE = 32


@dataclass(frozen=True)
class Sprite:
    id: str
    width: int
    height: int
    scale: int
    origin: tuple[int, int]
    palette: dict[str, tuple[int, int, int]]
    rows: tuple[str, ...]

    def cells(self) -> list[tuple[int, int, str]]:
        return [
            (x, y, key)
            for y, row in enumerate(self.rows)
            for x, key in enumerate(row)
            if key != TRANSPARENT
        ]


def _invalid(sprite_id: str, reason: str) -> AppError:
    return AppError("asset_invalid", detail={"asset": sprite_id, "reason": reason})


def _int(raw: dict[str, Any], key: str, sprite_id: str, low: int, high: int) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise _invalid(sprite_id, key)
    return value


def parse_sprite(raw: object, sprite_id: str) -> Sprite:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise _invalid(sprite_id, "schema_version")
    if raw.get("id") != sprite_id:
        raise _invalid(sprite_id, "id")
    width = _int(raw, "width", sprite_id, 1, MAX_GRID)
    height = _int(raw, "height", sprite_id, 1, MAX_GRID)
    scale = _int(raw, "scale", sprite_id, 1, MAX_SCALE)
    origin_raw = raw.get("origin", {"x": 0, "y": 0})
    if not isinstance(origin_raw, dict):
        raise _invalid(sprite_id, "origin")
    origin = (
        _int(origin_raw, "x", sprite_id, 0, MAX_GRID),
        _int(origin_raw, "y", sprite_id, 0, MAX_GRID),
    )
    palette_raw = raw.get("palette")
    if not isinstance(palette_raw, dict):
        raise _invalid(sprite_id, "palette")
    palette: dict[str, tuple[int, int, int]] = {}
    for key, rgb in palette_raw.items():
        if (
            len(key) != 1
            or key in (TRANSPARENT, ERASE)
            or not isinstance(rgb, list)
            or len(rgb) != 3
            or not all(isinstance(v, int) and 0 <= v <= 255 for v in rgb)
        ):
            raise _invalid(sprite_id, f"palette {key}")
        palette[key] = (rgb[0], rgb[1], rgb[2])
    rows = raw.get("rows")
    if not isinstance(rows, list) or len(rows) != height:
        raise _invalid(sprite_id, "rows")
    for row in rows:
        if not isinstance(row, str) or len(row) != width:
            raise _invalid(sprite_id, "row width")
        for key in row:
            if key not in palette and key not in (TRANSPARENT, ERASE):
                raise _invalid(sprite_id, f"unknown key {key}")
    return Sprite(
        id=sprite_id,
        width=width,
        height=height,
        scale=scale,
        origin=origin,
        palette=palette,
        rows=tuple(rows),
    )


def load_sprite(path: Path, sprite_id: str) -> Sprite:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _invalid(sprite_id, "unreadable") from error
    return parse_sprite(raw, sprite_id)


def rasterize(sprite: Sprite, cell: int | None = None) -> Image.Image:
    """Draw the grid with one square of ``cell`` pixels per grid cell (default: scale)."""
    size = cell or sprite.scale
    pixels = Image.new("RGBA", (sprite.width, sprite.height), (0, 0, 0, 0))
    for x, y, key in sprite.cells():
        if key != ERASE:
            pixels.putpixel((x, y), (*sprite.palette[key], 255))
    return pixels.resize((sprite.width * size, sprite.height * size), Image.Resampling.NEAREST)


def erase_mask(sprite: Sprite, frame: tuple[int, int], cell: int) -> Image.Image:
    """An L mask of ``frame`` size where erase cells are 0 and every other pixel 255."""
    mask = Image.new("L", frame, 255)
    ox, oy = sprite.origin
    for x, y, key in sprite.cells():
        if key == ERASE:
            left, top = (ox + x) * cell, (oy + y) * cell
            mask.paste(0, (left, top, left + cell, top + cell))
    return mask
