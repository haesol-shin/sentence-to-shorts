"""Attack: start a child process from the Deno side."""

import wave

js = wave.builtins.__import__("js")


def build_assets(spec, character, canvas, seed):
    js.eval("new Deno.Command(Deno.execPath(), { args: ['--version'] }).outputSync()")
    return {}
