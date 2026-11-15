"""Invalid output: patch the image encoder so the runner sends broken PNG bytes."""

from PIL import Image


def _broken_save(self, fp, format=None, **params):
    fp.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


Image.Image.save = _broken_save


def build_assets(spec, character, canvas, seed):
    return {"part": Image.new("RGBA", (8, 8), (10, 20, 30, 255))}
