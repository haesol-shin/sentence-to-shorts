"""Contract check: a plain import outside the allowlist is refused by the hook."""

import os


def build_assets(spec, character, canvas, seed):
    return {"part": os}
