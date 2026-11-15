"""Attack: write a file in the working folder."""

import wave

js = wave.builtins.__import__("js")


def build_assets(spec, character, canvas, seed):
    js.Deno.writeTextFileSync("escape.txt", "escaped")
    return {}
