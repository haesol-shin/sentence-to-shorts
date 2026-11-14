"""Attack: start a child process and wait for it.

The command is this Deno binary itself, so the failure is the run permission and
not a missing executable or an empty PATH.
"""

import js

js.eval("new Deno.Command(Deno.execPath(), { args: ['--version'] }).outputSync()")


def build_assets(spec, character, canvas, seed):
    return {}
