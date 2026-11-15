"""Style program that redraws the builtin pixel sprites with inverted colours.

The test puts the sprite grids into `SPRITES` before running it, because the
sandbox cannot read package files. Only colours change; every shape stays.
"""

from PIL import Image

SPRITES = {}
OFFSET = (40, 80)


def _grid(sprite, cell):
    image = Image.new("RGBA", (sprite["width"], sprite["height"]), (0, 0, 0, 0))
    for y, row in enumerate(sprite["rows"]):
        for x, key in enumerate(row):
            if key in sprite["palette"]:
                red, green, blue = sprite["palette"][key]
                image.putpixel((x, y), (255 - red, 255 - green, 255 - blue, 255))
    size = (sprite["width"] * cell, sprite["height"] * cell)
    return image.resize(size, Image.Resampling.NEAREST)


def _placed(sprite, canvas):
    layer = Image.new("RGBA", (canvas["width"], canvas["height"]), (0, 0, 0, 0))
    cell = sprite["scale"]
    origin = sprite.get("origin") or {"x": 0, "y": 0}
    position = (OFFSET[0] + origin["x"] * cell, OFFSET[1] + origin["y"] * cell)
    layer.alpha_composite(_grid(sprite, cell), position)
    return layer


def build_assets(spec, character, canvas, seed):
    assets = {}
    for ids in spec["parts"].values():
        for asset_id in ids:
            assets[asset_id] = _placed(SPRITES[asset_id], canvas)
    for asset_id in spec["expressions"] + spec["poses"]:
        assets[asset_id] = _placed(SPRITES[asset_id], canvas)
    for asset_id in spec["backgrounds"]:
        sprite = SPRITES[asset_id]
        assets[asset_id] = _grid(sprite, sprite["scale"]).resize(
            (canvas["width"], canvas["height"]), Image.Resampling.NEAREST
        )
    for asset_id in spec["skins"]:
        assets[asset_id] = _grid(SPRITES[asset_id], 1)
    for asset_id in spec["icons"]:
        sprite = SPRITES[asset_id]
        assets[asset_id] = _grid(sprite, sprite["scale"])
    return assets
