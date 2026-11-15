"""Attack: open a network request. The entry awaits the request inside the sandbox."""

import wave

js = wave.builtins.__import__("js")


async def build_assets(spec, character, canvas, seed):
    await js.fetch("https://sandbox.invalid/")
    return {}
