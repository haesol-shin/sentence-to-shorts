"""Attack: load a dynamic library."""

import js


def build_assets(spec, character, canvas, seed):
    js.Deno.dlopen("probe.invalid.so", {})
    return {}
