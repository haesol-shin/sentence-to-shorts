from PIL import Image, ImageDraw


def draw_caption_box(plate, spec, canvas, seed):
    width, height = plate["w"], plate["h"]
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle(
        [0, 0, width - 1, height - 1], radius=height // 2, fill=spec["box_color"]
    )
    return image, {"box": [0, 0, width, height], "text_area": [8, 4, width - 16, height - 8]}
