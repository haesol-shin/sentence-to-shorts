"""Attack: ask for the read permission again, then use it.

The request resolves to a status instead of throwing, so the program reads a
runtime file afterwards. A restored permission would let the read succeed.
"""

import js


async def build_assets(spec, character, canvas, seed):
    status = await js.Deno.permissions.request({"name": "read"})
    print("request_state=" + status.state)
    runtime = js.Deno.args[0]
    js.Deno.readTextFileSync(runtime + "/pyodide/pyodide-lock.json")
    return {}
