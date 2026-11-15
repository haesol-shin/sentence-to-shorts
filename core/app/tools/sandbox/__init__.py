"""Sandbox runner package: generated drawing, template and code BGM run here only.

Design notes:

- State: no process outlives a request. Each run starts a fresh Deno process with
  a new empty working folder, so modules, the virtual file system and monkey
  patches of one program never reach the next. The adapter keeps only the
  runtime digest and a once-per-process readiness flag.
- Persistence: validated results only, in `CACHE_DIR/sandbox/results`, keyed by
  code digest, runtime digest, kind, canonical input, asset digests, seed and the
  effective limits. Deno's own cache lives in `CACHE_DIR/sandbox/deno`.
- Streaming: none. One request goes to stdin and the pipe is closed; one response
  line comes back on stdout. Stderr is capped and discarded.
- Failure: timeout, memory, invalid output, denied access, crash and missing
  runtime map to the `sandbox_*` job error codes. A failure caches nothing and
  never falls back to running the code on the host.
- Performance: a cold run pays the Pyodide bootstrap, about 3 s on the probe
  host. A cache hit starts no process. A warm worker pool is left out because
  the probe showed state surviving between programs in one interpreter.
- Extension: a new kind needs an entry function in the bootstrap, its input keys
  and file rules in the adapter, and a validator when it returns a new media type.
"""
