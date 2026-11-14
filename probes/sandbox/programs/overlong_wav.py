"""Invalid output: a valid PCM WAV that runs past the length limit."""

import io
import struct
import wave

RATE = 44100
SECONDS = 20


def render_loop(params, seed):
    frames = RATE * SECONDS
    samples = struct.pack("<h", 100) * frames
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(samples)
    return buffer.getvalue()
