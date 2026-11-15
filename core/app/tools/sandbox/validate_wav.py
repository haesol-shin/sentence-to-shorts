"""Parent-side WAV check for code BGM output.

The file must be RIFF/WAVE with exactly one `fmt ` chunk (PCM, mono, 44100 Hz,
16-bit) and one non-empty `data` chunk of whole frames, and nothing else. The
length and byte limits come from the caller. The accepted file is measured: the
sample peak in dBFS and the integrated loudness in LUFS (ITU-R BS.1770 K-weighting
with the absolute and relative gates), both as integers in tenths.
"""

from __future__ import annotations

import math
import sys
from array import array
from dataclasses import dataclass

SAMPLE_RATE = 44100
CHANNELS = 1
BITS = 16
BLOCK_ALIGN = CHANNELS * BITS // 8
ALLOWED_CHUNKS = (b"fmt ", b"data")
FULL_SCALE = 32768.0
# BS.1770 gating: 400 ms blocks with 75 percent overlap, so 100 ms steps.
STEP_FRAMES = SAMPLE_RATE // 10
BLOCK_STEPS = 4
ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0
LOUDNESS_OFFSET = -0.691


class WavRejected(ValueError):
    """The bytes are not an acceptable WAV."""


@dataclass(frozen=True)
class CheckedWav:
    data: bytes
    frames: int
    duration_ms: int
    sample_peak_dbfs_x10: int | None
    loudness_lufs_x10: int | None


def _chunks(data: bytes) -> dict[bytes, bytes]:
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavRejected("missing RIFF or WAVE header")
    if int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise WavRejected("RIFF size does not match the file length")
    chunks: dict[bytes, bytes] = {}
    position = 12
    while position < len(data):
        if position + 8 > len(data):
            raise WavRejected("truncated chunk header")
        kind = data[position : position + 4]
        size = int.from_bytes(data[position + 4 : position + 8], "little")
        body = data[position + 8 : position + 8 + size]
        if len(body) != size:
            raise WavRejected(f"truncated {kind!r} chunk")
        if kind not in ALLOWED_CHUNKS:
            raise WavRejected(f"chunk {kind!r} is not allowed")
        if kind in chunks:
            raise WavRejected(f"repeated {kind!r} chunk")
        if kind == b"data" and b"fmt " not in chunks:
            raise WavRejected("data chunk comes before the fmt chunk")
        chunks[kind] = body
        position += 8 + size + (size & 1)
    if position != len(data):
        raise WavRejected("chunk padding runs past the file")
    return chunks


def _check_format(fmt: bytes | None) -> None:
    if fmt is None:
        raise WavRejected("missing fmt chunk")
    if len(fmt) != 16:
        raise WavRejected(f"fmt chunk is {len(fmt)} bytes, PCM needs 16")
    audio_format = int.from_bytes(fmt[0:2], "little")
    channels = int.from_bytes(fmt[2:4], "little")
    rate = int.from_bytes(fmt[4:8], "little")
    byte_rate = int.from_bytes(fmt[8:12], "little")
    block_align = int.from_bytes(fmt[12:14], "little")
    bits = int.from_bytes(fmt[14:16], "little")
    if (audio_format, channels, rate, bits) != (1, CHANNELS, SAMPLE_RATE, BITS):
        raise WavRejected(
            f"format {audio_format}/{channels}/{rate}/{bits} is not PCM mono 44100 Hz 16-bit"
        )
    if block_align != BLOCK_ALIGN or byte_rate != SAMPLE_RATE * BLOCK_ALIGN:
        raise WavRejected("block align or byte rate does not match PCM mono 16-bit")


def _biquad(
    samples: list[float], b: tuple[float, float, float], a: tuple[float, float]
) -> list[float]:
    b0, b1, b2 = b
    a1, a2 = a
    out = [0.0] * len(samples)
    x1 = x2 = y1 = y2 = 0.0
    for index, x0 in enumerate(samples):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[index] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


def _k_weighting() -> tuple[
    tuple[tuple[float, float, float], tuple[float, float]],
    tuple[tuple[float, float, float], tuple[float, float]],
]:
    # Coefficients from the BS.1770 analog prototypes, as libebur128 derives them.
    gain_db = 3.999843853973347
    shelf_hz = 1681.974450955533
    shelf_q = 0.7071752369554196
    k = math.tan(math.pi * shelf_hz / SAMPLE_RATE)
    vh = 10 ** (gain_db / 20)
    vb = vh**0.4996667741545416
    a0 = 1 + k / shelf_q + k * k
    shelf = (
        (
            (vh + vb * k / shelf_q + k * k) / a0,
            2 * (k * k - vh) / a0,
            (vh - vb * k / shelf_q + k * k) / a0,
        ),
        (2 * (k * k - 1) / a0, (1 - k / shelf_q + k * k) / a0),
    )
    high_hz = 38.13547087602444
    high_q = 0.5003270373238773
    k = math.tan(math.pi * high_hz / SAMPLE_RATE)
    a0 = 1 + k / high_q + k * k
    highpass = (
        (1.0, -2.0, 1.0),
        (2 * (k * k - 1) / a0, (1 - k / high_q + k * k) / a0),
    )
    return shelf, highpass


def _loudness_x10(samples: array) -> int | None:
    shelf, highpass = _k_weighting()
    weighted = _biquad(_biquad([value / FULL_SCALE for value in samples], *shelf), *highpass)
    steps = [
        sum(value * value for value in weighted[start : start + STEP_FRAMES])
        for start in range(0, len(weighted) - STEP_FRAMES + 1, STEP_FRAMES)
    ]
    block_frames = STEP_FRAMES * BLOCK_STEPS
    blocks = [
        sum(steps[index : index + BLOCK_STEPS]) / block_frames
        for index in range(len(steps) - BLOCK_STEPS + 1)
    ]
    absolute = [
        power
        for power in blocks
        if power > 0 and LOUDNESS_OFFSET + 10 * math.log10(power) > ABSOLUTE_GATE_LUFS
    ]
    if not absolute:
        return None
    relative_gate = (
        LOUDNESS_OFFSET + 10 * math.log10(sum(absolute) / len(absolute)) + RELATIVE_GATE_LU
    )
    gated = [
        power for power in absolute if LOUDNESS_OFFSET + 10 * math.log10(power) > relative_gate
    ]
    if not gated:
        return None
    return round(10 * (LOUDNESS_OFFSET + 10 * math.log10(sum(gated) / len(gated))))


def _peak_x10(samples: array) -> int | None:
    peak = max((abs(value) for value in samples), default=0)
    if peak == 0:
        return None
    return round(10 * 20 * math.log10(peak / FULL_SCALE))


def check_wav(data: bytes, *, max_ms: int, max_bytes: int) -> CheckedWav:
    """Check a code BGM WAV and measure its peak and loudness."""
    if len(data) > max_bytes:
        raise WavRejected(f"WAV is {len(data)} bytes, over {max_bytes}")
    chunks = _chunks(data)
    _check_format(chunks.get(b"fmt "))
    pcm = chunks.get(b"data")
    if pcm is None:
        raise WavRejected("missing data chunk")
    if not pcm:
        raise WavRejected("empty data chunk")
    if len(pcm) % BLOCK_ALIGN:
        raise WavRejected("data size is not a whole number of frames")
    frames = len(pcm) // BLOCK_ALIGN
    if frames * 1000 > max_ms * SAMPLE_RATE:
        raise WavRejected(f"WAV runs {frames * 1000 // SAMPLE_RATE} ms, over {max_ms} ms")
    samples = array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return CheckedWav(
        data=data,
        frames=frames,
        duration_ms=frames * 1000 // SAMPLE_RATE,
        sample_peak_dbfs_x10=_peak_x10(samples),
        loudness_lufs_x10=_loudness_x10(samples),
    )
