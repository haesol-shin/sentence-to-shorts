"""Acceptance paths of the pipeline runner.

Every test drives the production dispatcher and the production cache-key graph.
Media, voice, sound and template work are deterministic fakes that write files,
so the tests observe cache keys, publication, checkpoints and service calls
without starting ffmpeg, a TTS engine or an LLM.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.ports import AppError, Cancelled, ReferenceOutcome, Usage
from app.schemas.change import SetOp, SetScriptOp, Target
from app.schemas.common import Origin
from app.schemas.job import Effort, JobKind, Stage, StageRecord
from app.schemas.script import Script, ScriptSource
from app.schemas.settings import LockKey, LockState
from app.schemas.video import ArtifactState, VideoStage
from app.services.pipeline.build import run_generate
from app.services.pipeline.dependencies import build_view, plan_change
from app.services.pipeline.run import run
from app.services.pipeline.run_state import check_context
from tests.pipeline.support import Harness, build_harness


@pytest.fixture
def harness(tmp_path: Path):
    opened = build_harness(tmp_path)
    yield opened
    opened.close()


def _run(
    harness: Harness,
    kind: JobKind,
    *,
    video=None,
    input: dict | None = None,
    base_revision: int | None = None,
    deadline_seconds: float = 3600.0,
):
    job = harness.job(kind, video=video, input=input, base_revision=base_revision)
    ctx = harness.context(job, deadline_seconds=deadline_seconds)
    result = run(job, ctx, harness.services)
    return result, ctx


def _all_calls(harness: Harness) -> list[object]:
    return [
        *harness.render.still_calls,
        *harness.render.clip_calls,
        *harness.voice.synthesize_calls,
        *harness.voice.timing_calls,
        *harness.templates.parts.build_calls,
        *harness.templates.layers.draw_calls,
    ]


def _digest(harness: Harness, artifact_id: str) -> str:
    return hashlib.sha256(harness.artifacts.path(artifact_id).read_bytes()).hexdigest()


def test_2_preview_before_script_confirmed_makes_no_render_calls(harness: Harness) -> None:
    video = harness.new_video(stage=VideoStage.draft, visuals=False)

    with pytest.raises(AppError) as caught:
        _run(harness, JobKind.preview, video=video)

    assert caught.value.code == "script_not_confirmed"
    assert _all_calls(harness) == []
    assert harness.story.scene_data_calls == []


def test_2_preview_fills_scene_data_then_reuses_cached_stills(harness: Harness) -> None:
    video = harness.new_video(stage=VideoStage.script_confirmed, visuals=False)

    first, _ = _run(harness, JobKind.preview, video=video)

    head = harness.projects.get_video(video.id)
    assert head.revision == 2
    assert harness.story.scene_data_calls == [list(head.scene_order)]
    assert all(scene.visual is not None for scene in head.scenes.values())
    assert set(first["artifacts"]["still"]) == set(head.scene_order)
    for record in first["stages"]:
        StageRecord.model_validate(record)
    view = build_view(head, harness.services)
    assert all(item.still.state is ArtifactState.fresh for item in view.scenes.values())

    still_calls = list(harness.render.still_calls)
    second, _ = _run(harness, JobKind.preview, video=head)

    assert harness.render.still_calls == still_calls
    assert set(second["artifacts"]["still"]) == set(head.scene_order)
    assert second["cache_hits"] >= len(head.scene_order)
    assert all(
        second["artifacts"]["still"][scene_id] == first["artifacts"]["still"][scene_id]
        for scene_id in head.scene_order
    )


def test_2_preview_rejects_scene_data_outside_the_missing_visuals(
    harness: Harness,
) -> None:
    video = harness.new_video(stage=VideoStage.script_confirmed, visuals=False)
    harness.story.scene_data_ops = [
        SetOp(
            op="set",
            path="/settings/format/humor",
            value="light",
            origin=Origin.llm,
        )
    ]

    with pytest.raises(AppError) as caught:
        _run(harness, JobKind.preview, video=video)

    assert caught.value.code == "invalid_op"
    assert harness.projects.get_video(video.id).revision == video.revision
    assert harness.projects.list_changes(video.id) == []
    assert _all_calls(harness) == []


def test_2_failed_preview_leaves_head_and_retry_reuses_finished_stills(
    harness: Harness,
) -> None:
    video = harness.new_video(stage=VideoStage.script_confirmed, visuals=False)
    harness.render.fail_still = video.scene_order[1]

    with pytest.raises(AppError) as caught:
        _run(harness, JobKind.preview, video=video)

    assert caught.value.code == "render_failed"
    assert harness.projects.get_video(video.id).revision == video.revision
    assert harness.projects.list_changes(video.id) == []
    harness.render.fail_still = None
    still_calls = len(harness.render.still_calls)

    result, _ = _run(harness, JobKind.preview, video=video)

    assert result["revision"] == video.revision + 1
    assert harness.render.still_calls[still_calls:] == [video.scene_order[1]] + [
        scene_id for scene_id in video.scene_order[2:]
    ]


def test_10_text_only_change_keeps_tts_and_rebuilds_only_that_scene(
    harness: Harness,
) -> None:
    first, _ = _run(harness, JobKind.generate)
    scene_id = harness.video.scene_order[0]
    line_id = harness.video.scenes[scene_id].lines[0].id
    tts_calls = list(harness.voice.synthesize_calls)
    still_calls = len(harness.render.still_calls)
    clip_ids = dict(first["artifacts"]["clip"])

    changed = harness.revise_scene(scene_id, display_text="바뀐 화면 글")
    second, _ = _run(harness, JobKind.generate, video=changed)

    assert harness.voice.synthesize_calls == tts_calls
    assert second["artifacts"]["tts"][line_id] == first["artifacts"]["tts"][line_id]
    assert harness.render.still_calls[still_calls:] == [scene_id]
    assert second["rebuilt_scene_ids"] == [scene_id]
    for other in changed.scene_order:
        if other == scene_id:
            assert second["artifacts"]["clip"][other] != clip_ids[other]
        else:
            assert second["artifacts"]["clip"][other] == clip_ids[other]


def test_10_speech_change_rebuilds_only_that_line_tts(harness: Harness) -> None:
    _run(harness, JobKind.generate)
    scene_id = harness.video.scene_order[0]
    line_id = harness.video.scenes[scene_id].lines[0].id
    tts_calls = list(harness.voice.synthesize_calls)

    changed = harness.revise_scene(scene_id, speech_text="바뀐 말할 글")
    _run(harness, JobKind.generate, video=changed)

    assert harness.voice.synthesize_calls == [*tts_calls, line_id]


def test_12_scene_rewrite_leaves_other_clips_and_render_calls_alone(
    harness: Harness,
) -> None:
    first, _ = _run(harness, JobKind.generate)
    target = harness.video.scene_order[1]
    others = [scene_id for scene_id in harness.video.scene_order if scene_id != target]
    clip_ids = dict(first["artifacts"]["clip"])
    still_calls = len(harness.render.still_calls)
    clip_calls = len(harness.render.clip_calls)

    changed = harness.revise_scene(
        target, display_text="다시 쓴 장면 글", speech_text="다시 쓴 장면"
    )
    second, _ = _run(harness, JobKind.generate, video=changed)

    new_still_calls = harness.render.still_calls[still_calls:]
    new_clip_calls = harness.render.clip_calls[clip_calls:]
    assert new_still_calls == [target]
    assert new_clip_calls == [target]
    assert all(
        second["artifacts"]["clip"][scene_id] == clip_ids[scene_id] for scene_id in others
    )
    assert all(
        _digest(harness, second["artifacts"]["clip"][scene_id])
        == _digest(harness, clip_ids[scene_id])
        for scene_id in others
    )


def test_14_bgm_replacement_rebuilds_mix_and_final_without_rendering(
    harness: Harness,
) -> None:
    first, _ = _run(harness, JobKind.generate)
    calls = _all_calls(harness)
    mix_calls = len(harness.sound.mix_calls)
    final_calls = len(harness.assemble.final_calls)
    srt_id = first["artifacts"]["srt"]

    changed = harness.change_bgm(harness.catalog.pin("bgm", "calm_happy_lullaby"))
    second, _ = _run(harness, JobKind.generate, video=changed)

    assert _all_calls(harness) == calls
    assert len(harness.sound.mix_calls) == mix_calls + 1
    assert len(harness.assemble.final_calls) == final_calls + 1
    assert second["rebuilt_scene_ids"] == []
    assert second["artifacts"]["srt"] == srt_id
    assert second["artifacts"]["mix"] != first["artifacts"]["mix"]
    assert second["artifacts"]["final"] != first["artifacts"]["final"]
    states = {record["stage"]: record["state"] for record in second["stages"]}
    assert states["mix"] == "done"
    assert states["assemble"] == "done"
    assert states["srt"] == "skipped"


def test_26_reorder_rebuilds_no_scene_artifacts(harness: Harness) -> None:
    first, _ = _run(harness, JobKind.generate)
    calls = _all_calls(harness)
    clip_ids = dict(first["artifacts"]["clip"])
    order = list(reversed(harness.video.scene_order))

    changed = harness.reorder(order)
    second, _ = _run(harness, JobKind.generate, video=changed)

    assert _all_calls(harness) == calls
    assert second["rebuilt_scene_ids"] == []
    assert all(
        second["artifacts"]["clip"][scene_id] == clip_ids[scene_id] for scene_id in order
    )


def test_10_failed_scene_retry_rebuilds_only_the_failed_clip(harness: Harness) -> None:
    failed = harness.video.scene_order[-1]
    harness.render.fail_clip = failed

    with pytest.raises(AppError) as caught:
        _run(harness, JobKind.generate)

    assert caught.value.code == "render_failed"
    synthesize_calls = list(harness.voice.synthesize_calls)

    harness.render.fail_clip = None
    clip_calls = len(harness.render.clip_calls)
    still_calls = len(harness.render.still_calls)

    result, ctx = _run(harness, JobKind.generate)

    assert harness.render.clip_calls[clip_calls:] == [failed]
    assert harness.render.still_calls[still_calls:] == []
    assert harness.voice.synthesize_calls == synthesize_calls
    assert result["artifacts"]["final"] is not None
    assert ctx.checkpoints != []


def test_11_stale_base_revision_is_not_linked_to_the_current_view(
    harness: Harness,
) -> None:
    video = harness.video
    changed = harness.revise_scene(
        video.scene_order[0], display_text="동시에 바뀐 장면 글"
    )
    before = list(harness.render.still_calls)

    job = harness.job(JobKind.generate, video=video, base_revision=video.revision)
    ctx = harness.context(job)
    with pytest.raises(AppError) as caught:
        run_generate(job, ctx, harness.services)

    assert caught.value.code == "stale_revision"
    assert harness.render.still_calls == before
    view = build_view(changed, harness.services)
    assert view.scenes[video.scene_order[0]].still.state is not ArtifactState.fresh


def test_11_revision_change_during_render_publishes_no_stale_still(
    harness: Harness,
) -> None:
    target = harness.video.scene_order[0]

    def revise(_: str) -> None:
        harness.render.still_hook = None
        harness.revise_scene(target, display_text="렌더 중 바뀐 글")

    harness.render.still_hook = revise
    job = harness.job(JobKind.generate, video=harness.video)
    ctx = harness.context(job)

    with pytest.raises(AppError) as caught:
        run_generate(job, ctx, harness.services)

    assert caught.value.code == "stale_revision"
    assert all(record.stage is not Stage.still for record in ctx.checkpoints)
    head = harness.projects.get_video(harness.video.id)
    view = build_view(head, harness.services)
    assert view.scenes[target].still.state is not ArtifactState.fresh


def test_11_deadline_and_cancel_stop_before_any_publication(harness: Harness) -> None:
    job = harness.job(JobKind.generate, video=harness.video)
    ctx = harness.context(job, deadline_seconds=0)
    with pytest.raises(AppError) as deadline:
        run_generate(job, ctx, harness.services)
    assert deadline.value.code == "deadline_exceeded"

    job = harness.job(JobKind.generate, video=harness.video)
    ctx = harness.context(job)
    ctx.cancel.cancel()
    with pytest.raises(Cancelled):
        run_generate(job, ctx, harness.services)
    assert ctx.checkpoints == []


def test_8_generate_stage_records_are_valid_and_cache_hits_are_reported(
    harness: Harness,
) -> None:
    first, first_ctx = _run(harness, JobKind.generate)
    for record in first["stages"]:
        StageRecord.model_validate(record)
    stages = [record["stage"] for record in first["stages"]]
    assert stages.index("tts") < stages.index("align") < stages.index("clip")
    assert first_ctx.stage_events

    second, _ = _run(harness, JobKind.generate)
    for record in second["stages"]:
        StageRecord.model_validate(record)
    assert second["cache_hits"] > 0
    assert any(record["state"] == "skipped" for record in second["stages"])
    assert second["artifacts"] == first["artifacts"]
    first_states = {record["stage"]: record["state"] for record in first["stages"]}
    assert first_states["mix"] == "done"
    assert first_states["assemble"] == "done"
    assert first_states["srt"] == "done"


def _draft_video_without_script(harness: Harness):
    video = harness.new_video(stage=VideoStage.concept_confirmed, visuals=False)
    return harness.revise(video, script=None, scenes={}, scene_order=[])


def test_4_1_draft_applies_when_head_is_current_and_never_renders(
    harness: Harness,
) -> None:
    video = _draft_video_without_script(harness)
    harness.story.draft_ops = [
        SetOp(op="set", path="/topic", value="합성 주제", origin=Origin.llm),
        SetOp(
            op="set",
            path="/settings/format/humor",
            value="light",
            origin=Origin.llm,
        ),
    ]

    result, ctx = _run(
        harness,
        JobKind.draft,
        video=video,
        input={"base_revision": video.revision, "message": "합성 요청", "card_id": None},
    )

    head = harness.projects.get_video(video.id)
    assert head.revision == video.revision + 1
    assert result["applied_revision"] == head.revision
    assert head.topic == "합성 주제"
    assert head.settings.format.humor.value == "light"
    assert ctx.stage_events == []
    assert _all_calls(harness) == []


def test_4_1_draft_stale_base_leaves_its_plan_proposed(harness: Harness) -> None:
    video = _draft_video_without_script(harness)
    advanced = harness.revise(video, topic="새 주제")
    harness.story.draft_ops = [
        SetOp(op="set", path="/topic", value="합성 주제", origin=Origin.llm)
    ]

    result, _ = _run(
        harness,
        JobKind.draft,
        video=video,
        input={"base_revision": video.revision, "message": "합성 요청", "card_id": None},
    )

    head = harness.projects.get_video(video.id)
    assert head.revision == advanced.revision
    assert head.topic == "새 주제"
    assert result["status"] == "proposed"
    assert result["applied_revision"] is None
    plan = harness.projects.get_change(result["change_id"])
    assert plan.status.value == "proposed"
    assert _all_calls(harness) == []

    later = harness.revise(advanced, topic="또 다른 주제")
    with pytest.raises(AppError) as caught:
        harness.services.project.commit(plan, later.revision)
    assert caught.value.code == "change_stale"
    assert harness.projects.get_change(plan.id).status.value == "stale"


@pytest.mark.parametrize("protection", ["user_origin", "lock"])
def test_26_draft_never_overwrites_user_or_locked_values(
    harness: Harness, protection: str
) -> None:
    video = _draft_video_without_script(harness)
    settings = video.settings.model_copy(deep=True)
    if protection == "user_origin":
        settings.origins["/format/humor"] = Origin.user
    else:
        settings.locks[LockKey.humor] = LockState.locked
    video = harness.revise(video, settings=settings)
    harness.story.draft_ops = [
        SetOp(op="set", path="/topic", value="합성 주제", origin=Origin.llm),
        SetOp(op="set", path="/settings/format/humor", value="light", origin=Origin.llm),
    ]

    result, _ = _run(
        harness,
        JobKind.draft,
        video=video,
        input={"base_revision": video.revision, "message": "합성 요청", "card_id": None},
    )

    head = harness.projects.get_video(video.id)
    assert result["status"] == "proposed"
    assert result["applied_revision"] is None
    assert head.revision == video.revision
    assert head.settings.format.humor.value == "none"
    reason = "user_value_overwrite" if protection == "user_origin" else "lock_change"
    assert reason in result["confirmation_reasons"]


def test_4_1_script_rewrite_waits_for_confirmation_and_never_renders(
    harness: Harness,
) -> None:
    video = harness.video
    harness.story.script_ops = [
        SetScriptOp(
            op="set_script",
            script=video.script,
            scenes=[video.scenes[scene_id] for scene_id in video.scene_order],
        )
    ]

    result, _ = _run(
        harness,
        JobKind.script,
        video=video,
        input={"base_revision": video.revision},
    )

    plan = harness.projects.get_change(result["change_id"])
    assert plan.status.value == "proposed"
    assert plan.requires_confirmation
    assert result["applied_revision"] is None
    assert harness.projects.get_video(video.id).revision == video.revision
    assert _all_calls(harness) == []


def test_4_1_first_script_applies_without_confirmation(harness: Harness) -> None:
    video = _draft_video_without_script(harness)
    scene = harness.video.scenes[harness.video.scene_order[0]]
    script = Script(source=ScriptSource.llm, raw_text="합성 대본", title="합성")
    harness.story.script_ops = [SetScriptOp(op="set_script", script=script, scenes=[scene])]

    result, _ = _run(
        harness,
        JobKind.script,
        video=video,
        input={"base_revision": video.revision},
    )

    head = harness.projects.get_video(video.id)
    assert result["applied_revision"] == head.revision
    assert head.script is not None
    assert head.scene_order == [scene.id]
    assert _all_calls(harness) == []


def test_4_1_chat_single_value_applies_and_multi_scene_waits(harness: Harness) -> None:
    video = harness.video
    harness.story.proposal_ops = [
        SetOp(
            op="set",
            path="/settings/format/humor",
            value="light",
            origin=Origin.llm,
        )
    ]
    result, _ = _run(
        harness,
        JobKind.chat,
        video=video,
        input={
            "base_revision": video.revision,
            "text": "유머를 조금 넣어",
            "target": {"scene_id": None, "pointer": None},
        },
    )
    head = harness.projects.get_video(video.id)
    assert result["applied_revision"] == head.revision
    assert head.settings.format.humor.value == "light"

    scene_ids = video.scene_order[:2]
    ops = []
    for scene_id in scene_ids:
        scene = head.scenes[scene_id]
        lines = [
            line.model_copy(update={"display_text": f"바뀐 글 {index}"})
            for index, line in enumerate(scene.lines)
        ]
        ops.append(
            SetOp(
                op="set",
                path=f"/scenes/{scene_id}/lines",
                value=[line.model_dump(mode="json") for line in lines],
                origin=Origin.llm,
            )
        )
    harness.story.proposal_ops = ops
    result, _ = _run(
        harness,
        JobKind.chat,
        video=head,
        input={
            "base_revision": head.revision,
            "text": "두 장면을 고쳐",
            "target": {"scene_id": None, "pointer": None},
        },
    )
    plan = harness.projects.get_change(result["change_id"])
    assert plan.status.value == "proposed"
    assert plan.requires_confirmation
    assert harness.projects.get_video(video.id).revision == head.revision
    assert _all_calls(harness) == []


def test_4_1_scene_rewrite_is_constrained_to_its_target(harness: Harness) -> None:
    video = harness.video
    target = video.scene_order[0]
    other = video.scene_order[1]
    harness.story.rewrite_ops_by_scene[target] = [
        SetOp(
            op="set",
            path=f"/scenes/{other}/beat_label",
            value="다른 장면",
            origin=Origin.llm,
        )
    ]

    with pytest.raises(AppError) as caught:
        _run(
            harness,
            JobKind.chat,
            video=video,
            input={
                "base_revision": video.revision,
                "text": "",
                "target": {"scene_id": target, "pointer": None},
            },
        )

    assert caught.value.code == "invalid_op"
    assert harness.projects.get_video(video.id).revision == video.revision
    assert _all_calls(harness) == []


def test_4_1_targeted_chat_rejects_other_scene_ops(harness: Harness) -> None:
    video = harness.video
    target, other = video.scene_order[:2]
    harness.story.proposal_ops = [
        SetOp(
            op="set",
            path=f"/scenes/{other}/beat_label",
            value="다른 장면",
            origin=Origin.llm,
        )
    ]

    with pytest.raises(AppError) as caught:
        _run(
            harness,
            JobKind.chat,
            video=video,
            input={
                "base_revision": video.revision,
                "text": "이 장면만 고쳐",
                "target": {"scene_id": target, "pointer": None},
            },
        )

    assert caught.value.code == "invalid_op"
    assert harness.projects.get_video(video.id).revision == video.revision
    assert harness.projects.list_changes(video.id) == []
    assert _all_calls(harness) == []


def test_4_1_style_and_template_create_plans_without_rendering(harness: Harness) -> None:
    video = harness.video
    style_result, _ = _run(
        harness,
        JobKind.style,
        video=video,
        input={
            "video_id": video.id,
            "base_revision": video.revision,
            "instruction": "합성 그림체",
            "base_style": None,
            "use_reference": False,
        },
    )
    assert harness.templates.style_calls == ["합성 그림체"]
    style_plan = harness.projects.get_change(style_result["change_id"])
    assert style_plan.requires_confirmation
    assert style_plan.status.value == "proposed"

    template_result, _ = _run(
        harness,
        JobKind.template,
        video=video,
        input={
            "video_id": video.id,
            "base_revision": video.revision,
            "instruction": "합성 화면 틀",
        },
    )
    assert harness.templates.template_calls == ["합성 화면 틀"]
    template_plan = harness.projects.get_change(template_result["change_id"])
    assert template_plan.requires_confirmation
    assert template_plan.status.value == "proposed"
    assert _all_calls(harness) == []


def test_4_1_reference_applies_existing_change_when_it_needs_no_confirmation(
    harness: Harness,
) -> None:
    video = harness.video
    op = SetOp(
        op="set",
        path="/settings/format/humor",
        value="light",
        origin=Origin.reference,
    )
    plan = plan_change(
        video, [op], "reference", Target(scene_id=None, pointer=None), harness.services
    )
    harness.projects.put_change(plan)
    harness.reference.outcome = ReferenceOutcome(change_id=plan.id, reference=None)

    result, _ = _run(
        harness,
        JobKind.reference,
        video=video,
        input={"base_revision": video.revision, "url": "https://example.test/ref"},
    )

    head = harness.projects.get_video(video.id)
    assert result["applied_revision"] == head.revision
    assert head.settings.format.humor.value == "light"
    assert _all_calls(harness) == []


def test_4_1_reference_plan_effects_come_from_key_comparison(harness: Harness) -> None:
    video = harness.video
    scene_ids = video.scene_order[:2]
    ops = [
        SetOp(
            op="set",
            path=f"/scenes/{scene_id}/lines",
            value=[
                line.model_copy(update={"display_text": "참고 영상 글"}).model_dump(mode="json")
                for line in video.scenes[scene_id].lines
            ],
            origin=Origin.reference,
        )
        for scene_id in scene_ids
    ]
    computed = plan_change(
        video, ops, "reference", Target(scene_id=None, pointer=None), harness.services
    )
    empty = computed.effects.model_copy(
        update={"scene_ids_text": [], "scene_ids_tts": [], "scene_ids_render": [],
                "mix": False, "assemble": False}
    )
    understated = computed.model_copy(
        update={"effects": empty, "requires_confirmation": False, "confirmation_reasons": []}
    )
    harness.projects.put_change(understated)
    harness.reference.outcome = ReferenceOutcome(change_id=understated.id, reference=None)

    result, _ = _run(
        harness,
        JobKind.reference,
        video=video,
        input={"base_revision": video.revision, "url": "https://example.test/ref"},
    )

    assert result["change_id"] == understated.id
    assert result["status"] == "proposed"
    assert result["effects"]["scene_ids_render"] == scene_ids
    assert "multi_scene" in result["confirmation_reasons"]
    assert harness.projects.get_video(video.id).revision == video.revision


def test_4_1_reference_does_not_apply_a_plan_across_a_concept_gate(
    harness: Harness,
) -> None:
    video = harness.new_video(stage=VideoStage.draft, visuals=True)
    op = SetOp(
        op="set",
        path="/settings/visual/character/slots/hair",
        value="hair_short",
        origin=Origin.reference,
    )
    plan = plan_change(
        video, [op], "reference", Target(scene_id=None, pointer=None), harness.services
    )
    harness.projects.put_change(plan)
    advanced = harness.revise(video, stage=VideoStage.concept_confirmed)
    harness.reference.outcome = ReferenceOutcome(change_id=plan.id, reference=None)

    result, _ = _run(
        harness,
        JobKind.reference,
        video=advanced,
        input={"base_revision": advanced.revision, "url": "https://example.test/ref"},
    )

    head = harness.projects.get_video(video.id)
    assert result["status"] == "stale"
    assert head.revision == advanced.revision
    assert head.stage is VideoStage.concept_confirmed
    assert head.settings.visual.character.slots.hair is None


def test_4_1_precheck_gate_and_usage_are_exact(harness: Harness) -> None:
    draft = harness.new_video(stage=VideoStage.draft, visuals=False)
    job = harness.job(JobKind.precheck, video=draft, input={"base_revision": 1})
    ctx = harness.context(job)
    from app.services.pipeline.support import run_precheck

    with pytest.raises(AppError) as caught:
        run_precheck(job, ctx, harness.services)
    assert caught.value.code == "scenes_not_confirmed"
    assert harness.story.precheck_calls == []

    usage = Usage(
        stage=Stage.llm_precheck,
        provider="fixture",
        model="fixture",
        effort=Effort.low,
        input_tokens=3,
        output_tokens=5,
        cache_read_tokens=None,
        cost_usd=None,
        wall_ms=7,
        retries=0,
    )
    harness.story.usage = usage
    job = harness.job(JobKind.precheck, video=harness.video)
    ctx = harness.context(job)
    result = run_precheck(job, ctx, harness.services)
    assert harness.story.precheck_calls == [harness.video.id]
    assert ctx.usage == [usage]
    assert "usage" not in result
    assert result["precheck"]["opening_promise"] == "약속"


def test_4_1_bgm_code_and_upload_return_entries_without_rendering(
    harness: Harness,
) -> None:
    code_job = harness.job(
        JobKind.bgm_code,
        input={
            "project_id": harness.project.id,
            "mood": "curious",
            "instruction": "합성 BGM",
            "seed": 1,
        },
    )
    code_ctx = harness.context(code_job)
    from app.services.pipeline.changes import run_bgm_code, run_bgm_upload

    code_result = run_bgm_code(code_ctx.input, code_ctx, harness.services)
    assert code_result["bgm_id"] == "builtin_loop"
    assert harness.templates.bgm_calls == ["curious"]

    staged = harness.root / "upload.bin"
    staged.write_bytes(b"not decoded by the fake")
    upload_job = harness.job(
        JobKind.bgm_upload,
        input={"project_id": harness.project.id, "upload_path": str(staged)},
    )
    upload_ctx = harness.context(upload_job)
    upload_result = run_bgm_upload(upload_ctx.input, upload_ctx, harness.services)
    assert harness.sound.import_calls == [str(staged)]
    assert upload_result["bgm_id"].startswith("u_")
    assert _all_calls(harness) == []


def test_11_stale_context_helper_translates_revision_change(harness: Harness) -> None:
    video = harness.video
    harness.revise_scene(video.scene_order[0], display_text="바뀐 글")
    ctx = harness.context(harness.job(JobKind.generate, video=video))
    with pytest.raises(AppError) as caught:
        check_context(video, ctx, harness.services)
    assert caught.value.code == "stale_revision"


def test_26_partly_supported_chat_keeps_notes_on_the_plan(harness: Harness) -> None:
    video = harness.video
    harness.story.proposal_ops = [
        SetOp(op="set", path="/settings/format/humor", value="light", origin=Origin.llm)
    ]
    harness.story.proposal_notes = ["유머만 바꿈"]
    harness.story.proposal_unsupported = ["배경 음악 작곡"]
    result, _ = _run(
        harness,
        JobKind.chat,
        video=video,
        input={
            "base_revision": video.revision,
            "text": "유머를 넣고 음악도 새로 작곡해",
            "target": {"scene_id": None, "pointer": None},
        },
    )
    plan = harness.projects.get_change(result["change_id"])
    assert plan.notes == ["유머만 바꿈"]
    assert plan.unsupported == ["배경 음악 작곡"]


def test_27_warm_cache_then_failure_still_records_preserved_work(harness: Harness) -> None:
    _run(harness, JobKind.generate)
    changed = harness.change_bgm(harness.catalog.pin("bgm", "calm_happy_lullaby"))
    harness.sound.fail_mix = True
    job = harness.job(JobKind.generate, video=changed)
    ctx = harness.context(job)
    with pytest.raises(AppError):
        run(job, ctx, harness.services)
    assert ctx.checkpoints != []
    for checkpoint in ctx.checkpoints:
        assert _digest(harness, checkpoint.artifact_id) == checkpoint.digest


def test_16_preview_after_generate_reads_the_measured_timing(harness: Harness) -> None:
    preview_video = harness.new_video(stage=VideoStage.script_confirmed, visuals=True)
    estimated, _ = _run(harness, JobKind.preview, video=preview_video)
    confirmed = harness.revise(
        harness.projects.get_video(preview_video.id), stage=VideoStage.scenes_confirmed
    )
    _run(harness, JobKind.generate, video=confirmed)
    measured, _ = _run(harness, JobKind.preview, video=confirmed)
    scene_id = confirmed.scene_order[0]
    assert measured["artifacts"]["still"][scene_id] != estimated["artifacts"]["still"][scene_id]
    view = build_view(harness.projects.get_video(confirmed.id), harness.services)
    assert view.scenes[scene_id].still.artifact.id == measured["artifacts"]["still"][scene_id]
