"""Precheck reports the promise, the answer, the claims and the assumptions."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from app.jobs import CancelFlag, LocalJobContext
from app.ports import AppError, LlmRequest, LlmResult
from app.schemas.job import Stage, Usage
from app.schemas.video import Material, Video
from app.services.story.precheck import run_precheck

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "fixtures" / "contracts" / "valid" / "video_ko_draft_no_visual.json"
MATERIAL_ID = "m_0nzvrzf0tp9wba44f6yvh6nzpr"


class ScriptedLlm:
    """Replays recorded responses in order and keeps every request."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.requests: list[LlmRequest] = []

    def complete(
        self, req: LlmRequest, *, owner_id: str, cancel: Any, deadline: float
    ) -> LlmResult:
        self.requests.append(req)
        payload = self.responses.pop(0)
        return LlmResult(
            text=json.dumps(payload, ensure_ascii=False),
            parsed=payload,
            usage=Usage(
                stage=Stage.llm_precheck,
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

    def auth_state(self, owner_id: str) -> str:
        return "ok"


@pytest.fixture
def ctx(tmp_path: Path) -> LocalJobContext:
    return LocalJobContext(
        cancel_token=CancelFlag(), deadline=time.monotonic() + 60, job_dir=tmp_path
    )


def _video() -> Video:
    video = Video.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    return video.model_copy(
        update={"material": [Material(id=MATERIAL_ID, text="물은 90도에서 우린다")]}
    )


def _response(video: Video, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "opening_promise": "커피를 고르는 기준 세 가지를 알려 줘요.",
        "ending_answer": "세 번째 기준으로 물의 온도를 지켜요.",
        "claims": [
            {
                "scene_id": video.scene_order[2],
                "text": "물의 온도는 90도다.",
                "material_id": MATERIAL_ID,
            }
        ],
        "hypotheticals": [video.scene_order[0]],
    }
    payload.update(overrides)
    return payload


def test_30_precheck_reports_promise_answer_claims_and_hypotheticals(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    llm = ScriptedLlm(_response(video))

    report = run_precheck(video, llm=llm, ctx=ctx)

    data = json.loads(llm.requests[0].parts[0].text)
    assert data["register"] == "friendly"
    assert report.opening_promise == "커피를 고르는 기준 세 가지를 알려 줘요."
    assert report.ending_answer == "세 번째 기준으로 물의 온도를 지켜요."
    assert [claim.material_id for claim in report.claims] == [MATERIAL_ID]
    assert [claim.scene_id for claim in report.claims] == [video.scene_order[2]]
    assert report.hypotheticals == [video.scene_order[0]]


def test_30_precheck_repairs_once_when_a_scene_id_is_unknown(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    llm = ScriptedLlm(
        _response(video, hypotheticals=["s_0gv16xq3n089nbs6wykgccs0zf"]),
        _response(video),
    )

    report = run_precheck(video, llm=llm, ctx=ctx)

    assert len(llm.requests) == 2
    assert json.loads(llm.requests[1].parts[-1].text)["repair"]["problems"]
    assert report.hypotheticals == [video.scene_order[0]]


def test_30_precheck_fails_after_one_repair_for_a_material_outside_the_video(
    ctx: LocalJobContext,
) -> None:
    video = _video()
    wrong = [
        {
            "scene_id": video.scene_order[2],
            "text": "물의 온도는 90도다.",
            "material_id": "m_0dwky4wxht8qraax96tzhh4kgx",
        }
    ]
    llm = ScriptedLlm(_response(video, claims=wrong), _response(video, claims=wrong))

    with pytest.raises(AppError) as raised:
        run_precheck(video, llm=llm, ctx=ctx)

    assert raised.value.code == "llm_invalid_output"
    assert len(llm.requests) == 2


def test_30_precheck_rejects_a_video_without_scenes(ctx: LocalJobContext) -> None:
    video = _video().model_copy(update={"scene_order": [], "scenes": {}})
    llm = ScriptedLlm()

    with pytest.raises(AppError) as raised:
        run_precheck(video, llm=llm, ctx=ctx)

    assert raised.value.code == "scenes_not_confirmed"
    assert llm.requests == []
