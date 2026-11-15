"""Attack: allocate without a bound."""


def build_assets(spec, character, canvas, seed):
    chunks = []
    while True:
        chunks.append(bytearray(32 * 1024 * 1024))
