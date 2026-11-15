"""Invalid output: RIFF container with a wrong WAVE identifier."""


def render_loop(params, seed):
    body = b"WAVX" + b"junk" + b"\x00" * 32
    return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + body
