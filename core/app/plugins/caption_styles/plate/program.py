"""Draw the default filled caption rectangle at the origin."""

from PIL import Image


def draw_caption_box(plate, spec, canvas, seed):
    width, height = plate["w"], plate["h"]
    return Image.new("RGBA", (width, height), spec["box_color"]), {
        "box": [0, 0, width, height],
        "text_area": [0, 4, width, height - 8],
    }
