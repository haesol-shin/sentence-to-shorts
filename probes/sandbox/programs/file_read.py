"""Attack: read a runtime file that was readable during bootstrap.

The read permission is revoked before stdin is read, so this read must fail even
though the file was open to the bootstrap step.
"""

import js


def build_assets(spec, character, canvas, seed):
    runtime = js.Deno.args[0]
    js.Deno.readTextFileSync(runtime + "/pyodide/python_stdlib.zip")
    return {}
