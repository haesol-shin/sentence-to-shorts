"""Normal program: build a short mono PCM16 loop as WAV bytes."""

import io
import math
import struct
import wave

RATE = 44100


def render_loop(params, seed):
    seconds = max(1, min(int(params.get("seconds", 2)), 16))
    frames = RATE * seconds
    samples = bytearray()
    for index in range(frames):
        value = int(6000 * math.sin(2 * math.pi * 220 * index / RATE))
        samples += struct.pack("<h", value)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(samples))
    return buffer.getvalue()
