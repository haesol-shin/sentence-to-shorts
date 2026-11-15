"""Template program: a title band, thin side rails and a caption frame."""

from PIL import Image, ImageDraw


def render_layer(scene, regions, canvas, parts, seed):
    layer = Image.new("RGBA", (canvas["width"], canvas["height"]), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    boxes = {}
    title = regions.get("title")
    if title:
        box = [title["x"], title["y"], title["x"] + title["w"], title["y"] + title["h"]]
        draw.rectangle(box, fill=(20, 24, 60, 230))
        boxes["title"] = box
    visual = regions["visual"]
    left = [visual["x"], visual["y"], visual["x"] + 12, visual["y"] + visual["h"]]
    right_x = visual["x"] + visual["w"]
    right = [right_x - 12, visual["y"], right_x, visual["y"] + visual["h"]]
    for rail in (left, right):
        draw.rectangle(rail, fill=(250, 210, 90, 255))
    caption = regions["caption"]
    frame = [caption["x"], caption["y"], caption["x"] + caption["w"], caption["y"] + caption["h"]]
    draw.rectangle(frame, outline=(240, 240, 240, 255), width=6)
    boxes["caption"] = frame
    return layer, {"boxes": boxes, "lines": len(scene["lines"])}
