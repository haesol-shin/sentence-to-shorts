"""Paper cut-out style: layered flat pieces with soft drop shadows, muted colours.

The program draws every asset the manifest declares. The stored grids in
``sprites/`` were encoded from this program, so a package without them can be
redrawn in the sandbox with the same shapes and colours.

Character parts share one 90x128 design canvas, drawn at three pixels per cell
for the 1080x1920 canvas; backgrounds use a 72x128 design canvas. Every piece is
a shadow and then the cut paper, which is what separates this style from the
flat one.
"""

from PIL import Image, ImageDraw, ImageFilter

PART = (90, 128)
SCENE = (72, 128)

SKY = "#F4E9D8"
SKIN = "#F1C9A5"
HAIR = "#5B3A29"
SHIRT = "#3F6E8C"
PANTS = "#2E3B47"
SHOE = "#1F2B33"
INK = "#2B2B2B"
MOUTH = "#8C3B2E"
SUN = "#E86F4C"
CLOUD = "#FFF6E5"
HILL = "#C9B28A"
GRASS = "#B79C6E"
GROUND = "#A88B5C"
CANOPY = "#7C9A6B"
TRUNK = "#6E5640"
WALL = "#E8D6BC"
BOARD = "#7C9A6B"
WOOD = "#B08A62"
NIGHT = "#232A3A"
DEEP = "#171C29"
STAR = "#F6E7C8"
MOON = "#F2D6A2"
PLUM = "#3A2E3F"
STONE = "#221A26"
SHADOW = (90, 70, 50, 110)


def _new(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _base(image, color):
    ImageDraw.Draw(image).rectangle((0, 0, SCENE[0], SCENE[1]), fill=color)


def _shape(draw, kind, box, fill):
    if kind == "ellipse":
        draw.ellipse(box, fill=fill)
    elif kind == "rect":
        draw.rectangle(box, fill=fill)
    elif kind == "round":
        draw.rounded_rectangle(box, 6, fill=fill)
    elif kind == "line":
        draw.line(box, fill=fill, width=8)
        for point in box:
            draw.ellipse((point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4), fill=fill)
    elif kind == "chord":
        draw.chord(box, 180, 360, fill=fill)
    else:
        draw.polygon(box, fill=fill)


def _piece(image, kind, box, fill, *, blur=2, offset=(1, 1)):
    shadow = _new(image.size)
    _shape(ImageDraw.Draw(shadow), kind, box, SHADOW)
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)), offset)
    _shape(ImageDraw.Draw(image), kind, box, fill)


def _head(image, glasses=False):
    _piece(image, "ellipse", (24, 10, 66, 58), SKIN)
    for left in (20, 64):
        _piece(image, "ellipse", (left, 30, left + 6, 40), SKIN)
    draw = ImageDraw.Draw(image)
    if glasses:
        draw.rounded_rectangle((31, 32, 41, 42), 3, outline=INK, width=2)
        draw.rounded_rectangle((49, 32, 59, 42), 3, outline=INK, width=2)
        draw.line((41, 37, 49, 37), fill=INK, width=2)


def _body(image, round_body=False):
    if round_body:
        _piece(image, "round", (26, 54, 64, 94), SHIRT)
        for left in (33, 46):
            _piece(image, "round", (left, 90, left + 11, 120), PANTS)
        for left in (32, 45):
            _piece(image, "round", (left, 116, left + 13, 126), SHOE)
        return
    _piece(image, "round", (29, 50, 61, 96), SHIRT)
    for left in (34, 46):
        _piece(image, "round", (left, 92, left + 10, 120), PANTS)
    for left in (33, 45):
        _piece(image, "round", (left, 116, left + 12, 126), SHOE)


def _arm(image, start, end, radius=4):
    _piece(image, "line", (start, end), SHIRT)
    draw = ImageDraw.Draw(image)
    draw.ellipse((start[0] - radius, start[1] - radius,
                  start[0] + radius, start[1] + radius), fill=SHIRT)
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


def _hair(image, long_hair=False):
    if long_hair:
        _piece(image, "round", (19, 28, 31, 66), HAIR)
        _piece(image, "round", (59, 28, 71, 66), HAIR)
    _piece(image, "chord", (23, 6, 67, 58), HAIR)


def _hat(image, crown=False):
    if crown:
        _piece(image, "rect", (29, 6, 61, 12), "#D9A441")
        _piece(image, "polygon", [(29, 6), (35, 0), (41, 5), (45, 0), (49, 5),
                                  (55, 0), (61, 6), (61, 12), (29, 12)], "#E8C06A")
        return
    _piece(image, "round", (21, 12, 69, 20), "#6E8FA8")
    _piece(image, "chord", (28, 0, 62, 24), "#7FA3BC")


def _outfit(image, scarf=False):
    if scarf:
        _piece(image, "round", (27, 52, 63, 60), "#D98E4A")
        _piece(image, "round", (43, 58, 49, 74), "#D98E4A")
        return
    _piece(image, "polygon", [(43, 56), (47, 56), (45, 72)], "#C2554A")
    _piece(image, "round", (43, 52, 47, 56), "#C2554A")


def _prop(image, mug=False):
    if mug:
        _piece(image, "round", (68, 94, 80, 108), "#6E8FA8")
        _piece(image, "ellipse", (70, 95, 78, 99), "#4A3628")
        draw = ImageDraw.Draw(image)
        draw.ellipse((78, 96, 86, 104), outline="#6E8FA8", width=2)
        return
    _piece(image, "round", (4, 92, 26, 108), "#B5654A")
    _piece(image, "rect", (9, 94, 23, 106), "#FFF6E5")


def _pose(image, wave=False):
    _arm(image, (31, 58), (17, 90))
    if wave:
        _arm(image, (59, 58), (76, 22), radius=5)
        _piece(image, "ellipse", (72, 14, 82, 24), SKIN, blur=1)
        return
    _arm(image, (59, 58), (73, 90))


CHARACTER = {
    "body_hero": lambda image: _body(image),
    "body_round": lambda image: _body(image, round_body=True),
    "face_neutral": lambda image: _head(image),
    "face_glasses": lambda image: _head(image, glasses=True),
    "hair_short": lambda image: _hair(image),
    "hair_long": lambda image: _hair(image, long_hair=True),
    "hat_cap": lambda image: _hat(image),
    "hat_crown": lambda image: _hat(image, crown=True),
    "outfit_tie": lambda image: _outfit(image),
    "outfit_scarf": lambda image: _outfit(image, scarf=True),
    "prop_book": lambda image: _prop(image),
    "prop_mug": lambda image: _prop(image, mug=True),
    "expr_happy": lambda image: _expression(ImageDraw.Draw(image)),
    "expr_surprised": lambda image: _expression(ImageDraw.Draw(image), surprised=True),
    "pose_idle": lambda image: _pose(image),
    "pose_wave": lambda image: _pose(image, wave=True),
}


def _character(asset_id):
    image = _new(PART)
    CHARACTER[asset_id](image)
    return image.resize((PART[0] * 3, PART[1] * 3), Image.Resampling.NEAREST)


def _park(image):
    _base(image, SKY)
    _piece(image, "ellipse", (-20, 56, 47, 98), HILL)
    _piece(image, "ellipse", (25, 60, 95, 102), GRASS)
    _piece(image, "rect", (0, 64, SCENE[0], SCENE[1]), GROUND)
    _piece(image, "ellipse", (52, 12, 64, 24), SUN)
    for left, top in ((8, 22), (35, 16)):
        _piece(image, "ellipse", (left, top + 4, left + 18, top + 13), CLOUD, blur=1)
        _piece(image, "ellipse", (left + 6, top, left + 16, top + 7), CLOUD, blur=1)
    _piece(image, "rect", (11, 52, 13, 66), TRUNK)
    _piece(image, "ellipse", (4, 36, 20, 54), CANOPY)


def _village(image):
    _base(image, SKY)
    _piece(image, "rect", (0, 64, SCENE[0], SCENE[1]), GRASS)
    _piece(image, "ellipse", (52, 14, 64, 26), SUN)
    for left, top, roof in ((7, 42, "#C2554A"), (28, 48, "#D9A441"), (50, 38, "#6E8FA8")):
        _piece(image, "rect", (left, top, left + 17, 66), "#F6EBD8")
        _piece(image, "polygon", [(left - 2, top), (left + 8, top - 10),
                                  (left + 19, top)], roof)
        draw = ImageDraw.Draw(image)
        draw.rectangle((left + 3, top + 6, left + 7, top + 12), fill="#A88B5C")
        draw.rectangle((left + 10, top + 6, left + 14, top + 12), fill="#A88B5C")


def _stars(image):
    _base(image, NIGHT)
    draw = ImageDraw.Draw(image)
    for x, y in ((8, 12), (18, 30), (32, 10), (44, 36), (58, 18), (64, 48), (24, 52)):
        draw.ellipse((x, y, x + 2, y + 2), fill=STAR)
    _piece(image, "ellipse", (50, 12, 64, 26), MOON)
    _piece(image, "ellipse", (0, 58, 72, 102), "#2E3648")


def _classroom(image):
    _base(image, WALL)
    _piece(image, "rect", (6, 12, 52, 40), BOARD)
    _piece(image, "rect", (0, 64, SCENE[0], SCENE[1]), WOOD)
    for left in (6, 28, 50):
        _piece(image, "rect", (left, 44, left + 16, 64), "#C8A46B")
        _piece(image, "rect", (left + 6, 32, left + 10, 46), "#B08A55")


def _city_night(image):
    _base(image, NIGHT)
    _piece(image, "ellipse", (54, 10, 64, 20), MOON)
    for left, top, width in ((4, 34, 12), (20, 22, 14), (38, 30, 11), (53, 26, 16)):
        _piece(image, "rect", (left, top, left + width, 66), "#3A4152")
        draw = ImageDraw.Draw(image)
        for row in range(top + 6, 62, 10):
            draw.rectangle((left + 3, row, left + 6, row + 3), fill=MOON)
    _piece(image, "rect", (0, 64, SCENE[0], SCENE[1]), DEEP)


def _moon_hill(image):
    _base(image, DEEP)
    draw = ImageDraw.Draw(image)
    for x, y in ((10, 20), (26, 8), (40, 30), (60, 22), (16, 44)):
        draw.ellipse((x, y, x + 2, y + 2), fill=STAR)
    _piece(image, "ellipse", (48, 10, 64, 26), MOON)
    _piece(image, "ellipse", (-16, 54, 80, 106), "#2E3648")


def _bedroom(image):
    _base(image, "#33283A")
    _piece(image, "rect", (40, 10, 66, 40), DEEP)
    _piece(image, "ellipse", (54, 16, 62, 24), MOON)
    _piece(image, "rect", (0, 64, SCENE[0], SCENE[1]), "#241C2C")
    _piece(image, "rect", (6, 38, 46, 64), "#4A3A55")
    _piece(image, "rect", (6, 38, 46, 46), "#E8DCC8")
    _piece(image, "rect", (8, 30, 18, 40), "#FFF6E5")


def _arcade(image):
    _base(image, "#2E1A1A")
    _piece(image, "ellipse", (24, 10, 48, 34), "#E86F4C")
    draw = ImageDraw.Draw(image)
    for row in range(30, 64, 8):
        draw.rectangle((0, row, SCENE[0], row + 2), fill="#A8703F")
    _piece(image, "rect", (0, 64, SCENE[0], SCENE[1]), "#402828")


def _castle(image):
    _base(image, PLUM)
    _piece(image, "ellipse", (52, 12, 66, 26), "#F2D6A2")
    _piece(image, "ellipse", (0, 52, 72, 100), "#33283F")
    _piece(image, "rect", (20, 30, 52, 70), STONE)
    for left, height in ((14, 26), (48, 30)):
        _piece(image, "rect", (left, 58 - height, left + 10, 70), STONE)
        _piece(image, "polygon", [(left - 2, 58 - height), (left + 5, 48 - height),
                                  (left + 12, 58 - height)], STONE)
    draw = ImageDraw.Draw(image)
    draw.rectangle((32, 50, 40, 70), fill="#140F1A")


def _space(image):
    _base(image, "#171C29")
    draw = ImageDraw.Draw(image)
    for x, y in ((8, 10), (22, 26), (36, 8), (50, 30), (64, 14), (16, 44), (58, 40)):
        draw.ellipse((x, y, x + 2, y + 2), fill=STAR)
    _piece(image, "ellipse", (12, 24, 36, 48), "#6E8FA8")
    _piece(image, "ellipse", (44, 14, 60, 30), "#C2554A")
    _piece(image, "ellipse", (-24, 66, 96, 160), "#2A3040")


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
    image = _new(SCENE)
    BACKGROUNDS[asset_id](image)
    return image


def _skin(asset_id):
    image = _new((9, 9))
    fill, border = {
        "skin_plain": ("#FFFBF2", "#D9C3A0"),
        "skin_round": ("#3A3226", "#C9A87C"),
        "skin_bevel": ("#4A2E24", "#D9A441"),
    }[asset_id]
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 8, 8), 6, fill=fill, outline=border, width=1)
    return image


def _icon(asset_id):
    image = _new((5, 5))
    if asset_id == "icon_arrow":
        ImageDraw.Draw(image).polygon(
            [(0, 1), (3, 1), (3, 0), (5, 2), (3, 4), (3, 3), (0, 3)], fill=INK
        )
    return image


def build_assets(spec, character, canvas, seed):
    """Every asset of the manifest, drawn at the declared canvas size."""
    width, height = int(canvas["width"]), int(canvas["height"])
    images = {}
    for slot_ids in spec["parts"].values():
        for asset_id in slot_ids:
            images[asset_id] = _character(asset_id)
    for asset_id in [*spec["expressions"], *spec["poses"]]:
        images[asset_id] = _character(asset_id)
    for asset_id in spec["backgrounds"]:
        images[asset_id] = _background(asset_id).resize(
            (width, height), Image.Resampling.NEAREST
        )
    for asset_id in spec["skins"]:
        images[asset_id] = _skin(asset_id)
    for asset_id in spec["icons"]:
        images[asset_id] = _icon(asset_id)
    return images
