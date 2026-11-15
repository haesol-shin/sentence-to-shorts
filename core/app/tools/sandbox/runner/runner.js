// Fixed Deno entry for the sandbox runner.
//
// Bootstrap reads only the pinned runtime folder: Pyodide, its lock file and the
// allowed Pillow wheel. Then the read permission is revoked, every permission
// state is checked, and a read of a runtime file must fail. Only after that is
// stdin read: one request in, one response JSON line out. Bootstrap problems
// exit with a fixed status and no stdout line; the parent trusts neither.

import { pathToFileURL } from "node:url";

import { BOOTSTRAP_PY } from "./bootstrap.js";

const PERMISSIONS = ["read", "write", "net", "env", "run", "ffi", "sys", "import"];
const STDIN_CAP = 12 * 1024 * 1024;
const EXIT_BOOTSTRAP = 3;
const EXIT_PERMISSION_GATE = 4;
const EXIT_REQUEST = 5;
const EXIT_RUNNER = 6;

const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

// Library logging must not reach stdout, which carries only the response line.
for (const name of ["log", "info", "debug", "warn", "error", "trace"]) {
  console[name] = () => {};
}

function writeAll(stream, bytes) {
  let offset = 0;
  while (offset < bytes.length) {
    offset += stream.writeSync(bytes.subarray(offset));
  }
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

function fail(status, message) {
  try {
    writeAll(Deno.stderr, encoder.encode(message.slice(0, 2000) + "\n"));
  } catch {
    // stderr is diagnostic only
  }
  Deno.exit(status);
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

async function bootstrap(runtimeDir) {
  const { loadPyodide } = await import(
    pathToFileURL(runtimeDir + "/pyodide/pyodide.mjs").href
  );
  const pyodide = await loadPyodide({
    // Pyodide resolves indexURL with node:path under Deno, so a directory path
    // is required here; a file URL would be mangled into a relative path.
    indexURL: runtimeDir + "/pyodide/",
    stdout: () => {},
    stderr: () => {},
  });
  await pyodide.loadPackage("pillow", {
    messageCallback: () => {},
    errorCallback: () => {},
  });
  pyodide.runPython(BOOTSTRAP_PY);
  return pyodide;
}

async function checkPermissionGate(runtimeDir) {
  await Deno.permissions.revoke({ name: "read" });
  const states = {};
  for (const name of PERMISSIONS) {
    try {
      states[name] = (await Deno.permissions.query({ name })).state;
    } catch {
      states[name] = "unsupported";
    }
  }
  const granted = PERMISSIONS.filter((name) => states[name] === "granted");
  if (granted.length > 0) {
    return "permissions still granted: " + granted.join(",");
  }
  if (states.read !== "denied" && states.read !== "prompt") {
    return "read permission state is " + states.read;
  }
  try {
    Deno.readTextFileSync(runtimeDir + "/pyodide/pyodide-lock.json");
  } catch {
    return null;
  }
  return "a runtime file is still readable after the revoke";
}

async function main() {
  const runtimeDir = Deno.args[0];
  if (!runtimeDir) {
    fail(EXIT_BOOTSTRAP, "runtime directory argument missing");
  }

  let pyodide;
  try {
    pyodide = await bootstrap(runtimeDir);
  } catch (error) {
    fail(EXIT_BOOTSTRAP, "bootstrap failed: " + errorText(error));
  }

  const gate = await checkPermissionGate(runtimeDir);
  if (gate !== null) {
    fail(EXIT_PERMISSION_GATE, "permission gate failed: " + gate);
  }

  let text;
  try {
    text = await readStdin();
  } catch (error) {
    fail(EXIT_REQUEST, "request read failed: " + errorText(error));
  }

  let response;
  try {
    pyodide.globals.set("__sbx_request_text", text);
    response = await pyodide.runPythonAsync("await __sbx_run(__sbx_request_text)");
  } catch (error) {
    fail(EXIT_RUNNER, "runner failed: " + errorText(error));
  }
  if (typeof response !== "string") {
    fail(EXIT_RUNNER, "runner returned no response text");
  }
  writeAll(Deno.stdout, encoder.encode(response + "\n"));
  Deno.exit(0);
}

await main();
