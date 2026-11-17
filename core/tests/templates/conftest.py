"""Doubles and builders for the generated style, template and code BGM tests.

The model is a queue of fixed answers whose code strings are the programs in
`programs/`. The sandbox is the real adapter with its validators and cache; only
the launcher differs. Host tests use `HostLauncher`, which runs the trusted test
programs in-process with the runner's entry and file rules, so the parent sees
the same one-line protocol. Tests marked `sandbox` use the real runner instead.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import time
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.jobs import CancelFlag, LocalJobContext
from app.plugins.registry import Registry
from app.ports import LlmRequest, LlmResult
from app.schemas.common import PinnedRef
from app.schemas.job import Stage, Usage
from app.schemas.video import Video
from app.services.render import BUILTIN_LAYER_DRAWERS, BUILTIN_PARTS_BUILDERS
from app.services.templates.service import TemplatesService
from app.tools import process
from app.tools.sandbox.adapter import SandboxAdapter, SandboxConfig
from app.tools.sandbox.cache import ResultCache
from tests.sandbox.conftest import sandbox_config_values

CORE = Path(__file__).resolve().parents[2]
PROGRAMS = Path(__file__).resolve().parent / "programs"
PIXEL_SPRITES = CORE / "app" / "plugins" / "art_styles" / "pixel" / "sprites"
VIDEO = CORE.parent / "fixtures" / "contracts" / "valid" / "video_ko_just_three.json"
JOB_IDS = (
    "j_08c71zekrt8ceaqnmy5jjy5zvn",
    "j_08c71zekrt8ceaqnmy5jjy5zv1",
    "j_08c71zekrt8ceaqnmy5jjy5zv2",
    "j_08c71zekrt8ceaqnmy5jjy5zv3",
)
ENTRIES = {
    "style_parts": ("build_assets", ("spec", "character", "canvas")),
    "template_layer": ("render_layer", ("scene", "regions", "canvas")),
    "bgm_loop": ("render_loop", ("params",)),
}
REGIONS = {
    "title": {"x": 60, "y": 70, "w": 960, "h": 110},
    "progress": None,
    "visual": {"x": 90, "y": 260, "w": 900, "h": 740},
    "caption": {"x": 90, "y": 1040, "w": 900, "h": 160},
}
ANCHORS = {
    "left": {"x": 270, "y": 960},
    "center": {"x": 540, "y": 960},
    "right": {"x": 810, "y": 960},
}


def program(name: str) -> str:
    return (PROGRAMS / f"{name}.py").read_text(encoding="utf-8")


def pixel_recolor_code() -> str:
    """The recolour program with the builtin sprite grids written into it."""
    sprites = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(PIXEL_SPRITES.glob("*.json"))
    }
    return program("pixel_recolor").replace("SPRITES = {}", f"SPRITES = {sprites!r}", 1)


def narrow_eyes(code: str) -> str:
    return code.replace("EYE_HEIGHT = 14", "EYE_HEIGHT = 3", 1)


def style_answer(code: str) -> dict[str, Any]:
    return {"label": {"ko": "둥근 머리", "en": "Round Heads"}, "code": code}


def template_answer(code: str, **overrides: Any) -> dict[str, Any]:
    answer = {
        "label": {"ko": "위쪽 제목 띠", "en": "Top Title Band"},
        "code": code,
        "regions": REGIONS,
        "character_anchors": ANCHORS,
        "caption_modes": ["sentence", "phrase"],
        "dialog_box": False,
    }
    answer.update(overrides)
    return answer


def bgm_answer(code: str, *, bpm: int = 120, bars: int = 4) -> dict[str, Any]:
    return {
        "label": {"ko": "작은 아르페지오", "en": "Small Arpeggio"},
        "code": code,
        "bpm": bpm,
        "bars": bars,
    }


class ScriptedLlm:
    """Replays queued answers and records each request."""

    def __init__(self) -> None:
        self.answers: list[dict[str, Any]] = []
        self.requests: list[LlmRequest] = []

    def queue(self, *answers: dict[str, Any]) -> None:
        self.answers.extend(answers)

    def complete(
        self, req: LlmRequest, *, owner_id: str, cancel: Any, deadline: float,
        on_request: Any = None,
    ) -> LlmResult:
        self.requests.append(req)
        if not self.answers:
            raise AssertionError(f"no answer queued for {req.route}")
        answer = self.answers.pop(0)
        usage = Usage(
            stage=Stage.code_llm,
            provider="fake",
            model="fake",
            effort=None,
            input_tokens=None,
            output_tokens=None,
            cache_read_tokens=None,
            cache_write_tokens=None,
            wall_ms=0,
            retries=0,
        )
        return LlmResult(text=json.dumps(answer), parsed=answer, usage=usage)

    def auth_state(self, owner_id: str) -> str:
        return "ok"

    def data(self, index: int) -> dict[str, Any]:
        text = self.requests[index].parts[0].text
        assert text is not None
        return json.loads(text)


def _png(image: Any, max_side: int) -> str:
    if not isinstance(image, Image.Image):
        raise ValueError("expected a PIL image")
    if not (1 <= image.width <= max_side and 1 <= image.height <= max_side):
        raise ValueError("image passes the side limit")
    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _files(kind: str, result: Any, limits: dict[str, Any]) -> tuple[list[dict], dict]:
    side = int(limits["max_png_side"])
    if kind == "style_parts":
        return [
            {"name": name, "media_type": "image/png", "b64": _png(image, side)}
            for name, image in result.items()
        ], {}
    if kind == "template_layer":
        image, meta = result
        return [{"name": "layer", "media_type": "image/png", "b64": _png(image, side)}], meta
    data = base64.b64encode(bytes(result)).decode("ascii")
    return [{"name": "loop", "media_type": "audio/wav", "b64": data}], {}


@dataclass
class HostLauncher:
    """Runs trusted test programs in-process and answers in the runner protocol."""

    calls: int = 0

    def __call__(self, payload: bytes, *, timeout_s: float, cancel: Any) -> process.ProcessResult:
        self.calls += 1
        request = json.loads(payload)
        kind = request["kind"]
        entry_name, names = ENTRIES[kind]
        arguments = [request["input"][name] for name in names]
        if kind == "template_layer":
            arguments.append(
                {
                    asset["name"]: Image.open(io.BytesIO(base64.b64decode(asset["png_b64"])))
                    for asset in request["assets"]
                }
            )
        arguments.append(request["seed"])
        try:
            namespace: dict[str, Any] = {"__name__": "generated"}
            exec(compile(request["code"], "<generated>", "exec"), namespace)  # noqa: S102
            files, meta = _files(kind, namespace[entry_name](*arguments), request["limits"])
            response = {
                "type": "result",
                "request_id": request["request_id"],
                "files": files,
                "meta": meta,
            }
        except Exception:
            response = {
                "type": "error",
                "request_id": request["request_id"],
                "code": "python_exception",
                "message": traceback.format_exc()[-2000:],
            }
        line = json.dumps(response, separators=(",", ":")).encode() + b"\n"
        return process.ProcessResult(
            argv=("host",),
            returncode=0,
            stdout=line,
            stderr=b"",
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            cancelled=False,
            duration_ms=0,
        )


class CountingLauncher:
    """Wraps a launcher and counts the processes it starts."""

    def __init__(self, inner: Callable[..., process.ProcessResult]) -> None:
        self.inner = inner
        self.calls = 0

    def __call__(self, payload: bytes, *, timeout_s: float, cancel: Any) -> process.ProcessResult:
        self.calls += 1
        return self.inner(payload, timeout_s=timeout_s, cancel=cancel)


class FixedRuntime:
    def digest(self) -> str:
        return "ab" * 32

    def verify(self) -> None:
        return None


@dataclass
class Harness:
    service: TemplatesService
    catalog: Registry
    llm: ScriptedLlm
    launcher: CountingLauncher
    root: Path
    usages: list[Usage] = field(default_factory=list)
    jobs: Iterator[str] = field(default_factory=lambda: iter(JOB_IDS))

    def ctx(self) -> LocalJobContext:
        job_dir = self.root / "cache" / "j" / next(self.jobs)
        job_dir.mkdir(parents=True)
        return LocalJobContext(
            cancel_token=CancelFlag(),
            deadline=time.monotonic() + 600,
            job_dir=job_dir,
            on_usage=self.usages.append,
        )

    def video(self, style: PinnedRef | None = None) -> Video:
        raw = json.loads(VIDEO.read_text(encoding="utf-8"))
        visual = raw["settings"]["visual"]
        pinned = style or self.catalog.pin("art_style", "pixel")
        visual["art_style"] = pinned.model_dump()
        raw["settings"]["format"]["layout"] = self.catalog.pin(
            "template", "fixed_stage"
        ).model_dump()
        return Video.model_validate(raw)


def build_harness(
    root: Path,
    launcher: Callable[..., process.ProcessResult],
    *,
    runtime: Any = None,
) -> Harness:
    values = sandbox_config_values()
    values["wall_ms"] = {kind: 60000 for kind in values["wall_ms"]}
    counting = CountingLauncher(launcher)
    catalog = Registry(data_dir=root / "data")
    catalog.load()
    adapter = SandboxAdapter(
        runtime=runtime or FixedRuntime(),
        config=SandboxConfig.from_mapping(values),
        cache=ResultCache(root / "cache" / "sandbox" / "results"),
        launcher=counting,
    )
    llm = ScriptedLlm()
    service = TemplatesService(
        llm,
        adapter,
        catalog,
        builtin_parts=BUILTIN_PARTS_BUILDERS,
        builtin_layers=BUILTIN_LAYER_DRAWERS,
    )
    return Harness(service=service, catalog=catalog, llm=llm, launcher=counting, root=root)


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return build_harness(tmp_path, HostLauncher())


@contextlib.contextmanager
def no_new_calls(harness: Harness) -> Iterator[None]:
    """Assert that the block calls neither the model nor the sandbox launcher."""
    requests, calls = len(harness.llm.requests), harness.launcher.calls
    yield
    assert len(harness.llm.requests) == requests
    assert harness.launcher.calls == calls
