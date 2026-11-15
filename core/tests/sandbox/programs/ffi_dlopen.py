"""Attack: load a dynamic library."""

import wave

js = wave.builtins.__import__("js")


def build_assets(spec, character, canvas, seed):
    js.Deno.dlopen("sandbox.invalid.so", js.Object.new())
    return {}
