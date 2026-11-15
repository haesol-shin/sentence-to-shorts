"""Code BGM program that returns a big-endian RIFX header the parent must reject."""

import struct


def render_loop(params, seed):
    body = b"\x00\x00" * 44100
    fmt = struct.pack(">HHIIHH", 1, 1, 44100, 88200, 2, 16)
    chunks = b"fmt " + struct.pack(">I", len(fmt)) + fmt + b"data" + struct.pack(">I", len(body))
    return b"RIFX" + struct.pack(">I", 4 + len(chunks) + len(body)) + b"WAVE" + chunks + body
