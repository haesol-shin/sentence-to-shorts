"""Attack: read an environment variable."""

import js


def build_assets(spec, character, canvas, seed):
    js.Deno.env.get("PATH")
    return {}
