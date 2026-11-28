"""LLM result jobs: one plan per result, applied only when §4.1 allows it.

Every route returns ops. The plan compares cache keys before and after, so the
effects lists come from the graph rather than a hand-written scene list. A plan
that needs confirmation stays proposed and no render, voice or assembly work is
started from this module.
"""

from __future__ import annotations

from typing import Any

from app.caption_layout import draws_bubble
from app.ports import AppError, JobContext, Proposal, StyleFrames
from app.schemas.api import (
    BgmCodeRequest,
    DraftRequest,
    MessageRequest,
    StyleRequest,
    TemplateRequest,
)
from app.schemas.change import (
    AddSceneOp,
    ChangePlan,
    ChangeStatus,
    Op,
    RemoveSceneOp,
    ReorderOp,
    ReplaceSceneOp,
    SetOp,
    SetScriptOp,
    Target,
)
from app.schemas.common import Language, Mood, Origin
from app.schemas.job import Job
from app.schemas.template_manifest import TemplateManifest
from app.schemas.video import CreatedBy, ReferenceSummary, Video
from app.services.pipeline.dependencies import plan_change
from app.services.pipeline.run_state import check_alive
from app.services.pipeline.types import Services
from app.services.project import revision, state

SCENE_PREFIX = "/scenes/"
CAPTION_STYLE_PATH = "/settings/caption/style"
CAPTION_PLACE_PATH = "/settings/caption/place"


def run_change_job(job: Job, ctx: JobContext, services: Services) -> dict[str, object]:
    video = load_change_video(job, services)
    body = ctx.input
    if job.kind.value == "draft":
        return _draft(video, DraftRequest.model_validate(body), ctx, services)
    if job.kind.value == "script":
        return _script(video, ctx, services)
    if job.kind.value == "chat":
        return _chat(video, MessageRequest.model_validate(body), ctx, services)
    if job.kind.value == "style":
        return _style(video, StyleRequest.model_validate(body), ctx, services)
    if job.kind.value == "template":
        return _template(video, TemplateRequest.model_validate(body), ctx, services)
    raise AppError("not_implemented", detail={"kind": job.kind.value})


def run_reference_job(
    job: Job, ctx: JobContext, services: Services
) -> dict[str, object]:
    video = load_change_video(job, services)
    # A cancelled or failed attempt can leave frames no revision points to.
    services.reference.prune_frames(services.project.view(video.id))
    body = ctx.input
    url = body.get("url")
    if url is not None:
        source = services.reference.ingest(None, str(url), ctx=ctx)
    else:
        source = services.reference.ingest(_upload_path(ctx), None, ctx=ctx)
    check_alive(ctx)
    outcome = services.reference.analyze(source, video, ctx=ctx)
    check_alive(ctx)
    report = outcome.reference
    summary = None if report is None else getattr(report, "summary", None)
    if outcome.change_id is None:
        _store_reference(video, summary, services)
        return {
            "change_id": None,
            "artifact_ids": [],
            "rebuilt_scene_ids": [],
            "stages": [],
            "status": None,
            "applied_revision": None,
            "reference": _plain(report),
        }
    stored = services.project.projects.get_change(outcome.change_id)
    if stored.video_id != video.id:
        raise AppError("not_found", detail={"change_id": stored.id})
    result = _settle_reference_plan(video, stored, summary, services)
    result["reference"] = _plain(report)
    return result


def _settle_reference_plan(
    video: Video, stored: ChangePlan, summary: Any, services: Services
) -> dict[str, object]:
    """Settle the analysis plan and keep its summary on the analyzed base.

    Saving the summary writes the revision after that base, so a plan that still
    applies moves onto it. A head that changed on its own is never merged with:
    the summary is not written and the plan is left to become stale.
    """
    if stored.status is not ChangeStatus.proposed or stored.base_revision != video.revision:
        saved = _store_reference(video, summary, services)
        return settle_plan(stored, video if saved is None else saved, services)
    # The analysis stores only its ops; effects and confirmation come from keys.
    planned = plan_change(video, list(stored.ops), stored.source.value, stored.target, services)
    plan = planned.model_copy(
        update={
            "id": stored.id,
            "base_revision": stored.base_revision,
            "created_at": stored.created_at,
            "notes": stored.notes,
            "unsupported": stored.unsupported,
        }
    )
    saved = _store_reference(video, summary, services)
    if saved is not None:
        plan = plan.model_copy(update={"base_revision": saved.revision})
    services.project.projects.put_change(plan)
    return settle_plan(plan, video if saved is None else saved, services)


def _store_reference(
    video: Video, summary: ReferenceSummary | None, services: Services
) -> Video | None:
    """Append the summary only while the analyzed revision is still the head.

    ``append_revision`` checks that the new revision is head + 1, so a writer
    that advances the head between the read and the write wins: the conflict is
    swallowed and this stale job output is not stored. Every path prunes the
    frames to the reference the resulting head points to, so an attempt that is
    not stored and a replaced reference leave no folder behind.
    """
    if summary is None:
        return None
    head = services.project.view(video.id)
    if head.revision != video.revision:
        services.reference.prune_frames(head)
        return None
    try:
        saved = services.project.projects.append_revision(
            revision.next_revision(
                video.model_copy(update={"reference": summary}),
                head,
                CreatedBy.system,
            )
        )
    except AppError as error:
        if error.code != "revision_conflict":
            raise
        services.reference.prune_frames(services.project.view(video.id))
        return None
    services.reference.prune_frames(saved)
    return saved


def run_bgm_code(body: dict[str, Any], ctx: JobContext, services: Services) -> dict[str, object]:
    request = BgmCodeRequest.model_validate(body)
    ref = services.templates.generate_bgm(request, ctx=ctx)
    return {"bgm_id": ref.id, "revision": ref.revision, "ref": ref.model_dump(mode="json")}


def run_bgm_upload(body: dict[str, Any], ctx: JobContext, services: Services) -> dict[str, object]:
    project_id = body.get("project_id")
    if not isinstance(project_id, str):
        raise AppError("validation_failed", detail={"field": "project_id"})
    try:
        mood = Mood(body.get("mood", Mood.calm.value))
    except ValueError:
        raise AppError("validation_failed", detail={"field": "mood"}) from None
    entry = services.sound.import_upload(
        _bgm_upload_path(ctx), project_id, ctx=ctx, mood=mood
    )
    ref = services.sound.register_upload(entry, ctx=ctx)
    return {
        "bgm_id": entry.id,
        "upload_id": entry.upload_id,
        "revision": ref.revision,
        "ref": ref.model_dump(mode="json"),
        "entry": entry.model_dump(mode="json"),
    }


def load_change_video(job: Job, services: Services) -> Video:
    """The revision the change was requested against; a newer head is not merged."""
    if job.video_id is None:
        raise AppError("validation_failed", detail={"field": "video_id"})
    if job.base_revision is None:
        return services.project.view(job.video_id)
    try:
        return services.project.projects.get_video(job.video_id, job.base_revision)
    except AppError as error:
        if error.code != "not_found":
            raise
        head = services.project.view(job.video_id)
        raise AppError(
            "stale_revision", detail={"current_revision": head.revision}
        ) from error


def _draft(
    video: Video, request: DraftRequest, ctx: JobContext, services: Services
) -> dict[str, object]:
    ops = _keep_protected(
        video, services.story.draft(video, request.message, request.card_id, ctx=ctx)
    )
    return _plan_result(
        video,
        ops,
        "direct",
        Target(scene_id=None, pointer=None),
        ctx,
        services,
        auto=True,
        override_confirmation=True,
        mark_stale=False,
    )


def _keep_protected(video: Video, ops: list[Op]) -> list[Op]:
    """Drop the settings ops a draft may not apply, so the rest still applies.

    A draft value ranks below a user, reference or preset value and below a lock
    (user > reference > preset > card > llm), so the stored value stays. One such
    op must not turn the whole draft into a plan that waits for a confirmation
    the draft never asks for.
    """
    kept: list[Op] = []
    for op in ops:
        if isinstance(op, SetOp) and op.path.startswith(state.SETTINGS + "/"):
            guarded = state.apply(video, [op], Origin.user)
            if guarded.overwrites_user_values or guarded.locked_keys:
                continue
        kept.append(op)
    return kept


def _script(video: Video, ctx: JobContext, services: Services) -> dict[str, object]:
    ops = services.story.write_script(video, ctx=ctx)
    return _plan_result(
        video,
        ops,
        "direct",
        Target(scene_id=None, pointer=None),
        ctx,
        services,
        auto=video.script is None,
        override_confirmation=video.script is None,
    )


def _chat(
    video: Video, request: MessageRequest, ctx: JobContext, services: Services
) -> dict[str, object]:
    scene_target = request.target.scene_id
    if scene_target is not None:
        # A scene target keeps the whole request in that scene: lines, sound and
        # beat changes stay, and anything else comes back in unsupported.
        if scene_target not in video.scenes:
            raise AppError("validation_failed", detail={"scene_id": scene_target})
        proposal = services.story.rewrite_scene(
            video, scene_target, request.text, ctx=ctx
        )
        ops = list(proposal.ops)
        _only_scene(ops, scene_target)
        source = "scene_rewrite"
        target = request.target
    else:
        caption_pointer = request.target.pointer in (CAPTION_STYLE_PATH, CAPTION_PLACE_PATH)
        if caption_pointer and request.text.strip():
            proposal = _caption_edit(video, request, ctx, services)
        else:
            proposal = services.story.interpret(video, request.text, request.target, ctx=ctx)
        ops = proposal.ops
        source = "chat"
        target = request.target
    notes = list(proposal.notes)
    unsupported = list(proposal.unsupported)
    if not ops:
        return {
            "change_id": None,
            "artifact_ids": [],
            "rebuilt_scene_ids": [],
            "stages": [],
            "status": None,
            "applied_revision": None,
            "notes": notes,
            "unsupported": unsupported,
        }
    return _plan_result(
        video, ops, source, target, ctx, services, auto=True, override_confirmation=False,
        notes=notes, unsupported=unsupported,
    )


def _caption_stage_notes(video: Video, services: Services) -> list[str]:
    layout = video.settings.format.layout
    template = services.catalog_port.get("template", layout.id, layout.revision)
    if not isinstance(template, TemplateManifest):
        return []
    korean = video.settings.language is Language.ko
    if draws_bubble(template):
        return [
            "이 무대는 말풍선을 씁니다." if korean else "This stage uses its own speech bubble."
        ]
    if template.renderer.kind != "builtin":
        return ["이 무대는 상자가 고정입니다." if korean else "This stage has a fixed caption box."]
    return []


def _caption_edit(
    video: Video, request: MessageRequest, ctx: JobContext, services: Services
) -> Proposal:
    pointer = request.target.pointer
    notes = _caption_stage_notes(video, services)
    if pointer == CAPTION_STYLE_PATH:
        result = services.templates.generate_caption_box(request.text, video, ctx=ctx)
    else:
        assert pointer == CAPTION_PLACE_PATH
        result, moved = services.templates.edit_caption_place(request.text, video, ctx=ctx)
        if moved:
            notes.append(state.PLACE_CLAMPED[video.settings.language])
    return Proposal(
        ops=[
            SetOp(
                op="set", path=pointer, value=result.model_dump(mode="json"), origin=Origin.user
            )
        ],
        notes=notes,
    )


def _style(
    video: Video, request: StyleRequest, ctx: JobContext, services: Services
) -> dict[str, object]:
    hints = _style_hints(video, request.use_reference, services)
    ref = services.templates.generate_style(request, video, hints, ctx=ctx)
    op = SetOp(
        op="set",
        path="/settings/visual/art_style",
        value=ref.model_dump(mode="json"),
        origin=Origin.llm,
    )
    ops = [op]
    notes: list[str] = []
    look = video.reference.style if request.use_reference and video.reference is not None else None
    if look is not None and look.caption_box is not None:
        caption_ref = services.templates.generate_caption_box(
            request.instruction, video, reference_box=look.caption_box, art_style=ref, ctx=ctx
        )
        ops.append(SetOp(
            op="set",
            path=CAPTION_STYLE_PATH,
            value=caption_ref.model_dump(mode="json"),
            origin=Origin.llm,
        ))
        notes = _caption_stage_notes(video, services)
    result = _plan_result(
        video,
        ops,
        "style",
        Target(scene_id=None, pointer="/settings/visual/art_style"),
        ctx,
        services,
        auto=True,
        override_confirmation=False,
        notes=notes,
    )
    result["package"] = ref.model_dump(mode="json")
    return result


def _template(
    video: Video, request: TemplateRequest, ctx: JobContext, services: Services
) -> dict[str, object]:
    ref = services.templates.generate_template(request, video, ctx=ctx)
    op = SetOp(
        op="set",
        path="/settings/format/layout",
        value=ref.model_dump(mode="json"),
        origin=Origin.llm,
    )
    result = _plan_result(
        video,
        [op],
        "template",
        Target(scene_id=None, pointer="/settings/format/layout"),
        ctx,
        services,
        auto=True,
        override_confirmation=False,
    )
    result["package"] = ref.model_dump(mode="json")
    return result


def _plan_result(
    video: Video,
    ops: list[Op],
    source: str,
    target: Target,
    ctx: JobContext,
    services: Services,
    *,
    auto: bool,
    override_confirmation: bool,
    mark_stale: bool = True,
    notes: list[str] | None = None,
    unsupported: list[str] | None = None,
) -> dict[str, object]:
    if not ops:
        return {
            "change_id": None,
            "artifact_ids": [],
            "rebuilt_scene_ids": [],
            "stages": [],
            "status": None,
            "applied_revision": None,
        }
    check_alive(ctx)
    plan = plan_change(video, ops, source, target, services)
    if notes or unsupported:
        # Keep geometry validation notes when a route adds its own explanation.
        plan = ChangePlan.model_validate({
            **plan.model_dump(),
            "notes": list(dict.fromkeys([*plan.notes, *(notes or [])]))[:5],
            "unsupported": unsupported or [],
        })
    services.project.projects.put_change(plan)
    # The draft and first-script requests are the user's own start of those
    # steps, so their plans apply even when the graph sees new scenes. They never
    # confirm a lock change or the overwrite of a user value on the user's behalf.
    protected = bool(plan.effects.locked_keys or plan.effects.overwrites_user_values)
    allowed = auto and (
        not plan.requires_confirmation or (override_confirmation and not protected)
    )
    return settle_plan(
        plan, video, services, apply=allowed, mark_stale=mark_stale
    )


def settle_plan(
    plan: ChangePlan,
    video: Video,
    services: Services,
    *,
    apply: bool | None = None,
    mark_stale: bool = True,
) -> dict[str, object]:
    """Apply a proposed plan only while its base is still the head; always report it.

    ``apply`` overrides the confirmation test for the routes whose request is
    itself the user's start of the step. A plan whose base is older than the
    head is stale and is never applied.
    """
    if plan.status.value == "applied":
        return plan_result(plan)
    if plan.status.value != "proposed":
        return plan_result(plan)
    head = services.project.view(video.id)
    if plan.base_revision != head.revision:
        if mark_stale:
            plan = plan.model_copy(update={"status": ChangeStatus.stale})
            services.project.projects.put_change(plan)
        return plan_result(plan)
    wait = plan.requires_confirmation if apply is None else not apply
    if wait:
        return plan_result(plan)
    try:
        applied = services.project.commit(plan, plan.base_revision)
    except AppError as error:
        if error.code in ("change_stale", "revision_conflict"):
            raise AppError("stale_revision", detail=dict(error.detail)) from error
        raise
    stored = services.project.projects.get_change(plan.id)
    result = plan_result(stored)
    result["revision"] = applied.revision
    return result


def plan_result(plan: ChangePlan) -> dict[str, object]:
    applied = plan.status.value == "applied"
    return {
        "change_id": plan.id,
        "artifact_ids": [],
        "rebuilt_scene_ids": [],
        "stages": [],
        "status": plan.status.value,
        "requires_confirmation": plan.requires_confirmation,
        "confirmation_reasons": [reason.value for reason in plan.confirmation_reasons],
        "warnings": [
            {"code": warning.code.value, "scene_id": warning.scene_id}
            for warning in plan.warnings
        ],
        "effects": plan.effects.model_dump(mode="json"),
        "notes": list(plan.notes),
        "unsupported": list(plan.unsupported),
        "applied_revision": plan.applied_revision if applied else None,
        "revision": plan.applied_revision if applied else None,
    }


def _only_scene(ops: list[Op], scene_id: str) -> None:
    """A rewrite result may only touch its target scene; nothing else is accepted."""
    for op in ops:
        if isinstance(op, SetOp):
            if not op.path.startswith(f"{SCENE_PREFIX}{scene_id}/"):
                raise AppError(
                    "invalid_op", detail={"op": "set", "path": op.path, "scene_id": scene_id}
                )
        elif isinstance(op, ReplaceSceneOp):
            if op.scene.id != scene_id:
                raise AppError(
                    "invalid_op", detail={"op": "replace_scene", "scene_id": op.scene.id}
                )
        elif isinstance(op, (AddSceneOp, RemoveSceneOp, ReorderOp, SetScriptOp)):
            raise AppError("invalid_op", detail={"op": op.op, "scene_id": scene_id})


def _style_hints(
    video: Video, use_reference: bool, services: Services
) -> StyleFrames | None:
    """The kept palette and frames of the reference, when the request asks for them.

    A reference that records frames but no longer has all of them would make a
    style that does not copy the look while looking successful, so the request
    fails instead. An older reference can lose its folder to a later analysis.
    """
    if not use_reference or video.reference is None or video.reference.style is None:
        return None
    look = video.reference.style
    frames = services.reference.kept_frames(video)
    if len(frames) != len(look.frames):
        raise AppError(
            "internal",
            detail={
                "reason": "reference_frames_missing",
                "kept": len(frames),
                "expected": len(look.frames),
            },
        )
    return StyleFrames(palette=list(look.palette), frames=frames)


def _upload_path(ctx: JobContext) -> Any:
    value = ctx.input.get("upload_path")
    if not isinstance(value, str) or not value:
        raise AppError("validation_failed", detail={"field": "upload_path"})
    from pathlib import Path

    path = Path(value)
    if not path.is_file():
        raise AppError("validation_failed", detail={"field": "upload_path"})
    return path


def _bgm_upload_path(ctx: JobContext) -> Any:
    value = ctx.input.get("staging_path", ctx.input.get("upload_path"))
    if not isinstance(value, str) or not value:
        raise AppError("validation_failed", detail={"field": "staging_path"})
    from pathlib import Path

    path = Path(value)
    if not path.is_file():
        raise AppError("validation_failed", detail={"field": "staging_path"})
    return path


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


__all__ = [
    "load_change_video",
    "plan_result",
    "run_bgm_code",
    "run_bgm_upload",
    "run_change_job",
    "run_reference_job",
    "settle_plan",
]
