"""Attack: open a network request from Python.

The entry is async so the request result is observed inside the sandbox instead
of being left as an unresolved promise.
"""

import js


async def build_assets(spec, character, canvas, seed):
    await js.fetch("https://probe.invalid/")
    return {}
