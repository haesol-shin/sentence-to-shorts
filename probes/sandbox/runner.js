// Fixed Deno entry for the sandbox probe.
//
// Bootstrap reads only the pinned runtime folder and loads the allowed Pillow
// wheel. Read permission is then revoked and the permission state is checked
// before stdin is read. The program under test runs in a fresh Python namespace
// and cannot change the flags of this process. One request in, one JSON line out.
//
// This file is probe code. It is not part of the product runtime.

import { pathToFileURL } from "node:url";

const PROTOCOL = 1;
const PERMISSIONS = ["read", "write", "net", "env", "run", "ffi", "sys", "import"];
const CAPTURE_LINES = 40;
const STDIN_CAP = 16 * 1024 * 1024;

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function emit(payload) {
  Deno.stdout.writeSync(encoder.encode(JSON.stringify(payload) + "\n"));
}

function errorText(error) {
  if (error === null || error === undefined) {
    return "";
  }
  if (typeof error.message === "string") {
    return error.message;
  }
  return String(error);
}

function classify(error) {
  const name = error?.name ?? "";
  const message = errorText(error);
  if (name === "PermissionDenied" || name === "NotCapable") {
    return "permission_denied";
  }
  if (
    /PermissionDenied|NotCapable|Requires (read|write|net|env|run|ffi|sys|import) access|not allowed/i
      .test(message)
  ) {
    return "permission_denied";
  }
  if (
    /out of memory|Cannot enlarge memory|Maximum memory size exceeded|MemoryError|Array buffer allocation failed/i
      .test(message)
  ) {
    return "memory_limit";
  }
  return "program_error";
}

async function readStdin() {
  const chunks = [];
  let total = 0;
  const buffer = new Uint8Array(1 << 16);
  while (true) {
    const read = await Deno.stdin.read(buffer);
    if (read === null) {
      break;
    }
    total += read;
    if (total > STDIN_CAP) {
      throw new Error("request exceeds the stdin cap");
    }
    chunks.push(buffer.slice(0, read));
  }
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return decoder.decode(merged);
}

const TRUSTED_HELPER = `
import base64 as __probe_base64
import io as __probe_io
import json as __probe_json


def __probe_call(entry, arguments):
    return entry(*arguments)


def __probe_encode(result, output):
    if output == "png":
        if isinstance(result, dict):
            image = next(iter(result.values()))
            buffer = __probe_io.BytesIO()
            image.save(buffer, format="PNG")
            data = buffer.getvalue()
        else:
            data = bytes(result)
        return __probe_json.dumps(
            {"kind": "png", "base64": __probe_base64.b64encode(data).decode("ascii")}
        )
    if output == "wav":
        data = bytes(result)
        return __probe_json.dumps(
            {"kind": "wav", "base64": __probe_base64.b64encode(data).decode("ascii")}
        )
    return __probe_json.dumps({"kind": "json", "value": result})
`;

function captured() {
  return { stdout: [], stderr: [] };
}

function respondError(state, error, status = "error", code = null) {
  const message = errorText(error).slice(-2000);
  emit({
    protocol: PROTOCOL,
    run_id: state.run_id ?? null,
    status,
    value: null,
    error: {
      code: code ?? classify(error),
      name: error?.name ?? "",
      type: error?.constructor?.name ?? "",
      message,
    },
    timings: {
      bootstrap_ms: state.bootstrap_ms ?? null,
      run_ms: state.run_ms ?? null,
    },
    permissions: state.permissions ?? {},
    gate: state.gate ?? null,
    captured: state.log ?? captured(),
  });
}

async function main() {
  const state = { run_id: null, bootstrap_ms: null, run_ms: null, permissions: {}, log: captured() };
  const runtimeDir = Deno.args[0];
  if (!runtimeDir) {
    respondError(state, new Error("runtime directory argument missing"), "error", "invalid_request");
    return 3;
  }

  const bootstrapStart = performance.now();
  let pyodide;
  let loadPyodide;
  try {
    ({ loadPyodide } = await import(
      pathToFileURL(runtimeDir + "/pyodide/pyodide.mjs").href
    ));
  } catch (error) {
    respondError(state, error, "error", "bootstrap_failed");
    return 3;
  }

  const capture = (kind) => (line) => {
    if (state.log[kind].length < CAPTURE_LINES) {
      state.log[kind].push(String(line));
    }
  };

  try {
    pyodide = await loadPyodide({
      // Pyodide 314.0.7 treats Deno as its Node path and resolves indexURL with
      // node:path, so a plain directory path is required here. A file URL is
      // mangled into a relative path.
      indexURL: runtimeDir + "/pyodide/",
      stdout: capture("stdout"),
      stderr: capture("stderr"),
    });
    await pyodide.loadPackage("pillow");
    pyodide.runPython(TRUSTED_HELPER);
  } catch (error) {
    respondError(state, error, "error", "bootstrap_failed");
    return 3;
  }
  state.bootstrap_ms = Math.round(performance.now() - bootstrapStart);

  await Deno.permissions.revoke({ name: "read" });
  for (const name of PERMISSIONS) {
    try {
      const status = await Deno.permissions.query({ name });
      state.permissions[name] = status.state;
    } catch {
      state.permissions[name] = "unsupported";
    }
  }
  let deniedReadThrew = false;
  let deniedReadError = "";
  try {
    Deno.readTextFileSync(runtimeDir + "/pyodide/pyodide-lock.json");
  } catch (error) {
    deniedReadThrew = true;
    deniedReadError = errorText(error).slice(0, 200);
  }
  state.gate = {
    read: state.permissions.read,
    denied_read_threw: deniedReadThrew,
    error: deniedReadError,
  };
  const readState = state.permissions.read;
  if (!deniedReadThrew || (readState !== "denied" && readState !== "prompt")) {
    respondError(
      state,
      new Error(
        "read access survived the revoke: state " + readState + ", threw " + deniedReadThrew,
      ),
      "error",
      "permission_gate",
    );
    return 3;
  }

  let request;
  try {
    request = JSON.parse(await readStdin());
  } catch (error) {
    respondError(state, error, "error", "invalid_request");
    return 3;
  }
  state.run_id = request?.run_id ?? null;
  if (request?.protocol !== PROTOCOL) {
    respondError(state, new Error("unsupported protocol"), "error", "invalid_request");
    return 3;
  }
  if (typeof request.source !== "string" || !Array.isArray(request.arg_names)) {
    respondError(state, new Error("request is missing source or arg_names"), "error", "invalid_request");
    return 3;
  }

  const namespace = pyodide.globals.get("dict")();
  const call = pyodide.globals.get("__probe_call");
  const encode = pyodide.globals.get("__probe_encode");
  const runStart = performance.now();
  try {
    if (request.async_source) {
      await pyodide.runPythonAsync(request.source, { globals: namespace });
    } else {
      pyodide.runPython(request.source, { globals: namespace });
    }
    const entry = namespace.get(request.entry);
    if (typeof entry !== "function") {
      respondError(
        state,
        new Error("entry function is missing: " + request.entry),
        "error",
        "invalid_request",
      );
      return 3;
    }
    const args = request.arg_names.map((name) => request.args[name]);
    let result = call(entry, pyodide.toPy(args));
    if (request.async_source) {
      result = await result;
    }
    const encoded = encode(result, request.output);
    state.run_ms = Math.round(performance.now() - runStart);
    emit({
      protocol: PROTOCOL,
      run_id: request.run_id,
      status: "ok",
      value: JSON.parse(encoded),
      error: null,
      timings: { bootstrap_ms: state.bootstrap_ms, run_ms: state.run_ms },
      permissions: state.permissions,
      gate: state.gate,
      captured: state.log,
    });
    entry.destroy?.();
    result?.destroy?.();
    return 0;
  } catch (error) {
    state.run_ms = Math.round(performance.now() - runStart);
    respondError(state, error);
    return 0;
  } finally {
    namespace.destroy?.();
    call.destroy?.();
    encode.destroy?.();
  }
}

const code = await main();
Deno.exit(code);
