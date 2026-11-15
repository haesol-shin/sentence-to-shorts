"""State check, second run: report what the first run left behind."""

import wave

from PIL import Image

MARKER_PATH = "/tmp/sandbox_leak_marker.txt"


def render_layer(scene, regions, canvas, parts, seed):
    modules = wave.sys.modules
    found = {
        "module": "sandbox_leak_marker" in modules,
        "file": modules["os"].path.exists(MARKER_PATH),
        "patch": getattr(Image, "sandbox_leak_patch", False) is True,
        "parts": sorted(parts),
    }
    return Image.new("RGBA", (16, 16), (0, 0, 0, 0)), found
