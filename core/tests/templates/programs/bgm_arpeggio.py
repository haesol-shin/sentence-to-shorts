"""Code BGM program: a soft arpeggio loop whose length follows bpm and bars.

`EXTRA_BARS` is raised by the long-loop test to make the WAV overrun its answer.
"""

import io
import math
import random
import struct
import wave

RATE = 44100
EXTRA_BARS = 0


def render_loop(params, seed):
    rng = random.Random(seed)
    bars = params["bars"] + EXTRA_BARS
    beat = RATE * 60 // params["bpm"]
    frames = beat * 4 * bars
    notes = [220.0 * 2 ** (step / 12) for step in (0, 4, 7, 12)]
    order = [rng.randrange(len(notes)) for _ in range(4 * bars)]
    samples = bytearray()
    for index in range(frames):
        note = notes[order[index // beat]]
        within = (index % beat) / beat
        envelope = math.sin(math.pi * within)
        value = int(9000 * envelope * math.sin(2 * math.pi * note * index / RATE))
        samples += struct.pack("<h", value)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(samples))
    return buffer.getvalue()
