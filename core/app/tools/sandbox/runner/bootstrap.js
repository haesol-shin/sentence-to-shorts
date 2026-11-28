// Python bootstrap for the sandbox runner, kept as a static module so the Deno
// read permission never has to cover a file outside the runtime folder.
//
// It runs once, before the read permission is revoked, and defines
// `__sbx_run(text)`: parse one request, execute the generated code in a fresh
// namespace, call the fixed entry function of the kind, and return one response
// JSON line. The import hook below marks the contract allowlist; it is not the
// security boundary. The boundary is the revoked Deno permissions and the parent.

export const BOOTSTRAP_PY = String.raw`
import base64
import builtins
import inspect
import io
import json
import re
import traceback

# Load the allowlisted modules now, while the runtime folder is still readable.
import array
import colorsys
import math
import random
import struct
import wave

import PIL
import PIL.Image
import PIL.ImageDraw
import PIL.PngImagePlugin

_ALLOWED_IMPORTS = frozenset(
    ("math", "random", "struct", "array", "io", "wave", "colorsys", "PIL")
)
_ENTRIES = {
    "style_parts": ("build_assets", ("spec", "character", "canvas")),
    "template_layer": ("render_layer", ("scene", "regions", "canvas")),
    "caption_box": ("draw_caption_box", ("plate", "spec", "canvas")),
    "bgm_loop": ("render_loop", ("params",)),
}
_IMAGE_META_NAMES = {"template_layer": "layer", "caption_box": "box"}
_NAME = re.compile(r"[a-z0-9_]{1,40}")
_REQUEST_ID = re.compile(r"[0-9a-f]{16}")
_NO_ID = "0000000000000000"
_MESSAGE_LIMIT = 2000
_META_LIMIT = 8
_real_import = builtins.__import__


class SandboxImportDenied(ImportError):
    pass


class _Failure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0 or name.partition(".")[0] not in _ALLOWED_IMPORTS:
        raise SandboxImportDenied("import of " + repr(name) + " is not allowed")
    return _real_import(name, globals, locals, fromlist, level)


def _namespace():
    generated_builtins = dict(builtins.__dict__)
    generated_builtins["__import__"] = _guarded_import
    return {"__builtins__": generated_builtins, "__name__": "generated"}


def _error(request_id, code, message):
    return json.dumps(
        {
            "type": "error",
            "request_id": request_id,
            "code": code,
            "message": message[-_MESSAGE_LIMIT:],
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _parse(text):
    try:
        request = json.loads(text)
    except ValueError as error:
        raise _Failure("bad_request", "request is not JSON: " + str(error)) from None
    if not isinstance(request, dict) or request.get("protocol") != 1:
        raise _Failure("bad_request", "request is not a protocol 1 object")
    kind = request.get("kind")
    if kind not in _ENTRIES:
        raise _Failure("bad_request", "unknown kind")
    for field in ("code", "input", "assets", "seed", "limits"):
        if field not in request:
            raise _Failure("bad_request", "request has no " + field)
    if not isinstance(request["input"], dict) or not isinstance(request["limits"], dict):
        raise _Failure("bad_request", "input and limits must be objects")
    return request


def _assets(assets):
    images = {}
    for asset in assets:
        data = base64.b64decode(asset["png_b64"], validate=True)
        image = PIL.Image.open(io.BytesIO(data))
        image.load()
        images[asset["name"]] = image
    return images


def _png(image, max_side):
    if not isinstance(image, PIL.Image.Image):
        raise _Failure("bad_return", "expected a PIL image, got " + type(image).__name__)
    width, height = image.size
    if not (1 <= width <= max_side and 1 <= height <= max_side):
        raise _Failure(
            "bad_return",
            "image is " + str(width) + "x" + str(height) + ", side limit " + str(max_side),
        )
    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _files(kind, result, limits):
    max_side = int(limits["max_png_side"])
    if kind == "style_parts":
        if not isinstance(result, dict) or not result:
            raise _Failure("bad_return", "build_assets must return a non-empty dict of images")
        if len(result) > int(limits["max_files"]):
            raise _Failure("too_many_files", str(len(result)) + " images returned")
        files = []
        for name, image in result.items():
            if not isinstance(name, str) or not _NAME.fullmatch(name):
                raise _Failure("bad_return", "part names must match [a-z0-9_]{1,40}")
            files.append({"name": name, "media_type": "image/png", "b64": _png(image, max_side)})
        return files, {}
    if kind in _IMAGE_META_NAMES:
        entry_name = _ENTRIES[kind][0]
        if not isinstance(result, tuple) or len(result) != 2:
            raise _Failure("bad_return", entry_name + " must return (image, dict)")
        image, meta = result
        if not isinstance(meta, dict) or len(meta) > _META_LIMIT:
            raise _Failure("bad_return", "program meta must be a dict of at most 8 keys")
        try:
            meta = json.loads(json.dumps(meta, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise _Failure("bad_return", "program meta is not JSON: " + str(error)) from None
        filename = _IMAGE_META_NAMES[kind]
        return [{"name": filename, "media_type": "image/png", "b64": _png(image, max_side)}], meta
    if not isinstance(result, (bytes, bytearray)):
        raise _Failure("bad_return", "render_loop must return WAV bytes")
    data = base64.b64encode(bytes(result)).decode("ascii")
    return [{"name": "loop", "media_type": "audio/wav", "b64": data}], {}


async def __sbx_run(text):
    request_id = _NO_ID
    try:
        request = _parse(text)
        candidate = request.get("request_id")
        if not isinstance(candidate, str) or not _REQUEST_ID.fullmatch(candidate):
            raise _Failure("bad_request", "request_id is not 16 hex digits")
        request_id = candidate
        kind = request["kind"]
        entry_name, arg_names = _ENTRIES[kind]
        try:
            arguments = [request["input"][name] for name in arg_names]
        except KeyError as error:
            raise _Failure("bad_request", "input has no " + str(error)) from None
        if kind == "template_layer":
            arguments.append(_assets(request["assets"]))
        arguments.append(int(request["seed"]))
    except _Failure as failure:
        return _error(request_id, failure.code, str(failure))
    except Exception as error:
        return _error(request_id, "bad_request", type(error).__name__ + ": " + str(error))

    try:
        random.seed(int(request["seed"]))
        namespace = _namespace()
        exec(compile(request["code"], "<generated>", "exec"), namespace)
        entry = namespace.get(entry_name)
        if not callable(entry):
            raise _Failure("bad_return", "entry function " + entry_name + " is missing")
        result = entry(*arguments)
        if inspect.isawaitable(result):
            result = await result
        files, meta = _files(kind, result, request["limits"])
        return json.dumps(
            {"type": "result", "request_id": request_id, "files": files, "meta": meta},
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
    except _Failure as failure:
        return _error(request_id, failure.code, str(failure))
    except SandboxImportDenied as error:
        return _error(request_id, "import_denied", str(error))
    except BaseException as error:
        # Drop the locals of finished frames first: after a MemoryError they
        # still hold the allocation, and formatting needs a little memory.
        traceback.clear_frames(error.__traceback__)
        try:
            text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        except BaseException:
            text = type(error).__name__
        return _error(request_id, "python_exception", text)
`;
