"""Template program that paints over the whole frame, hiding the visual region."""

from PIL import Image


def render_layer(scene, regions, canvas, parts, seed):
    return Image.new("RGBA", (canvas["width"], canvas["height"]), (10, 10, 10, 255)), {}
