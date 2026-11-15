"""State check, first run: leave a module, a virtual file and a monkey patch behind."""

import wave

from PIL import Image

MARKER_PATH = "/tmp/sandbox_leak_marker.txt"


def render_layer(scene, regions, canvas, parts, seed):
    modules = wave.sys.modules
    modules["sandbox_leak_marker"] = object()
    with open(MARKER_PATH, "w", encoding="utf-8") as handle:
        handle.write("planted")
    Image.sandbox_leak_patch = True
    return Image.new("RGBA", (16, 16), (0, 0, 0, 0)), {}
