"""Style program with its own shapes: a small round head on a long thin body.

`EYE_HEIGHT` is replaced by the modification tests to narrow the eyes.
"""

import random

from PIL import Image, ImageDraw

EYE_HEIGHT = 14


def _layer(canvas):
    return Image.new("RGBA", (canvas["width"], canvas["height"]), (0, 0, 0, 0))


def _box(canvas, left, top, right, bottom):
    width, height = canvas["width"], canvas["height"]
    return [int(left * width), int(top * height), int(right * width), int(bottom * height)]


def _part(slot, canvas, ink):
    image = _layer(canvas)
    draw = ImageDraw.Draw(image)
    if slot == "body":
        draw.rectangle(_box(canvas, 0.62, 0.22, 0.72, 0.95), fill=ink)
    elif slot == "face":
        draw.ellipse(_box(canvas, 0.55, 0.04, 0.80, 0.18), fill=ink)
    elif slot == "hair":
        draw.pieslice(_box(canvas, 0.55, 0.02, 0.80, 0.16), 180, 360, fill=ink)
    elif slot == "hat":
        draw.polygon(
            [
                tuple(_box(canvas, 0.67, 0.0, 0.0, 0.0)[:2]),
                tuple(_box(canvas, 0.55, 0.05, 0.0, 0.0)[:2]),
                tuple(_box(canvas, 0.80, 0.05, 0.0, 0.0)[:2]),
            ],
            fill=ink,
        )
    elif slot == "outfit":
        draw.rectangle(_box(canvas, 0.60, 0.30, 0.74, 0.45), fill=ink)
    elif slot == "prop":
        draw.ellipse(_box(canvas, 0.05, 0.55, 0.30, 0.70), fill=ink)
    return image


def _expression(canvas, ink):
    image = _layer(canvas)
    draw = ImageDraw.Draw(image)
    top = int(0.09 * canvas["height"])
    for left in (0.61, 0.70):
        x = int(left * canvas["width"])
        draw.rectangle([x, top, x + 8, top + EYE_HEIGHT], fill=ink)
    return image


def _pose(canvas, ink):
    image = _layer(canvas)
    draw = ImageDraw.Draw(image)
    draw.line(_box(canvas, 0.30, 0.62, 0.62, 0.30), fill=ink, width=4)
    return image


def _background(canvas, rng):
    image = Image.new("RGBA", (canvas["width"], canvas["height"]), (30, 40, 90, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse(_box(canvas, 0.10, 0.10, 0.50, 0.32), fill=(250, 220, 120, 255))
    draw.polygon(
        [
            (0, canvas["height"]),
            (canvas["width"], int(0.55 * canvas["height"])),
            (canvas["width"], canvas["height"]),
        ],
        fill=(40, 120, 60, rng.randrange(255, 256)),
    )
    return image


def _skin():
    image = Image.new("RGBA", (9, 9), (20, 20, 30, 255))
    ImageDraw.Draw(image).rectangle([1, 1, 7, 7], outline=(240, 240, 240, 255))
    return image


def build_assets(spec, character, canvas, seed):
    rng = random.Random(seed)
    ink = (240, 240, 240, 255)
    assets = {}
    for slot, ids in spec["parts"].items():
        for asset_id in ids:
            assets[asset_id] = _part(slot, canvas, ink)
    for asset_id in spec["expressions"]:
        assets[asset_id] = _expression(canvas, (10, 10, 10, 255))
    for asset_id in spec["poses"]:
        assets[asset_id] = _pose(canvas, ink)
    for asset_id in spec["backgrounds"]:
        assets[asset_id] = _background(canvas, rng)
    for asset_id in spec["skins"]:
        assets[asset_id] = _skin()
    for asset_id in spec["icons"]:
        assets[asset_id] = Image.new("RGBA", (5, 5), ink)
    return assets
