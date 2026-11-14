"""Attack: read host system information from Python through the js bridge.

The bridge itself stays reachable by design. This program asks for OS data that
the sys permission gates, so the call must fail after the revoke.
"""

import js


def build_assets(spec, character, canvas, seed):
    js.Deno.systemMemoryInfo()
    return {}
