"""Change previews and build views derived from the same artifact key graph."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.ports import AppError
from app.schemas.artifact import Artifact, ArtifactKind, Timing
from app.schemas.change import (
    ChangePlan,
    ChangeSource,
    ChangeStatus,
    ConfirmationReason,
    Effects,
    Op,
    PlanWarning,
    SetScriptOp,
    Target,
    WarningCode,
)
from app.schemas.common import ArtifactRef, Language, LocalizedText, Origin
from app.schemas.settings import LockKey
from app.schemas.video import ArtifactState, ArtifactStatus, SceneBuild, Video, VideoBuild
from app.services.pipeline.cache_keys import Graph
from app.services.pipeline.types import Services
from app.services.project import state


def _pointer(document: dict[str, Any], pointer: str) -> Any:
    value: Any = document
    for segment in pointer.strip("/").split("/"):
        if not isinstance(value, dict) or segment not in value:
            return None
        value = value[segment]
    return value


def _candidate(
    video: Video, ops: list[Op], source: ChangeSource, services: Services
) -> tuple[Video, list[LockKey], list[str]]:
    """Preview guarded edits with the confirmations applying this plan would give."""
    origin = state.SOURCE_ORIGIN[source]
    candidate = services.project.apply_ops(video, ops, origin)
    guarded = state.apply(video, ops, origin)
    if guarded.concept_changes:
        raise AppError("concept_locked")
    overwritten = list(guarded.overwrites_user_values)
    locks = list(guarded.locked_keys)
    if overwritten:
        # Origin protection runs before locks; reveal locks hidden by restoration.
        unlocked_origins = state.apply(
            video, ops, origin, state.Confirmed(overwrites=frozenset(overwritten))
        )
        locks = list(dict.fromkeys([*locks, *unlocked_origins.locked_keys]))
    if locks or overwritten:
        candidate = state.apply(
            video, ops, origin,
            state.Confirmed(locks=frozenset(locks), overwrites=frozenset(overwritten)),
        ).video
    before = video.model_dump(mode="json", by_alias=True)
    after = candidate.model_dump(mode="json", by_alias=True)
    for pointer, previous_origin in video.settings.origins.items():
        full = "/settings" + pointer
        if previous_origin is Origin.user and _pointer(before, full) != _pointer(after, full):
            if full not in overwritten:
                overwritten.append(full)
    for key in LockKey:
        if video.settings.locks.get(key) != candidate.settings.locks.get(key) and key not in locks:
            locks.append(key)
    return candidate, locks, overwritten


def stale_wording_in_neighbors(video: Video, changed: Video) -> list[PlanWarning]:
    """Warn on removed words still used next door; never rewrite a neighbor."""
    warnings: list[PlanWarning] = []
    for index, scene_id in enumerate(video.scene_order):
        old = video.scenes[scene_id]
        new = changed.scenes.get(scene_id)
        if new is None:
            continue
        old_text = " ".join(line.display_text for line in old.lines)
        new_text = " ".join(line.display_text for line in new.lines)
        removed = set(re.findall(r"\w{2,}", old_text)) - set(re.findall(r"\w{2,}", new_text))
        if not removed:
            continue
        for position in (index - 1, index + 1):
            if not 0 <= position < len(video.scene_order):
                continue
            neighbor_id = video.scene_order[position]
            neighbor = changed.scenes.get(neighbor_id)
            if neighbor is None or neighbor != video.scenes[neighbor_id]:
                continue
            neighbor_text = " ".join(line.display_text for line in neighbor.lines)
            words = set(re.findall(r"\w{2,}", neighbor_text))
            warning = PlanWarning(
                code=WarningCode.stale_wording_in_neighbor, scene_id=neighbor_id
            )
            if removed & words and warning not in warnings:
                warnings.append(warning)
    return warnings


def plan_change(
    video: Video,
    ops: list[Op],
    source: str,
    target: Target,
    services: Services,
) -> ChangePlan:
    source_kind = ChangeSource(source)
    changed, locks, overwritten = _candidate(video, ops, source_kind, services)
    before = Graph(video, services, symbolic=True)
    after = Graph(changed, services, symbolic=True)
    scene_ids = list(dict.fromkeys([*video.scene_order, *changed.scene_order]))
    text_ids = [
        scene_id for scene_id in scene_ids
        if before.text.get(scene_id) != after.text.get(scene_id)
    ]
    tts_ids: list[str] = []
    render_ids: list[str] = []
    for scene_id in scene_ids:
        old = before.scenes.get(scene_id)
        new = after.scenes.get(scene_id)
        if (None if old is None else old.tts) != (None if new is None else new.tts):
            tts_ids.append(scene_id)
        old_render = None if old is None else (old.parts, old.layer, old.still, old.clip)
        new_render = None if new is None else (new.parts, new.layer, new.still, new.clip)
        if old_render != new_render:
            render_ids.append(scene_id)
    script_rewrite = video.script is not None and any(isinstance(op, SetScriptOp) for op in ops)
    effects = Effects(
        script=video.script != changed.script or script_rewrite,
        scene_ids_text=text_ids,
        scene_ids_tts=tts_ids,
        scene_ids_render=render_ids,
        mix=before.mix != after.mix,
        assemble=before.final != after.final,
        locked_keys=locks,
        overwrites_user_values=overwritten,
    )
    reasons: list[ConfirmationReason] = []
    if script_rewrite:
        reasons.append(ConfirmationReason.script_rewrite)
    if len(set(text_ids) | set(tts_ids) | set(render_ids)) > 1:
        reasons.append(ConfirmationReason.multi_scene)
    if locks:
        reasons.append(ConfirmationReason.lock_change)
    if overwritten:
        reasons.append(ConfirmationReason.user_value_overwrite)
    if tts_ids:
        reasons.append(ConfirmationReason.rebuild_tts)
    if render_ids or source_kind is ChangeSource.style:
        reasons.append(ConfirmationReason.rebuild_render)
    return ChangePlan(
        schema_version=1,
        id=services.project.projects.new_id("c"),
        video_id=video.id,
        base_revision=video.revision,
        created_at=datetime.now(UTC),
        source=source_kind,
        target=target,
        ops=ops,
        effects=effects,
        requires_confirmation=bool(reasons),
        confirmation_reasons=reasons,
        warnings=stale_wording_in_neighbors(video, changed),
        unsupported=[],
        notes=[],
        status=ChangeStatus.proposed,
        applied_revision=None,
    )


def artifact_ref(artifact: Artifact) -> ArtifactRef:
    return ArtifactRef(
        id=artifact.id, digest=artifact.digest, cache_key=artifact.cache_key
    )


def _status(
    video: Video,
    services: Services,
    kind: ArtifactKind,
    key: str | None,
    scene_id: str | None = None,
    line_id: str | None = None,
) -> ArtifactStatus:
    artifact = None if key is None else services.artifact_store.find(key)
    if artifact is not None:
        return ArtifactStatus(
            state=ArtifactState.fresh,
            cache_key=key,
            artifact=artifact_ref(artifact),
            error_code=None,
        )
    record = services.build_states.get((video.id, video.revision, kind.value, scene_id, line_id))
    if key is not None and record is not None and record["cache_key"] == key:
        return ArtifactStatus(
            state=ArtifactState(record["state"]),
            cache_key=key,
            artifact=None,
            error_code=record.get("error_code"),
        )
    previous = services.previous_keys.get((video.id, kind.value, scene_id, line_id))
    stale = None if previous is None or previous == key else services.artifact_store.find(previous)
    return ArtifactStatus(
        state=ArtifactState.stale if stale is not None else ArtifactState.missing,
        cache_key=key,
        artifact=None if stale is None else artifact_ref(stale),
        error_code=None,
    )


def _attributions(video: Video, services: Services) -> list[LocalizedText]:
    refs = []
    bgm = video.settings.audio.bgm
    if bgm.enabled and bgm.entry is not None:
        refs.append(("bgm", bgm.entry))
    if video.settings.audio.sfx_enabled:
        for scene in video.scenes.values():
            if scene.visual is not None:
                refs.extend(("sfx", cue.sfx_id) for cue in scene.visual.sfx)
    entries = [
        services.catalog_port.get(kind, ref.id, ref.revision)
        for kind, ref in refs
    ]
    korean = services.assemble.attributions(entries, Language.ko)
    english = services.assemble.attributions(entries, Language.en)
    return [
        LocalizedText(ko=ko, en=en)
        for ko, en in zip(korean, english, strict=True)
    ]


def build_view(video: Video, services: Services) -> VideoBuild:
    graph = Graph(video, services)
    scenes = {}
    actual_ms = 0
    complete_timing = bool(video.scene_order)
    for scene_id, keys in graph.scenes.items():
        timing = _status(video, services, ArtifactKind.timing_json, keys.timing, scene_id)
        scenes[scene_id] = SceneBuild(
            still=_status(video, services, ArtifactKind.still_png, keys.still, scene_id),
            tts={
                line_id: _status(video, services, ArtifactKind.tts_wav, key, scene_id, line_id)
                for line_id, key in keys.tts.items()
            },
            timing=timing,
            layer=None if keys.layer is None else _status(
                video, services, ArtifactKind.layer_png, keys.layer, scene_id
            ),
            clip=_status(video, services, ArtifactKind.clip_mp4, keys.clip, scene_id),
        )
        if timing.state is ArtifactState.fresh and timing.artifact is not None:
            document = Timing.model_validate_json(
                services.artifact_store.path(timing.artifact.id).read_bytes()
            )
            actual_ms += document.duration_ms
        else:
            complete_timing = False
    final = _status(video, services, ArtifactKind.final_mp4, graph.final)
    if final.artifact is not None and final.state is ArtifactState.fresh:
        artifact = services.artifact_store.find(graph.final)
        if artifact is not None and "duration_ms" in artifact.media:
            actual_ms = artifact.media["duration_ms"]
    return VideoBuild(
        video_id=video.id,
        revision=video.revision,
        scenes=scenes,
        mix=_status(video, services, ArtifactKind.mix_wav, graph.mix),
        final=final,
        srt=_status(video, services, ArtifactKind.srt, graph.srt),
        estimated_ms=sum(
            services.voice.estimate_ms(line, video.settings.language.value)
            for scene in video.scenes.values() for line in scene.lines
        ),
        actual_ms=actual_ms if complete_timing else None,
        attribution=_attributions(video, services),
    )


__all__ = ["artifact_ref", "build_view", "plan_change", "stale_wording_in_neighbors"]
