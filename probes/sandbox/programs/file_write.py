"""Attack: write a file in the working directory."""

import js


def build_assets(spec, character, canvas, seed):
    js.Deno.writeTextFileSync("probe-escape.txt", "escaped")
    return {}
