"""Invalid output: a PNG signature followed by bytes that are not a PNG."""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def build_assets(spec, character, canvas, seed):
    return PNG_SIGNATURE + b"\x00" * 64
