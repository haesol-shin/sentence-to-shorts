"""Scene data: choose one scene's visual from the catalog ids the app allows.

The module also holds the small plumbing the scene routes share: the prompt
loader, the JSON request with one repair call, and the UUIDv7 id issuer. It
keeps every result as a `ChangePlan` op so the service never writes state.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypeVar

from pydantic import BaseModel, Field, ValidationError

from app.ports import (
    AppError,
    CatalogPort,
    JobContext,
    LlmPart,
    LlmPort,
    LlmRequest,
    LlmResult,
    LlmTask,
    UnknownCatalogId,
    canonical_json,
)
from app.schemas.change import Op, SetOp
from app.schemas.common import CatalogId, CharacterRole, ContractModel, EntityId, Origin
from app.schemas.job import Stage, WaitingOn
from app.schemas.scene import (
    Anchor,
    Element,
    ElementKind,
    Placement,
    PlacementAnchor,
    Scene,
    SceneMotion,
    SceneVisual,
    TransitionIn,
)
from app.schemas.style_manifest import StyleManifest
from app.schemas.video import Video

SCENE_PROMPTS = Path(__file__).resolve().parent / "prompts" / "scene"
SCENE_DATA_MAX_TOKENS = 800

_CROCKFORD32 = "0123456789abcdefghjkmnpqrstvwxyz"
_UUID7_LOCK = threading.Lock()
_LAST_UUID7_MS = 0
_UUID7_RANDOM_BITS = 62
_UUID7_RAND_A_MASK = 0x0FFF

TModel = TypeVar("TModel", bound=BaseModel)


class ElementChoice(ContractModel):
    kind: ElementKind
    value: Annotated[str, Field(min_length=1, max_length=300)]
    anchor: Anchor
    reveal_line_id: EntityId | None = None


class SceneDataResponse(ContractModel):
    scene_id: EntityId
    background_id: CatalogId
    expression_id: CatalogId | None = None
    pose_id: CatalogId | None = None
    elements: Annotated[list[ElementChoice], Field(max_length=6)] = Field(
        default_factory=list
    )


@dataclass(frozen=True)
class SceneCatalog:
    """Ids the current art style and the video materials allow."""

    backgrounds: tuple[str, ...]
    expressions: tuple[str, ...]
    poses: tuple[str, ...]
    assets: tuple[str, ...]
    materials: tuple[str, ...]


def load_scene_prompt(route: str) -> str:
    """Read a scene route prompt next to this module, independent of the cwd."""
    path = SCENE_PROMPTS / route / "prompt.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise AppError("internal", detail={"prompt_route": route}) from error


def new_entity_id(prefix: str) -> str:
    """Issue an app id in the CONTRACTS 1.1 form: TypeID over a UUIDv7.

    The story service has no id issuer port, so the module issues the same
    UUIDv7 layout `ProjectStore.new_id` produces and keeps the process
    monotonic when two ids fall in the same millisecond.
    """
    return f"{prefix}_{_typeid_body(_uuid7().int)}"


def _uuid7() -> uuid.UUID:
    global _LAST_UUID7_MS
    with _UUID7_LOCK:
        now_ms = time.time_ns() // 1_000_000
        milliseconds = max(now_ms, _LAST_UUID7_MS + 1)
        _LAST_UUID7_MS = milliseconds
    random_bits = secrets.token_bytes(10)
    value = (milliseconds & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76
    value |= int.from_bytes(random_bits[:2], "big") & _UUID7_RAND_A_MASK
    value |= 0b10 << 62
    value |= int.from_bytes(random_bits[2:], "big") & ((1 << _UUID7_RANDOM_BITS) - 1)
    return uuid.UUID(int=value)


def _typeid_body(value: int) -> str:
    """26 Crockford base32 characters; the first one carries the top 3 bits."""
    return "".join(
        _CROCKFORD32[(value >> (5 * index)) & 0x1F] for index in range(25, -1, -1)
    )


def ask_json(
    *,
    route: str,
    task: LlmTask,
    schema_model: type[TModel],
    parts: list[LlmPart],
    validate: Callable[[TModel], list[str]],
    llm: LlmPort,
    ctx: JobContext,
    max_output_tokens: int,
) -> TModel:
    """Ask one route, check schema and app rules, and repair once on failure."""
    system = load_scene_prompt(route)
    schema = schema_model.model_json_schema()
    request_parts = list(parts)
    problems = ["no request was sent"]
    for _ in range(2):
        ctx.cancel.raise_if_set()
        result = llm.complete(
            LlmRequest(
                task=task,
                route=route,
                system=system,
                parts=request_parts,
                output_schema=schema,
                max_output_tokens=max_output_tokens,
            ),
            owner_id=ctx.owner_id,
            cancel=ctx.cancel,
            deadline=ctx.deadline,
            on_request=ctx.record_request,
        )
        ctx.record_usage(result.usage)
        model, problems = _checked(result, schema_model, validate)
        if model is not None:
            return model
        request_parts = [*parts, _repair_part(result, problems)]
    raise AppError("llm_invalid_output", detail={"route": route, "problems": problems[:4]})


def _checked(
    result: LlmResult,
    schema_model: type[TModel],
    validate: Callable[[TModel], list[str]],
) -> tuple[TModel | None, list[str]]:
    payload: Any = result.parsed
    if payload is None:
        try:
            payload = json.loads(result.text)
        except json.JSONDecodeError:
            return None, ["output is not JSON"]
    if not isinstance(payload, dict):
        return None, ["output must be a JSON object"]
    try:
        model = schema_model.model_validate(payload)
    except ValidationError as error:
        return None, [
            f"{_pointer(item['loc'])}: {item['msg']}" for item in error.errors()[:6]
        ]
    problems = validate(model)
    if problems:
        return None, problems
    return model, []


def _pointer(loc: Sequence[object]) -> str:
    parts = [str(item) for item in loc]
    return "/".join(parts) if parts else "(root)"


def _repair_part(result: LlmResult, problems: list[str]) -> LlmPart:
    payload = {
        "repair": {
            "problems": problems[:6],
            "previous_output": result.parsed
            if result.parsed is not None
            else result.text[:2000],
        }
    }
    return LlmPart(kind="text", text=json.dumps(payload, ensure_ascii=False, sort_keys=True))


def scene_catalog(catalog: CatalogPort, video: Video) -> SceneCatalog:
    """Allowed ids for this video: the pinned art style theme plus the materials."""
    ref = video.settings.visual.art_style
    try:
        manifest = catalog.get("art_style", ref.id, ref.revision)
    except UnknownCatalogId as error:
        raise AppError(
            "unknown_catalog_id", detail={"kind": "art_style", "id": ref.id}
        ) from error
    if not isinstance(manifest, StyleManifest):
        raise AppError("unknown_catalog_id", detail={"kind": "art_style", "id": ref.id})
    theme_id = video.settings.visual.theme_id
    theme = next((item for item in manifest.themes if item.id == theme_id), None)
    if theme is None:
        raise AppError("unknown_catalog_id", detail={"kind": "theme", "id": theme_id})
    return SceneCatalog(
        backgrounds=tuple(theme.backgrounds),
        expressions=tuple(manifest.rig.expressions),
        poses=tuple(manifest.rig.poses),
        assets=tuple(asset.id for asset in manifest.assets),
        materials=tuple(item.id for item in video.material),
    )


def plan_scene_data(
    video: Video,
    scene_ids: list[str],
    *,
    llm: LlmPort,
    catalog: CatalogPort,
    ctx: JobContext,
) -> list[Op]:
    """Fill the visual of every requested scene with one op per scene."""
    chosen = _ordered_scenes(video, scene_ids)
    if not chosen:
        return []
    choices = scene_catalog(catalog, video)
    role_none = video.settings.format.character_role == CharacterRole.none
    ops: list[Op] = []
    total = len(chosen)
    with ctx.stage(Stage.llm_scene_data):
        for done, scene in enumerate(chosen):
            ctx.progress(done=done, total=total, waiting_on=WaitingOn.llm)
            response = ask_json(
                route="scene_data",
                task=LlmTask.scene_data,
                schema_model=SceneDataResponse,
                parts=_scene_parts(video, scene, choices, role_none),
                validate=lambda item: _scene_problems(item, scene, choices, role_none),
                llm=llm,
                ctx=ctx,
                max_output_tokens=SCENE_DATA_MAX_TOKENS,
            )
            visual = _build_visual(scene, response, role_none)
            ops.append(
                SetOp(
                    op="set",
                    path=f"/scenes/{scene.id}/visual",
                    value=visual.model_dump(mode="json"),
                    origin=Origin.llm,
                )
            )
        ctx.progress(done=total, total=total, waiting_on=None)
    return ops


def _ordered_scenes(video: Video, scene_ids: Sequence[str]) -> list[Scene]:
    wanted = set(scene_ids)
    unknown = [scene_id for scene_id in wanted if scene_id not in video.scenes]
    if unknown:
        raise AppError("validation_failed", detail={"unknown_scene_ids": sorted(unknown)})
    return [video.scenes[scene_id] for scene_id in video.scene_order if scene_id in wanted]


def _scene_parts(
    video: Video,
    scene: Scene,
    choices: SceneCatalog,
    role_none: bool,
) -> list[LlmPart]:
    payload = {
        "language": video.settings.language.value,
        "register": video.settings.format.register_value.value,
        "humor": video.settings.format.humor.value,
        "character_role": video.settings.format.character_role.value,
        "theme_id": video.settings.visual.theme_id,
        "scene": {
            "id": scene.id,
            "beat_id": scene.beat_id,
            "beat_label": scene.beat_label,
            "lines": [
                {
                    "id": line.id,
                    "display_text": line.display_text,
                    "speech_text": line.speech_text,
                }
                for line in scene.lines
            ],
        },
        "materials": [{"id": item.id, "text": item.text} for item in video.material],
        "allowed": {
            "backgrounds": list(choices.backgrounds),
            "expressions": [] if role_none else list(choices.expressions),
            "poses": [] if role_none else list(choices.poses),
            "assets": list(choices.assets),
            "materials": [item.id for item in video.material],
            "sfx": [],
        },
    }
    return [LlmPart(kind="text", text=canonical_json(payload).decode("utf-8"))]


def _scene_problems(
    response: SceneDataResponse,
    scene: Scene,
    choices: SceneCatalog,
    role_none: bool,
) -> list[str]:
    problems: list[str] = []
    if response.scene_id != scene.id:
        problems.append(f"scene_id must stay {scene.id}")
    if response.background_id not in choices.backgrounds:
        problems.append(f"background_id {response.background_id} is not an allowed background")
    if not role_none:
        if response.expression_id not in choices.expressions:
            problems.append("expression_id must be one of the allowed expressions")
        if response.pose_id not in choices.poses:
            problems.append("pose_id must be one of the allowed poses")
    line_ids = {line.id for line in scene.lines}
    problems.extend(_element_problems(response, choices, line_ids))
    return problems


def _element_problems(
    response: SceneDataResponse,
    choices: SceneCatalog,
    line_ids: set[str],
) -> list[str]:
    problems: list[str] = []
    for element in response.elements:
        if element.kind is ElementKind.asset and element.value not in choices.assets:
            problems.append(f"element asset {element.value} is not an allowed asset")
        if element.kind is ElementKind.material and element.value not in choices.materials:
            problems.append(f"element material {element.value} is not a material of this video")
        if element.reveal_line_id is not None and element.reveal_line_id not in line_ids:
            problems.append(f"reveal_line_id {element.reveal_line_id} is not a line of this scene")
    return problems


def _build_visual(
    scene: Scene,
    response: SceneDataResponse,
    role_none: bool,
) -> SceneVisual:
    characters: list[Placement] = []
    if not role_none:
        expression_id = response.expression_id
        pose_id = response.pose_id
        if expression_id is None or pose_id is None:
            raise AppError("llm_invalid_output", detail={"scene_id": scene.id})
        characters = [
            Placement(
                anchor=PlacementAnchor.center,
                expression_id=expression_id,
                pose_id=pose_id,
                motion=SceneMotion.none,
            )
        ]
    elements = [
        Element(
            id=new_entity_id("e"),
            kind=item.kind,
            value=item.value,
            anchor=item.anchor,
            reveal_line_id=item.reveal_line_id,
        )
        for item in response.elements
    ]
    return SceneVisual(
        background_id=response.background_id,
        characters=characters,
        elements=elements,
        sfx=[],
        transition_in=TransitionIn.cut,
    )
