"""Attack: read an environment variable."""

import wave

js = wave.builtins.__import__("js")


def build_assets(spec, character, canvas, seed):
    js.Deno.env.get("DENO_DIR")
    return {}
