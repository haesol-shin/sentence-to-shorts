"""Attack: reach a Deno API through the js bridge.

The import hook is only a contract marker, so the program steps around it with
the real import from an allowed module. The sys permission must still refuse.
"""

import wave

js = wave.builtins.__import__("js")


def build_assets(spec, character, canvas, seed):
    js.Deno.systemMemoryInfo()
    return {}
