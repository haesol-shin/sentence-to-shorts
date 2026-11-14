"""Parent-side payload validators for the sandbox probe.

Every byte here comes from the program under test, so the checks mirror the
product contract: the PNG is decoded inside a pixel cap and re-encoded as RGBA,
and the WAV must carry whole PCM frames. Pillow is a probe-only dependency for
the parent side; it is installed in the probe job, not in the product.

The limit values follow CONTRACTS 9.3 and 9.4.
"""

from __future__ import annotations

import io

from PIL import Image

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_SIDE = 1920
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_PNG_PIXELS = MAX_PNG_SIDE * MAX_PNG_SIDE
MAX_WAV_SECONDS = 16
MAX_WAV_BYTES = 1536 * 1024
WAV_RATE = 44100

# Pillow refuses to decode past twice this value; the checks below stop earlier.
Image.MAX_IMAGE_PIXELS = MAX_PNG_PIXELS


def check_png(data: bytes) -> tuple[bool, str]:
    """Check the header before decode, then decode and re-encode inside the cap."""
    if not data.startswith(PNG_SIGNATURE):
        return False, "missing PNG signature"
    if len(data) > MAX_PNG_BYTES:
        return False, f"PNG is {len(data)} bytes, over {MAX_PNG_BYTES}"
    if len(data) < 33 or data[12:16] != b"IHDR":
        return False, "missing IHDR chunk"
    length = int.from_bytes(data[8:12], "big")
    if length != 13:
        return False, f"IHDR length is {length}"
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width == 0 or height == 0:
        return False, f"empty image {width}x{height}"
    if width > MAX_PNG_SIDE or height > MAX_PNG_SIDE:
        return False, f"image {width}x{height} over the {MAX_PNG_SIDE} side cap"
    if width * height > MAX_PNG_PIXELS:
        return False, f"image {width}x{height} over the pixel cap"
    if b"IEND" not in data[-12:]:
        return False, "missing IEND chunk"
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                return False, f"decoder reported {image.format!r}"
            if image.size != (width, height):
                return False, f"decoded size {image.size} differs from IHDR {width}x{height}"
            if getattr(image, "n_frames", 1) != 1:
                return False, f"image has {image.n_frames} frames"
            image.load()
            encoded = io.BytesIO()
            image.convert("RGBA").save(encoded, format="PNG")
            reencoded = encoded.getvalue()
    except Image.DecompressionBombError as error:
        return False, f"decoder stopped at the pixel cap: {error}"
    except (OSError, ValueError, SyntaxError) as error:
        return False, f"decode failed: {error}"
    if not reencoded.startswith(PNG_SIGNATURE):
        return False, "re-encode produced no PNG"
    return True, f"PNG {width}x{height}, {len(data)} bytes, decoded and re-encoded to {len(reencoded)} bytes"


def check_wav(data: bytes) -> tuple[bool, str]:
    if len(data) < 44:
        return False, f"WAV is {len(data)} bytes, too short"
    if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False, "missing RIFF or WAVE header"
    if int.from_bytes(data[4:8], "little") + 8 != len(data):
        return False, "RIFF size does not match the file length"
    position = 12
    chunks: dict[bytes, bytes] = {}
    while position + 8 <= len(data):
        chunk_id = data[position : position + 4]
        size = int.from_bytes(data[position + 4 : position + 8], "little")
        body = data[position + 8 : position + 8 + size]
        if len(body) != size:
            return False, f"truncated {chunk_id!r} chunk"
        if chunk_id not in (b"fmt ", b"data"):
            return False, f"unexpected chunk {chunk_id!r}"
        if chunk_id in chunks:
            return False, f"repeated {chunk_id!r} chunk"
        chunks[chunk_id] = body
        position += 8 + size + (size & 1)
    if position != len(data):
        return False, "trailing bytes after the last chunk"
    fmt = chunks.get(b"fmt ")
    if fmt is None or len(fmt) < 16:
        return False, "missing fmt chunk"
    audio_format = int.from_bytes(fmt[0:2], "little")
    channels = int.from_bytes(fmt[2:4], "little")
    rate = int.from_bytes(fmt[4:8], "little")
    block_align = int.from_bytes(fmt[12:14], "little")
    bits = int.from_bytes(fmt[14:16], "little")
    if (audio_format, channels, rate, bits) != (1, 1, WAV_RATE, 16):
        return False, f"format {audio_format}/{channels}/{rate}/{bits} is not PCM mono 44100 16bit"
    if block_align != channels * bits // 8:
        return False, f"block align {block_align} does not match the sample size"
    samples = chunks.get(b"data")
    if samples is None:
        return False, "missing data chunk"
    if not samples:
        return False, "empty data chunk"
    if len(samples) % block_align:
        return False, "data size is not a whole number of frames"
    frames = len(samples) // block_align
    seconds = frames / WAV_RATE
    if seconds > MAX_WAV_SECONDS:
        return False, f"WAV is {seconds:.2f}s, over {MAX_WAV_SECONDS}s"
    if len(data) > MAX_WAV_BYTES:
        return False, f"WAV is {len(data)} bytes, over {MAX_WAV_BYTES}"
    return True, f"WAV {seconds:.2f}s, {frames} frames, {len(data)} bytes"
