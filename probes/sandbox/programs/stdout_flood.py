"""Attack: flood the host stdout stream from Python.

The write goes straight to the Deno stdout handle, so only the parent byte cap
can stop it.
"""

import js


def build_assets(spec, character, canvas, seed):
    chunk = js.Uint8Array.new(65536)
    while True:
        js.Deno.stdout.writeSync(chunk)
