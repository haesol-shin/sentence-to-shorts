"""Attack: allocate without a bound.

The wasm memory fails, or the parent memory cap kills the process.
"""


def build_assets(spec, character, canvas, seed):
    chunks = []
    while True:
        chunks.append(bytearray(32 * 1024 * 1024))
