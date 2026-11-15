"""Parent-side PNG check for sandbox output.

Every byte comes from generated code. Before any decode this module walks the
chunk list itself: signature, chunk lengths and CRCs, and the IHDR size and
layout. Only then does Pillow decode the pixels, after the header it read is
compared with the IHDR and the pixel count is under the limit. The accepted
image is written again from raw RGBA bytes as a fresh PNG, so text, color
profiles and any other chunk the program added are dropped.

The runner always encodes 8-bit RGBA without interlace, so any other layout is
an invalid output rather than a format to convert.
"""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass

from PIL import Image

SIGNATURE = b"\x89PNG\r\n\x1a\n"
RGBA_COLOR_TYPE = 6
MAX_CHUNKS = 4096
KNOWN_CRITICAL = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND"})
REENCODE_LEVEL = 6


class PngRejected(ValueError):
    """The bytes are not an acceptable PNG."""


@dataclass(frozen=True)
class CheckedPng:
    data: bytes
    width: int
    height: int


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    chunks: list[tuple[bytes, bytes]] = []
    position = len(SIGNATURE)
    while position < len(data):
        if len(chunks) >= MAX_CHUNKS:
            raise PngRejected(f"more than {MAX_CHUNKS} chunks")
        if position + 12 > len(data):
            raise PngRejected("truncated chunk header")
        length = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        end = position + 12 + length
        if length > 0x7FFFFFFF or end > len(data):
            raise PngRejected("chunk length runs past the file")
        if not kind.isalpha():
            raise PngRejected(f"chunk type {kind!r} is not four letters")
        body = data[position + 8 : position + 8 + length]
        crc = int.from_bytes(data[end - 4 : end], "big")
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise PngRejected(f"bad CRC in {kind!r}")
        chunks.append((kind, body))
        position = end
        if kind == b"IEND":
            break
    if position != len(data):
        raise PngRejected("bytes after IEND")
    return chunks


def _header(body: bytes, max_side: int) -> tuple[int, int]:
    if len(body) != 13:
        raise PngRejected(f"IHDR length is {len(body)}")
    width, height, depth, color, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", body
    )
    if width == 0 or height == 0:
        raise PngRejected(f"empty image {width}x{height}")
    if width > max_side or height > max_side:
        raise PngRejected(f"image {width}x{height} is over the {max_side} side limit")
    if (depth, color) != (8, RGBA_COLOR_TYPE):
        raise PngRejected(f"bit depth {depth} and color type {color} are not 8-bit RGBA")
    if compression != 0 or filter_method != 0:
        raise PngRejected("unknown compression or filter method")
    if interlace != 0:
        raise PngRejected("interlaced PNG")
    return width, height


def _check_structure(chunks: list[tuple[bytes, bytes]]) -> None:
    idat_state = "before"
    for kind, _body in chunks[1:-1]:
        if kind == b"IDAT":
            if idat_state == "after":
                raise PngRejected("IDAT chunks are not consecutive")
            idat_state = "inside"
            continue
        if idat_state == "inside":
            idat_state = "after"
        if kind in (b"IHDR", b"IEND"):
            raise PngRejected(f"repeated {kind!r}")
        if kind[0:1].isupper() and kind not in KNOWN_CRITICAL:
            raise PngRejected(f"unknown critical chunk {kind!r}")
    if idat_state == "before":
        raise PngRejected("missing IDAT")


def _decode_rgba(data: bytes, width: int, height: int, max_pixels: int) -> bytes:
    """Decode with Pillow and return the raw RGBA pixels.

    Pillow's own decompression bomb limit is a process-wide setting shared with
    the renderer, so the limit here is checked per call on the header Pillow
    parsed, before `load()` inflates any pixel data.
    """
    try:
        with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
            if image.size != (width, height) or image.mode != "RGBA":
                raise PngRejected(
                    f"decoder sees {image.mode} {image.size}, IHDR says RGBA {(width, height)}"
                )
            if image.width * image.height > max_pixels:
                raise PngRejected(f"image has over {max_pixels} pixels")
            image.load()
            return image.tobytes()
    except PngRejected:
        raise
    except Exception as error:  # any decoder failure rejects the file
        raise PngRejected(f"image data does not decode: {error}") from error


def check_png(data: bytes, *, max_side: int, max_bytes: int) -> CheckedPng:
    """Check a PNG from the sandbox and return it re-encoded as plain RGBA."""
    if len(data) > max_bytes:
        raise PngRejected(f"PNG is {len(data)} bytes, over {max_bytes}")
    if not data.startswith(SIGNATURE):
        raise PngRejected("missing PNG signature")
    chunks = _chunks(data)
    if not chunks or chunks[0][0] != b"IHDR":
        raise PngRejected("first chunk is not IHDR")
    if chunks[-1] != (b"IEND", b""):
        raise PngRejected("missing or non-empty IEND")
    width, height = _header(chunks[0][1], max_side)
    _check_structure(chunks)

    pixels = _decode_rgba(data, width, height, max_side * max_side)
    output = io.BytesIO()
    Image.frombytes("RGBA", (width, height), pixels).save(
        output, format="PNG", compress_level=REENCODE_LEVEL
    )
    return CheckedPng(data=output.getvalue(), width=width, height=height)
