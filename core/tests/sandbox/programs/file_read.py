"""Attack: read a runtime file that was readable during bootstrap."""

import wave

js = wave.builtins.__import__("js")


def build_assets(spec, character, canvas, seed):
    runtime = js.Deno.args[0]
    js.Deno.readTextFileSync(runtime + "/pyodide/pyodide-lock.json")
    return {}
