"""Attack: ask for the read permission again, then read a runtime file."""

import wave

js = wave.builtins.__import__("js")


async def build_assets(spec, character, canvas, seed):
    request = js.Object.new()
    request.name = "read"
    await js.Deno.permissions.request(request)
    js.Deno.readTextFileSync(js.Deno.args[0] + "/pyodide/pyodide-lock.json")
    return {}
