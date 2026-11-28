"""Flat illustration style: round shapes, pastel fills, no outlines.

The program draws every asset the manifest declares. The stored grids in
``sprites/`` were encoded from this program, so a package without them can be
redrawn in the sandbox with the same shapes and colours.

Pillow draws the original design coordinates directly onto four-times denser
part and background grids. No random and no host files.
"""

from PIL import Image, ImageDraw

DENSITY = 4
PART = (90, 128)
SCENE = (72, 128)

SKY = "#CFE8F5"
SKIN = "#FFD9B8"
HAIR = "#4A3A35"
SHIRT = "#F28C6B"
PANTS = "#3E4A61"
SHOE = "#2B3440"
INK = "#2B2B2B"
MOUTH = "#C2554A"
SUN = "#FFE08A"
CLOUD = "#FFFFFF"
HILL = "#9ED39A"
GRASS = "#86C784"
CANOPY = "#5FB36A"
TRUNK = "#8A6A4F"
WALL = "#F6E7CF"
BOARD = "#7FB39B"
WOOD = "#D9B98C"
NIGHT = "#16213E"
DEEP = "#0B1026"
STAR = "#FFF6D6"
MOON = "#FFF1C9"
PLUM = "#3D2B56"
STONE = "#1E1733"


def _box(box):
    left, top, right, bottom = box
    # Pillow includes both endpoints, so keep the far edge of each design cell.
    return (
        left * DENSITY, top * DENSITY,
        (right + 1) * DENSITY - 1, (bottom + 1) * DENSITY - 1,
    )


def _points(points):
    return [(x * DENSITY, y * DENSITY) for x, y in points]


class _Drawing:
    """Draw in design units without rasterizing the design grid first."""

    def __init__(self, image):
        self.draw = ImageDraw.Draw(image)

    def ellipse(self, box, *, width=1, **paint):
        self.draw.ellipse(_box(box), width=width * DENSITY, **paint)

    def rectangle(self, box, **paint):
        self.draw.rectangle(_box(box), **paint)

    def rounded_rectangle(self, box, radius, *, width=1, **paint):
        self.draw.rounded_rectangle(_box(box), radius * DENSITY, width=width * DENSITY, **paint)

    def line(self, points, *, width, **paint):
        self.draw.line(_points(points), width=width * DENSITY, **paint)

    def polygon(self, points, **paint):
        self.draw.polygon(_points(points), **paint)

    def arc(self, box, start, end, *, width, **paint):
        self.draw.arc(_box(box), start, end, width=width * DENSITY, **paint)

    def chord(self, box, start, end, **paint):
        self.draw.chord(_box(box), start, end, **paint)


def _new(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _head(draw, glasses=False):
    draw.ellipse((24, 10, 66, 58), fill=SKIN)
    draw.ellipse((20, 30, 26, 40), fill=SKIN)
    draw.ellipse((64, 30, 70, 40), fill=SKIN)
    if glasses:
        draw.rounded_rectangle((31, 32, 41, 42), 3, outline=INK, width=2)
        draw.rounded_rectangle((49, 32, 59, 42), 3, outline=INK, width=2)
        draw.line(((41, 37), (49, 37)), fill=INK, width=2)


def _body(draw, round_body=False):
    if round_body:
        draw.rounded_rectangle((26, 54, 64, 94), 18, fill=SHIRT)
        for left in (33, 46):
            draw.rounded_rectangle((left, 90, left + 11, 120), 5, fill=PANTS)
        for left in (32, 45):
            draw.rounded_rectangle((left, 116, left + 13, 126), 4, fill=SHOE)
        return
    draw.rounded_rectangle((29, 50, 61, 96), 14, fill=SHIRT)
    for left in (34, 46):
        draw.rounded_rectangle((left, 92, left + 10, 120), 5, fill=PANTS)
    for left in (33, 45):
        draw.rounded_rectangle((left, 116, left + 12, 126), 4, fill=SHOE)


def _arm(draw, start, end, radius=4):
    draw.line((start, end), fill=SHIRT, width=8)
    draw.ellipse((start[0] - radius, start[1] - radius,
                  start[0] + radius, start[1] + radius), fill=SHIRT)
    draw.ellipse((end[0] - radius, end[1] - radius,
                  end[0] + radius, end[1] + radius), fill=SHIRT)
    draw.ellipse((end[0] - 4, end[1] - 4, end[0] + 4, end[1] + 4), fill=SKIN)


def _expression(draw, surprised=False):
    if surprised:
        draw.ellipse((34, 33, 40, 40), fill=INK)
        draw.ellipse((50, 33, 56, 40), fill=INK)
        draw.ellipse((42, 44, 48, 51), fill=MOUTH)
        return
    draw.ellipse((35, 34, 39, 39), fill=INK)
    draw.ellipse((51, 34, 55, 39), fill=INK)
    draw.arc((38, 38, 52, 48), 20, 160, fill=MOUTH, width=2)


def _hair(draw, long_hair=False):
    if long_hair:
        draw.rounded_rectangle((19, 28, 31, 66), 5, fill=HAIR)
        draw.rounded_rectangle((59, 28, 71, 66), 5, fill=HAIR)
    draw.chord((23, 6, 67, 58), 180, 360, fill=HAIR)


def _hat(draw, crown=False):
    if crown:
        draw.rectangle((29, 6, 61, 12), fill="#F2A03D")
        draw.polygon([(29, 6), (35, 0), (41, 5), (45, 0), (49, 5), (55, 0),
                      (61, 6), (61, 12), (29, 12)], fill="#FFD166")
        return
    draw.rounded_rectangle((21, 12, 69, 20), 3, fill="#5B8FC0")
    draw.chord((28, 0, 62, 24), 180, 360, fill="#6FA8DC")


def _outfit(draw, scarf=False):
    if scarf:
        draw.rounded_rectangle((27, 52, 63, 60), 4, fill="#F2C14E")
        draw.rounded_rectangle((43, 58, 49, 74), 3, fill="#F2C14E")
        return
    draw.polygon([(43, 56), (47, 56), (45, 72)], fill="#E05A4E")
    draw.rounded_rectangle((43, 52, 47, 56), 1, fill="#E05A4E")


def _prop(draw, mug=False):
    if mug:
        draw.rounded_rectangle((68, 94, 80, 108), 2, fill="#6FA8DC")
        draw.ellipse((78, 96, 86, 104), outline="#6FA8DC", width=2)
        draw.ellipse((70, 95, 78, 99), fill="#6B4A34")
        return
    draw.rounded_rectangle((4, 92, 26, 108), 2, fill="#E76F51")
    draw.rectangle((9, 94, 23, 106), fill="#FFF6E5")
    draw.line(((9, 94), (9, 106)), fill="#FFD9B8", width=2)


def _pose(draw, wave=False):
    _arm(draw, (31, 58), (17, 90))
    if wave:
        _arm(draw, (59, 58), (76, 22), radius=5)
        draw.ellipse((72, 14, 82, 24), fill=SKIN)
        return
    _arm(draw, (59, 58), (73, 90))


CHARACTER = {
    "body_hero": lambda draw: _body(draw),
    "body_round": lambda draw: _body(draw, round_body=True),
    "face_neutral": lambda draw: _head(draw),
    "face_glasses": lambda draw: _head(draw, glasses=True),
    "hair_short": lambda draw: _hair(draw),
    "hair_long": lambda draw: _hair(draw, long_hair=True),
    "hat_cap": lambda draw: _hat(draw),
    "hat_crown": lambda draw: _hat(draw, crown=True),
    "outfit_tie": lambda draw: _outfit(draw),
    "outfit_scarf": lambda draw: _outfit(draw, scarf=True),
    "prop_book": lambda draw: _prop(draw),
    "prop_mug": lambda draw: _prop(draw, mug=True),
    "expr_happy": lambda draw: _expression(draw),
    "expr_surprised": lambda draw: _expression(draw, surprised=True),
    "pose_idle": lambda draw: _pose(draw),
    "pose_wave": lambda draw: _pose(draw, wave=True),
}


def _character(asset_id):
    image = _new((PART[0] * DENSITY, PART[1] * DENSITY))
    CHARACTER[asset_id](_Drawing(image))
    return image


def _park(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill=SKY)
    draw.ellipse((-20, 56, 47, 98), fill=HILL)
    draw.ellipse((25, 60, 95, 102), fill=GRASS)
    draw.rectangle((0, 64, SCENE[0], SCENE[1]), fill=GRASS)
    draw.ellipse((52, 12, 64, 24), fill=SUN)
    for left, top in ((8, 22), (35, 16)):
        draw.ellipse((left, top + 4, left + 18, top + 13), fill=CLOUD)
        draw.ellipse((left + 6, top, left + 16, top + 7), fill=CLOUD)
    draw.rectangle((11, 52, 13, 66), fill=TRUNK)
    draw.ellipse((4, 36, 20, 54), fill=CANOPY)


def _village(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill=SKY)
    draw.rectangle((0, 64, SCENE[0], SCENE[1]), fill=GRASS)
    draw.ellipse((52, 14, 64, 26), fill=SUN)
    for left, top, roof in ((7, 42, "#E76F51"), (28, 48, "#F2C14E"), (50, 38, "#6FA8DC")):
        draw.rectangle((left, top, left + 17, 66), fill="#FFF3D6")
        draw.polygon([(left - 2, top), (left + 8, top - 10), (left + 19, top)], fill=roof)
        draw.rectangle((left + 3, top + 6, left + 7, top + 12), fill="#8FB3C9")
        draw.rectangle((left + 10, top + 6, left + 14, top + 12), fill="#8FB3C9")


def _stars(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill="#1B2E4F")
    for x, y in ((8, 12), (18, 30), (32, 10), (44, 36), (58, 18), (64, 48), (24, 52)):
        draw.ellipse((x, y, x + 2, y + 2), fill=STAR)
    draw.ellipse((50, 12, 64, 26), fill=MOON)
    draw.ellipse((0, 58, 72, 102), fill="#24304F")


def _classroom(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill=WALL)
    draw.rounded_rectangle((6, 12, 52, 40), 2, fill=BOARD)
    draw.rounded_rectangle((6, 12, 52, 40), 2, outline="#5B8F77", width=2)
    draw.rectangle((0, 64, SCENE[0], SCENE[1]), fill=WOOD)
    for left in (6, 28, 50):
        draw.rounded_rectangle((left, 44, left + 16, 64), 2, fill="#C8A46B")
        draw.rectangle((left + 6, 32, left + 10, 46), fill="#B08A55")


def _city_night(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill=NIGHT)
    draw.ellipse((54, 10, 64, 20), fill=MOON)
    for left, top, width in ((4, 34, 12), (20, 22, 14), (38, 30, 11), (53, 26, 16)):
        draw.rectangle((left, top, left + width, 66), fill="#24304F")
        for row in range(top + 6, 62, 10):
            draw.rectangle((left + 3, row, left + 6, row + 3), fill=SUN)
    draw.rectangle((0, 64, SCENE[0], SCENE[1]), fill=DEEP)


def _moon_hill(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill=DEEP)
    for x, y in ((10, 20), (26, 8), (40, 30), (60, 22), (16, 44)):
        draw.ellipse((x, y, x + 2, y + 2), fill=STAR)
    draw.ellipse((48, 10, 64, 26), fill=MOON)
    draw.ellipse((-16, 54, 80, 106), fill="#24304F")


def _bedroom(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill="#2A2140")
    draw.rounded_rectangle((40, 10, 66, 40), 2, fill=DEEP)
    draw.ellipse((54, 16, 62, 24), fill=MOON)
    draw.rectangle((0, 64, SCENE[0], SCENE[1]), fill="#1B1530")
    draw.rectangle((6, 38, 46, 64), fill="#4A3A6A")
    draw.rectangle((6, 38, 46, 46), fill="#E8E0F4")
    draw.rectangle((8, 30, 18, 40), fill="#FFFFFF")


def _arcade(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill="#1A0628")
    draw.ellipse((24, 10, 48, 34), fill="#FF4FA3")
    for row in range(30, 64, 8):
        draw.rectangle((0, row, SCENE[0], row + 2), fill="#7B2CBF")
    draw.rectangle((0, 64, SCENE[0], SCENE[1]), fill="#2A0A3C")


def _castle(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill=PLUM)
    draw.ellipse((52, 12, 66, 26), fill="#FFE0B2")
    draw.ellipse((0, 52, 72, 100), fill="#2A2040")
    draw.rectangle((20, 30, 52, 70), fill=STONE)
    for left, height in ((14, 26), (48, 30)):
        draw.rectangle((left, 58 - height, left + 10, 70), fill=STONE)
        draw.polygon([(left - 2, 58 - height), (left + 5, 48 - height),
                      (left + 12, 58 - height)], fill=STONE)
    draw.rectangle((32, 50, 40, 70), fill="#0F0B1E")


def _space(draw):
    draw.rectangle((0, 0, SCENE[0], SCENE[1]), fill="#0B0F1F")
    for x, y in ((8, 10), (22, 26), (36, 8), (50, 30), (64, 14), (16, 44), (58, 40)):
        draw.ellipse((x, y, x + 2, y + 2), fill=STAR)
    draw.ellipse((12, 24, 36, 48), fill="#6FA8DC")
    draw.ellipse((44, 14, 60, 30), fill="#E76F51")
    draw.ellipse((40, 20, 64, 24), outline="#F2C14E", width=2)
    draw.ellipse((-24, 66, 96, 160), fill="#1E2A4A")


BACKGROUNDS = {
    "bg_park": _park,
    "bg_village": _village,
    "bg_stars": _stars,
    "bg_classroom": _classroom,
    "bg_city_night": _city_night,
    "bg_moon_hill": _moon_hill,
    "bg_bedroom_night": _bedroom,
    "bg_arcade_grid": _arcade,
    "bg_castle": _castle,
    "bg_space": _space,
}


def _background(asset_id):
    image = _new((SCENE[0] * DENSITY, SCENE[1] * DENSITY))
    BACKGROUNDS[asset_id](_Drawing(image))
    return image


def _skin(asset_id):
    image = _new((9, 9))
    draw = ImageDraw.Draw(image)
    if asset_id == "skin_plain":
        draw.rounded_rectangle((0, 0, 8, 8), 3, fill="#FFFFFF", outline=SKY, width=1)
    elif asset_id == "skin_round":
        draw.rounded_rectangle((0, 0, 8, 8), 4, fill="#182048", outline="#7FD6FF", width=1)
    else:
        draw.rounded_rectangle((0, 0, 8, 8), 2, fill="#2A0A3C", outline="#FF4FA3", width=1)
    return image


def _icon(asset_id):
    image = _new((5, 5))
    if asset_id == "icon_arrow":
        ImageDraw.Draw(image).polygon(
            [(0, 1), (3, 1), (3, 0), (5, 2), (3, 4), (3, 3), (0, 3)], fill=INK
        )
    return image


def build_assets(spec, character, canvas, seed):
    """Draw the manifest's assets at their native grid sizes."""
    images = {}
    for slot_ids in spec["parts"].values():
        for asset_id in slot_ids:
            images[asset_id] = _character(asset_id)
    for asset_id in [*spec["expressions"], *spec["poses"]]:
        images[asset_id] = _character(asset_id)
    for asset_id in spec["backgrounds"]:
        images[asset_id] = _background(asset_id)
    for asset_id in spec["skins"]:
        images[asset_id] = _skin(asset_id)
    for asset_id in spec["icons"]:
        images[asset_id] = _icon(asset_id)
    return images
