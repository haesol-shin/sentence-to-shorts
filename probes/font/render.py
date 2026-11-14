"""Deterministic caption rendering at the 1080x1920 output size.

The caption block is drawn at the layout the contract fixes for the subtitle
box, so the PNG digest covers the same glyphs and the same placement on every
platform. Both a pixel digest and a PNG file digest are recorded: the pixel
digest decides whether two runs drew the same image, because PNG bytes also
depend on the zlib build that compressed them.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

BACKGROUND = (12, 12, 16)
FOREGROUND = (240, 240, 240)


@dataclass(frozen=True)
class Layout:
    """Caption geometry used for every measurement of this probe."""

    width: int = 1080
    height: int = 1920
    box_x: int = 90
    box_y: int = 1030
    box_width: int = 900
    box_height: int = 200
    font_size: int = 64
    line_height: int = 80
    max_lines: int = 2

    def as_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "box": {
                "x": self.box_x,
                "y": self.box_y,
                "width": self.box_width,
                "height": self.box_height,
            },
            "font_size": self.font_size,
            "line_height": self.line_height,
            "max_lines": self.max_lines,
        }


def baselines(layout: Layout, ascent: int, descent: int, count: int) -> list[int]:
    """Baselines that center the block in the caption box."""
    gap = layout.line_height - (ascent + descent)
    top = layout.box_y + max(0, gap) // 2
    return [top + index * layout.line_height + ascent for index in range(count)]


def draw(font: ImageFont.FreeTypeFont, lines: Sequence[str], layout: Layout) -> Image.Image:
    """Draw the wrapped caption lines, and every line when there are more than allowed."""
    ascent, descent = font.getmetrics()
    image = Image.new("RGB", (layout.width, layout.height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for text, baseline in zip(lines, baselines(layout, ascent, descent, len(lines))):
        draw.text((layout.box_x, baseline), text, font=font, fill=FOREGROUND, anchor="ls")
    return image


def digests(image: Image.Image) -> dict:
    """Hash the pixels and the encoded PNG of one rendered image."""
    pixels = image.tobytes()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {
        "pixels_sha256": hashlib.sha256(pixels).hexdigest(),
        "png_sha256": hashlib.sha256(buffer.getvalue()).hexdigest(),
    }


def encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
