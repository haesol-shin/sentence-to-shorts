"""Scene data fills visuals from the allowed catalog ids only."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.jobs import CancelFlag, LocalJobContext
from app.plugins.registry import Registry
from app.ports import AppError, LlmRequest, LlmResult
from app.schemas.common import CharacterRole
from app.schemas.job import Stage, Usage
from app.schemas.scene import SceneVisual
from app.schemas.video import Material, Video
from app.services.story.scene_data import plan_scene_data

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "contracts" / "valid" / "video_ko_draft_no_visual.json"
MATERIAL_ID = "m_0nzvrzf0tp9wba44f6yvh6nzpr"
_CROCKFORD32 = "0123456789abcdefghjkmnpqrstvwxyz"


class ScriptedLlm:
    """Replays recorded responses in order and keeps every request."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.requests: list[LlmRequest] = []

    def complete(
        self, req: LlmRequest, *, cancel: Any, deadline: float
    ) -> LlmResult:
        self.requests.append(req)
        payload = self.responses.pop(0)
        return LlmResult(
            text=json.dumps(payload, ensure_ascii=False),
            parsed=payload,
            usage=Usage(
                stage=Stage.llm_scene_data,
                provider="scripted",
                model="scripted",
                effort=None,
                input_tokens=None,
                output_tokens=None,
                cache_read_tokens=None,
                cost_usd=None,
                wall_ms=0,
                retries=0,
            ),
        )

    def auth_state(self) -> str:
        return "ok"


@pytest.fixture
def ctx(tmp_path: Path) -> LocalJobContext:
    return LocalJobContext(
        cancel_token=CancelFlag(), deadline=time.monotonic() + 60, job_dir=tmp_path
    )


def _video(
    *,
    sfx_enabled: bool = True,
    character_role: CharacterRole | None = None,
    material_ids: tuple[str, ...] = (),
) -> Video:
    video = Video.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    settings = video.settings
    audio = settings.audio.model_copy(update={"sfx_enabled": sfx_enabled})
    fmt = settings.format
    if character_role is not None:
        fmt = fmt.model_copy(update={"character_role": character_role})
    settings = settings.model_copy(update={"audio": audio, "format": fmt})
    material = [Material(id=item, text="물은 90도에서 우린다") for item in material_ids]
    return video.model_copy(update={"settings": settings, "material": material})


def _response(scene_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scene_id": scene_id,
        "background_id": "bg_village",
        "expression_id": "expr_happy",
        "pose_id": "pose_idle",
        "elements": [],
    }
    payload.update(overrides)
    return payload


def _visual(op: Any) -> SceneVisual:
    return SceneVisual.model_validate(op.value)


def test_19_scene_data_fills_only_the_requested_scenes(ctx: LocalJobContext) -> None:
    video = _video(sfx_enabled=False)
    first, _, last = video.scene_order
    llm = ScriptedLlm(
        _response(first, background_id="bg_stars"), _response(last)
    )

    ops = plan_scene_data(video, [last, first], llm=llm, catalog=Registry(), ctx=ctx)

    assert [op.path for op in ops] == [
        f"/scenes/{first}/visual",
        f"/scenes/{last}/visual",
    ]
    assert _visual(ops[0]).background_id == "bg_stars"
    assert _visual(ops[1]).background_id == "bg_village"


def test_19_scene_data_repairs_once_when_a_catalog_id_is_outside_the_list(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    scene_id = video.scene_order[0]
    llm = ScriptedLlm(
        _response(scene_id, background_id="bg_moon"), _response(scene_id)
    )

    ops = plan_scene_data(video, [scene_id], llm=llm, catalog=Registry(), ctx=ctx)

    assert len(llm.requests) == 2
    repair = json.loads(llm.requests[1].parts[-1].text)
    assert repair["repair"]["problems"]
    assert _visual(ops[0]).background_id == "bg_village"


def test_19_scene_data_fails_with_llm_invalid_output_after_one_repair(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    scene_id = video.scene_order[0]
    llm = ScriptedLlm(
        _response(scene_id, background_id="bg_moon"),
        _response(scene_id, pose_id="pose_run"),
    )

    with pytest.raises(AppError) as raised:
        plan_scene_data(video, [scene_id], llm=llm, catalog=Registry(), ctx=ctx)

    assert raised.value.code == "llm_invalid_output"
    assert len(llm.requests) == 2


def test_19_scene_data_keeps_sfx_empty_without_a_scene_request(
    ctx: LocalJobContext,
) -> None:
    video = _video(sfx_enabled=True)
    scene = video.scenes[video.scene_order[0]]
    llm = ScriptedLlm(_response(scene.id))

    ops = plan_scene_data(video, [scene.id], llm=llm, catalog=Registry(), ctx=ctx)

    data = json.loads(llm.requests[0].parts[0].text)
    assert data["allowed"]["sfx"] == []
    assert _visual(ops[0]).sfx == []


def test_19_scene_data_skips_the_character_when_the_role_is_none(
    ctx: LocalJobContext,
) -> None:
    video = _video(character_role=CharacterRole.none)
    scene_id = video.scene_order[0]
    llm = ScriptedLlm(
        {"scene_id": scene_id, "background_id": "bg_village", "elements": []}
    )

    ops = plan_scene_data(video, [scene_id], llm=llm, catalog=Registry(), ctx=ctx)

    data = json.loads(llm.requests[0].parts[0].text)
    assert data["allowed"]["expressions"] == []
    assert _visual(ops[0]).characters == []


def test_18_scene_data_links_material_elements_to_video_materials(
    ctx: LocalJobContext,
) -> None:
    video = _video(material_ids=(MATERIAL_ID,))
    scene = video.scenes[video.scene_order[0]]
    element = {"kind": "material", "value": MATERIAL_ID, "anchor": "bottom"}
    llm = ScriptedLlm(
        _response(scene.id, elements=[{**element, "value": "m_0dwky4wxht8qraax96tzhh4kgx"}]),
        _response(scene.id, elements=[element]),
    )

    ops = plan_scene_data(video, [scene.id], llm=llm, catalog=Registry(), ctx=ctx)

    assert len(llm.requests) == 2
    elements = _visual(ops[0]).elements
    assert [(item.kind.value, item.value) for item in elements] == [
        ("material", MATERIAL_ID)
    ]
    assert elements[0].id.startswith("e_")


def test_19_scene_data_issues_uuid7_typeids_for_elements(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    scene = video.scenes[video.scene_order[0]]
    llm = ScriptedLlm(
        _response(
            scene.id,
            elements=[{"kind": "label", "value": "물의 온도", "anchor": "top"}],
        )
    )

    ops = plan_scene_data(video, [scene.id], llm=llm, catalog=Registry(), ctx=ctx)

    element_id = _visual(ops[0]).elements[0].id
    assert element_id.startswith("e_")
    generated = _uuid_of(element_id)
    assert generated.version == 7
    assert generated.variant == uuid.RFC_4122


def _uuid_of(value: str) -> uuid.UUID:
    _prefix, _, body = value.partition("_")
    number = 0
    for char in body:
        number = (number << 5) | _CROCKFORD32.index(char)
    return uuid.UUID(int=number)


def test_19_scene_data_rejects_unknown_scene_ids(ctx: LocalJobContext) -> None:
    video = _video()
    llm = ScriptedLlm()

    with pytest.raises(AppError) as raised:
        plan_scene_data(
            video, ["s_0gv16xq3n089nbs6wykgccs0zf"], llm=llm, catalog=Registry(), ctx=ctx
        )

    assert raised.value.code == "validation_failed"
    assert llm.requests == []
