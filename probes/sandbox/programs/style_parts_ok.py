"""Normal program: build two part images for the style_parts entry."""

from PIL import Image, ImageDraw


def build_assets(spec, character, canvas, seed):
    width = max(1, int(canvas["width"]) // 4)
    height = max(1, int(canvas["height"]) // 4)
    parts = {}
    for index, color in enumerate(((32, 64, 128, 255), (200, 180, 40, 255))):
        image = Image.new("RGBA", (width, height), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, width - 1, height - 1], outline=(255, 255, 255, 255), width=4)
        parts[f"part_{index}"] = image
    return parts
