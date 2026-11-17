"""Preview and generation steps over the shared cache-key graph.

The graph is rebuilt after a publication only when a dependent key is needed
next. A fully cached repeat therefore does no media work and one graph pass,
while a changed scene rebuilds only the artifacts whose keys moved.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import ValidationError

from app.ports import AppError, JobContext
from app.schemas.artifact import Artifact, ArtifactKind, Timing
from app.schemas.change import ChangePlan, Op, SetOp, Target
from app.schemas.common import ArtifactRef, Origin
from app.schemas.job import Job, Stage
from app.schemas.scene import SceneVisual
from app.schemas.video import STAGE_ORDER, Video, VideoStage
from app.schemas.voice_manifest import VoiceManifest
from app.services.pipeline.cache_keys import (
    CLIP_FPS,
    LAYER_CANVAS,
    MIX_SAMPLE_RATE,
    PART_SEED,
    STILL_PREVIEW,
    Graph,
)
from app.services.pipeline.dependencies import plan_change
from app.services.pipeline.run_state import RunState, StageLog, check_context
from app.services.pipeline.types import Services
from app.services.project import state as project_state

STILL_SIZE = STILL_PREVIEW
CLIP_MEDIA = {"width": LAYER_CANVAS[0], "height": LAYER_CANVAS[1], "fps": CLIP_FPS}
MIX_MEDIA = {"sample_rate": MIX_SAMPLE_RATE, "channels": 1}
SKIN = "skin"
BUILTIN_PART_NAMES = frozenset(
    {"body", "pose", "outfit", "face", "expression", "hair", "hat", "prop", SKIN}
)


def run_preview(job: Job, ctx: JobContext, services: Services) -> dict[str, object]:
    video = load_video(job, services)
    require_stage(video, VideoStage.script_confirmed, "script_not_confirmed")
    requested = ctx.input.get("scene_ids")
    targets = target_scene_ids(video, requested)
    change_id = ctx.input.get("change_id")
    plan = None
    if change_id is not None:
        video = planned_video(video, str(change_id), services)
        targets = target_scene_ids(video, requested)
    else:
        video, plan = prepare_scene_data(video, targets, ctx, services)
    for scene_id in targets:
        if video.scenes[scene_id].visual is None:
            raise AppError("scene_data_missing", detail={"scene_id": scene_id})
    run = RunState(job, ctx, services, video)
    _preview(run, targets)
    if plan is not None:
        run.guard()
        applied = _commit_plan(plan, run.video.revision, services)
        run.rebase(applied)
    return run.result()


def run_generate(job: Job, ctx: JobContext, services: Services) -> dict[str, object]:
    video = load_video(job, services)
    require_stage(video, VideoStage.scenes_confirmed, "scenes_not_confirmed")
    if not video.scene_order:
        raise AppError("scene_data_missing", detail={"reason": "no_scenes"})
    for scene_id in video.scene_order:
        if video.scenes[scene_id].visual is None:
            raise AppError("scene_data_missing", detail={"scene_id": scene_id})
    run = RunState(job, ctx, services, video)
    _generate(run)
    return run.result()


def load_video(job: Job, services: Services) -> Video:
    if job.video_id is None:
        raise AppError("validation_failed", detail={"field": "video_id"})
    video = services.project.view(job.video_id)
    if job.base_revision is not None and video.revision != job.base_revision:
        raise AppError("stale_revision", detail={"current_revision": video.revision})
    return video


def require_stage(video: Video, stage: VideoStage, code: str) -> None:
    if STAGE_ORDER.index(video.stage) < STAGE_ORDER.index(stage):
        raise AppError(code, detail={"stage": video.stage.value, "required": stage.value})


def target_scene_ids(video: Video, requested: object) -> list[str]:
    if requested is None:
        return list(video.scene_order)
    if not isinstance(requested, list) or not all(
        isinstance(item, str) for item in requested
    ):
        raise AppError("validation_failed", detail={"field": "scene_ids"})
    unknown = [scene_id for scene_id in requested if scene_id not in video.scenes]
    if unknown:
        raise AppError("validation_failed", detail={"unknown_scene_ids": unknown})
    wanted = set(requested)
    return [scene_id for scene_id in video.scene_order if scene_id in wanted]


def prepare_scene_data(
    video: Video, scene_ids: list[str], ctx: JobContext, services: Services
) -> tuple[Video, ChangePlan | None]:
    """Prepare missing scene visuals for a preview without persisting yet.

    The preview request authorizes drawing the missing scenes, not any other
    edit, so only the exact ``/visual`` ops of those scenes are accepted. A
    protected value that would need the user's own confirmation stops the
    preview. The plan is committed only after every preview artifact succeeded,
    so a failed attempt leaves the head and its retry input unchanged.
    """
    missing = [scene_id for scene_id in scene_ids if video.scenes[scene_id].visual is None]
    if not missing:
        return video, None
    check_context(video, ctx, services)
    ops = services.story.scene_data(video, missing, ctx=ctx)
    check_context(video, ctx, services)
    if not ops:
        raise AppError("scene_data_missing", detail={"scene_ids": missing})
    ops = _scene_data_ops(ops, missing)
    plan = plan_change(
        video, ops, "direct", Target(scene_id=None, pointer=None), services
    )
    if plan.effects.locked_keys or plan.effects.overwrites_user_values:
        raise AppError(
            "invalid_combination",
            detail={
                "reason": "protected_values",
                "locked_keys": [key.value for key in plan.effects.locked_keys],
                "overwrites_user_values": plan.effects.overwrites_user_values[:4],
            },
        )
    applied = project_state.apply(video, ops, Origin.user)
    if applied.concept_changes:
        raise AppError("concept_locked", detail={"pointer": applied.concept_changes[0]})
    for scene_id in missing:
        if applied.video.scenes[scene_id].visual is None:
            raise AppError("scene_data_missing", detail={"scene_id": scene_id})
    if project_state.new_issues(video, applied.video, services.catalog_port):
        raise AppError("invalid_combination", detail={"reason": "scene_data"})
    check_context(video, ctx, services)
    return applied.video, plan


def _commit_plan(plan: ChangePlan, base_revision: int, services: Services) -> Video:
    try:
        return services.project.commit(plan, base_revision)
    except AppError as error:
        if error.code in ("change_stale", "revision_conflict"):
            raise AppError("stale_revision", detail=dict(error.detail)) from error
        raise


def _scene_data_ops(ops: list[Op], missing: list[str]) -> list[Op]:
    """Keep only one visual write per missing scene; reject every other edit."""
    allowed = set(missing)
    seen: set[str] = set()
    checked: list[Op] = []
    for op in ops:
        if not isinstance(op, SetOp):
            raise AppError("invalid_op", detail={"op": getattr(op, "op", "unknown")})
        parts = op.path.split("/")
        if len(parts) != 4 or parts[1] != "scenes" or parts[3] != "visual":
            raise AppError("invalid_op", detail={"path": op.path})
        scene_id = parts[2]
        if scene_id not in allowed:
            raise AppError("invalid_op", detail={"scene_id": scene_id})
        if scene_id in seen:
            raise AppError("invalid_op", detail={"scene_id": scene_id, "reason": "duplicate"})
        try:
            SceneVisual.model_validate(op.value)
        except ValidationError as error:
            raise AppError(
                "invalid_op", detail={"scene_id": scene_id, "reason": "visual"}
            ) from error
        seen.add(scene_id)
        checked.append(op)
    if seen != allowed:
        raise AppError(
            "scene_data_missing", detail={"scene_ids": sorted(allowed - seen)}
        )
    return checked


def planned_video(video: Video, change_id: str, services: Services) -> Video:
    plan = services.project.projects.get_change(change_id)
    if plan.video_id != video.id:
        raise AppError("not_found")
    if plan.status.value != "proposed" or plan.base_revision != video.revision:
        raise AppError("change_stale")
    applied = project_state.apply(
        video,
        plan.ops,
        project_state.SOURCE_ORIGIN[plan.source],
        project_state.confirmed_by(plan),
    )
    if applied.concept_changes:
        raise AppError("concept_locked")
    return applied.video


def _preview(run: RunState, scene_ids: list[str]) -> None:
    build = _Builder(run)
    build.refresh()
    with run.stage(Stage.layer) as log:
        for scene_id in scene_ids:
            build.ensure_parts(scene_id, log)
    build.refresh_if_dirty()
    with run.stage(Stage.layer) as log:
        for scene_id in scene_ids:
            build.ensure_layer(scene_id, log)
    build.refresh_if_dirty()
    with run.stage(Stage.still) as log:
        for scene_id in scene_ids:
            build.ensure_still(scene_id, build.published_timing(scene_id), log)


def _generate(run: RunState) -> None:
    video = run.video
    build = _Builder(run)
    build.refresh()
    scene_ids = list(video.scene_order)
    with run.stage(Stage.tts) as log:
        for scene_id in scene_ids:
            build.ensure_tts(scene_id, log)
    build.refresh_if_dirty()
    with run.stage(Stage.align) as log:
        for scene_id in scene_ids:
            build.ensure_timing(scene_id, log)
    with run.stage(Stage.layer) as log:
        for scene_id in scene_ids:
            build.ensure_parts(scene_id, log)
    build.refresh_if_dirty()
    with run.stage(Stage.layer) as log:
        for scene_id in scene_ids:
            build.ensure_layer(scene_id, log)
    build.refresh_if_dirty()
    with run.stage(Stage.still) as log:
        for scene_id in scene_ids:
            build.ensure_still(scene_id, build.timing(scene_id), log)
    # A still artifact is not an input to a clip, mix, final or srt key.
    build.dirty = False
    with run.stage(Stage.clip) as log:
        for scene_id in scene_ids:
            build.ensure_clip(scene_id, log)
    with run.stage(Stage.mix) as log:
        build.ensure_mix(log)
    build.refresh_if_dirty()
    with run.stage(Stage.assemble) as log:
        build.ensure_final(log)
    with run.stage(Stage.srt) as log:
        build.ensure_srt(log)


class _Builder:
    def __init__(self, run: RunState) -> None:
        self.run = run
        self.services = run.services
        self.video = run.video
        self.graph = Graph(self.video, self.services)
        self.dirty = False
        self._parts_artifacts: dict[str, dict[str, Artifact]] = {}
        self._parts_bytes: dict[str, dict[str, bytes]] = {}
        self._timings: dict[str, Timing] = {}
        self._tts: dict[str, dict[str, Artifact]] = {}
        self._layers: dict[str, Artifact] = {}
        self._stills: dict[str, Artifact] = {}
        self._clips: dict[str, Artifact] = {}
        self._parts_builder: Any = None
        self._layer_drawer: Any = None
        self._voice_manifest: VoiceManifest | None = None
        self._mix: Artifact | None = None
        self._final: Artifact | None = None
        self._srt: Artifact | None = None

    def refresh(self) -> None:
        self.graph = Graph(self.video, self.services)
        self.dirty = False

    def refresh_if_dirty(self) -> None:
        if self.dirty:
            self.refresh()

    def keys(self, scene_id: str) -> Any:
        try:
            return self.graph.scenes[scene_id]
        except KeyError:
            raise AppError("scene_not_found", detail={"scene_id": scene_id}) from None

    def timing(self, scene_id: str) -> Timing:
        return self._timings[scene_id]

    def published_timing(self, scene_id: str) -> Timing | None:
        """The scene's measured timing when an earlier generate published it."""
        if scene_id not in self._timings:
            artifact = self.run.store.find(self.run.job.owner_id, self.keys(scene_id).timing)
            if artifact is None:
                return None
            self._timings[scene_id] = _load_timing(self.run, artifact, scene_id)
        return self._timings[scene_id]

    # --- parts and layer ---------------------------------------------------------

    def ensure_parts(self, scene_id: str, log: StageLog) -> None:
        keys = self.keys(scene_id).parts
        artifacts: dict[str, Artifact] = {}
        missing: list[str] = []
        for slot, cache_key in keys.items():
            artifact = self.run.find(
                cache_key, stage=log, scene_id=scene_id, slot=slot
            )
            if artifact is None:
                missing.append(slot)
            else:
                artifacts[slot] = artifact
        if not missing:
            self._parts_artifacts[scene_id] = artifacts
            return
        with self.run.building_many(
            [
                (ArtifactKind.part_png, keys[slot], scene_id, None)
                for slot in missing
            ]
        ):
            built = self._build_parts(scene_id, set(missing))
            extras = sorted(set(built) - set(keys))
            if extras:
                raise AppError(
                    "render_input_invalid",
                    detail={"input": extras[0], "scene_id": scene_id, "reason": "unkeyed"},
                )
            for slot in missing:
                if slot not in built:
                    raise AppError(
                        "render_input_invalid",
                        detail={"input": slot, "scene_id": scene_id, "reason": "missing"},
                    )
                artifact = self.run.publish(
                    ArtifactKind.part_png,
                    keys[slot],
                    self._stage_bytes(keys[slot], built[slot], ".png"),
                    stage=Stage.layer,
                    scene_id=scene_id,
                    slot=slot,
                )
                artifacts[slot] = artifact
                log.rebuilt(scene_id)
                self.run.rebuilt(scene_id)
        self.dirty = True
        self._parts_artifacts[scene_id] = artifacts

    def ensure_layer(self, scene_id: str, log: StageLog) -> None:
        keys = self.keys(scene_id)
        if keys.layer is None:
            raise AppError("scene_visual_missing", detail={"scene_id": scene_id})
        artifact = self.run.find(keys.layer, stage=log, scene_id=scene_id)
        if artifact is not None:
            self._layers[scene_id] = artifact
            return
        parts = self.parts_bytes(scene_id)
        drawer = self._drawer()
        scene = self.video.scenes[scene_id]
        with self.run.building(ArtifactKind.layer_png, keys.layer, scene_id):
            check_context(self.video, self.run.ctx, self.services)
            layer, _ = drawer.draw_layer(
                self.video.settings.format.layout,
                scene,
                LAYER_CANVAS,
                parts,
                PART_SEED,
                cancel=self.run.ctx.cancel,
            )
            check_context(self.video, self.run.ctx, self.services)
            if layer is None:
                layer = _transparent_layer()
            artifact = self.run.publish(
                ArtifactKind.layer_png,
                keys.layer,
                self._stage_bytes(keys.layer, layer, ".png"),
                stage=Stage.layer,
                scene_id=scene_id,
            )
        log.rebuilt(scene_id)
        self.run.rebuilt(scene_id)
        self.dirty = True
        self._layers[scene_id] = artifact

    def parts_bytes(self, scene_id: str) -> dict[str, bytes]:
        cached = self._parts_bytes.get(scene_id)
        if cached is not None:
            return cached
        artifacts = self._parts_artifacts.get(scene_id)
        if artifacts is None:
            raise AppError("render_input_invalid", detail={"input": "parts"})
        data = {
            slot: self.run.store.path(artifact.id).read_bytes()
            for slot, artifact in artifacts.items()
        }
        self._parts_bytes[scene_id] = data
        return data

    def _build_parts(self, scene_id: str, missing: set[str]) -> dict[str, bytes]:
        builder = self._parts_builder_for()
        scene = self.video.scenes[scene_id]
        visual = scene.visual
        if visual is None:
            raise AppError("scene_visual_missing", detail={"scene_id": scene_id})
        placement = visual.characters[0] if visual.characters else None
        built: dict[str, bytes] = {}
        theme_parts = getattr(builder, "theme_parts", None)
        build_character = any(name != SKIN for name in missing)
        build_skin = SKIN in missing and not callable(theme_parts)
        if build_character or build_skin:
            if placement is None:
                raise AppError(
                    "render_input_invalid",
                    detail={"input": "character", "scene_id": scene_id, "reason": "missing"},
                )
            check_context(self.video, self.run.ctx, self.services)
            built = builder.build_parts(
                self.video.settings.visual.art_style,
                self.video.settings.visual.character,
                placement.expression_id,
                placement.pose_id,
                PART_SEED,
                cancel=self.run.ctx.cancel,
            )
            check_context(self.video, self.run.ctx, self.services)
        if SKIN in missing or SKIN in built:
            if callable(theme_parts):
                skin = theme_parts(
                    self.video.settings.visual.art_style,
                    self.video.settings.visual.theme_id,
                )
                built = {**skin, **built}
            elif SKIN not in built:
                raise AppError(
                    "render_input_invalid",
                    detail={"input": SKIN, "reason": "unsupported_builder"},
                )
        return built

    def _parts_builder_for(self) -> Any:
        if self._parts_builder is None:
            self._parts_builder = self.services.templates.parts_builder(
                self.video.settings.visual.art_style
            )
        return self._parts_builder

    def _drawer(self) -> Any:
        if self._layer_drawer is None:
            self._layer_drawer = self.services.templates.layer_drawer(
                self.video.settings.format.layout
            )
        return self._layer_drawer

    # --- still and clip ----------------------------------------------------------

    def ensure_still(
        self, scene_id: str, timing: Timing | None, log: StageLog
    ) -> None:
        key = self.keys(scene_id).still
        if key is None:
            raise AppError("scene_visual_missing", detail={"scene_id": scene_id})
        artifact = self.run.find(key, stage=log, scene_id=scene_id)
        if artifact is not None:
            self._stills[scene_id] = artifact
            return
        layer = self._layer_bytes(scene_id)
        parts = self.parts_bytes(scene_id)
        with self.run.building(ArtifactKind.still_png, key, scene_id):
            check_context(self.video, self.run.ctx, self.services)
            path = self.services.render.still(
                self.video, scene_id, parts, layer, timing, ctx=self.run.ctx
            )
            check_context(self.video, self.run.ctx, self.services)
            artifact = self.run.publish(
                ArtifactKind.still_png,
                key,
                path,
                stage=Stage.still,
                scene_id=scene_id,
                media={"width": STILL_SIZE[0], "height": STILL_SIZE[1]},
            )
        log.rebuilt(scene_id)
        self.run.rebuilt(scene_id)
        self.dirty = True
        self._stills[scene_id] = artifact

    def ensure_clip(self, scene_id: str, log: StageLog) -> None:
        key = self.keys(scene_id).clip
        if key is None:
            raise AppError("scene_visual_missing", detail={"scene_id": scene_id})
        artifact = self.run.find(key, stage=log, scene_id=scene_id)
        if artifact is not None:
            self._clips[scene_id] = artifact
            return
        parts = self.parts_bytes(scene_id)
        layer = self._layer_bytes(scene_id)
        with self.run.building(ArtifactKind.clip_mp4, key, scene_id):
            check_context(self.video, self.run.ctx, self.services)
            path = self.services.render.clip(
                self.video,
                scene_id,
                parts,
                layer,
                self.timing(scene_id),
                ctx=self.run.ctx,
            )
            check_context(self.video, self.run.ctx, self.services)
            artifact = self.run.publish(
                ArtifactKind.clip_mp4,
                key,
                path,
                stage=Stage.clip,
                scene_id=scene_id,
                media=CLIP_MEDIA,
            )
        log.rebuilt(scene_id)
        self.run.rebuilt(scene_id)
        self.dirty = True
        self._clips[scene_id] = artifact

    def _layer_bytes(self, scene_id: str) -> bytes | None:
        artifact = self._layers.get(scene_id)
        if artifact is None:
            return None
        return self.run.store.path(artifact.id).read_bytes()

    # --- sound, timing and assembly ---------------------------------------------

    def ensure_tts(self, scene_id: str, log: StageLog) -> None:
        scene = self.video.scenes[scene_id]
        keys = self.keys(scene_id).tts
        artifacts: dict[str, Artifact] = {}
        for line in scene.lines:
            cache_key = keys.get(line.id)
            if cache_key is None:
                raise AppError(
                    "invalid_combination", detail={"line_id": line.id, "reason": "tts_key"}
                )
            artifact = self.run.find(
                cache_key, stage=log, scene_id=scene_id, line_id=line.id
            )
            if artifact is not None:
                artifacts[line.id] = artifact
                continue
            with self.run.building(
                ArtifactKind.tts_wav, cache_key, scene_id, line.id
            ):
                check_context(self.video, self.run.ctx, self.services)
                path = self.services.voice.synthesize(
                    self.voice_manifest(),
                    self.video.settings.language.value,
                    line,
                    ctx=self.run.ctx,
                )
                check_context(self.video, self.run.ctx, self.services)
                artifact = self.run.publish(
                    ArtifactKind.tts_wav,
                    cache_key,
                    path,
                    stage=Stage.tts,
                    scene_id=scene_id,
                    line_id=line.id,
                )
            artifacts[line.id] = artifact
            log.rebuilt(scene_id)
            self.run.rebuilt(scene_id)
            self.dirty = True
        self._tts[scene_id] = artifacts

    def ensure_timing(self, scene_id: str, log: StageLog) -> None:
        key = self.keys(scene_id).timing
        artifact = self.run.find(key, stage=log, scene_id=scene_id)
        if artifact is not None:
            self._timings[scene_id] = _load_timing(self.run, artifact, scene_id)
            return
        scene = self.video.scenes[scene_id]
        tts = {
            line_id: _ref(artifact)
            for line_id, artifact in self._tts[scene_id].items()
        }
        with self.run.building(ArtifactKind.timing_json, key, scene_id):
            check_context(self.video, self.run.ctx, self.services)
            timing = self.services.voice.timing(
                scene,
                self.video.settings.audio.voice,
                tts,
                self.video.settings.caption.mode.value,
                self.video.settings.language,
                ctx=self.run.ctx,
            )
            check_context(self.video, self.run.ctx, self.services)
            artifact = self.run.publish(
                ArtifactKind.timing_json,
                key,
                self._stage_bytes(key, timing.model_dump_json().encode("utf-8"), ".json"),
                stage=Stage.align,
                scene_id=scene_id,
            )
        self._timings[scene_id] = timing
        log.rebuilt(scene_id)
        self.run.rebuilt(scene_id)
        self.dirty = True

    def ensure_mix(self, log: StageLog) -> None:
        key = self.graph.mix
        artifact = self.run.find(key, stage=log)
        if artifact is not None:
            self._mix = artifact
            return
        timings = [self._timings[scene_id] for scene_id in self.video.scene_order]
        tts = {
            line_id: self.run.store.path(item.id)
            for scene in self._tts.values()
            for line_id, item in scene.items()
        }
        with self.run.building(ArtifactKind.mix_wav, key):
            check_context(self.video, self.run.ctx, self.services)
            path = self.services.sound.mix(self.video, timings, tts, ctx=self.run.ctx)
            check_context(self.video, self.run.ctx, self.services)
            self._mix = self.run.publish(
                ArtifactKind.mix_wav,
                key,
                path,
                stage=Stage.mix,
                media=MIX_MEDIA,
            )
            log.built_artifact()
        self.dirty = True

    def ensure_final(self, log: StageLog) -> None:
        key = self.graph.final
        artifact = self.run.find(key, stage=log)
        if artifact is not None:
            self._final = artifact
            return
        if self._mix is None:
            raise AppError("media_invalid_input", detail={"reason": "mix_missing"})
        clips = [
            self.run.store.path(self._clips[scene_id].id)
            for scene_id in self.video.scene_order
        ]
        with self.run.building(ArtifactKind.final_mp4, key):
            check_context(self.video, self.run.ctx, self.services)
            path = self.services.assemble.final(
                clips, self.run.store.path(self._mix.id), ctx=self.run.ctx
            )
            check_context(self.video, self.run.ctx, self.services)
            self._final = self.run.publish(
                ArtifactKind.final_mp4,
                key,
                path,
                stage=Stage.assemble,
                media=CLIP_MEDIA,
            )
            log.built_artifact()
        self.dirty = True

    def ensure_srt(self, log: StageLog) -> None:
        key = self.graph.srt
        artifact = self.run.find(key, stage=log)
        if artifact is not None:
            self._srt = artifact
            return
        timings = [self._timings[scene_id] for scene_id in self.video.scene_order]
        with self.run.building(ArtifactKind.srt, key):
            text = self.services.assemble.srt(self.video, timings)
            self._srt = self.run.publish(
                ArtifactKind.srt,
                key,
                self._stage_bytes(key, text.encode("utf-8"), ".srt"),
                stage=Stage.srt,
            )
            log.built_artifact()
        self.dirty = True

    def voice_manifest(self) -> VoiceManifest:
        if self._voice_manifest is None:
            ref = self.video.settings.audio.voice
            manifest = self.services.catalog_port.get("voice", ref.id, ref.revision)
            if not isinstance(manifest, VoiceManifest):
                raise AppError("unknown_catalog_id", detail={"kind": "voice", "id": ref.id})
            self._voice_manifest = manifest
        return self._voice_manifest

    def _stage_bytes(self, cache_key: str, data: bytes, suffix: str) -> Path:
        path = self.run.staged(cache_key, suffix)
        path.write_bytes(data)
        return path


def _ref(artifact: Artifact) -> ArtifactRef:
    return ArtifactRef(
        id=artifact.id, digest=artifact.digest, cache_key=artifact.cache_key
    )


def _load_timing(run: RunState, artifact: Artifact, scene_id: str) -> Timing:
    try:
        return Timing.model_validate_json(run.store.path(artifact.id).read_bytes())
    except ValidationError as error:
        raise AppError("timing_mismatch", detail={"scene_id": scene_id}) from error


def _transparent_layer() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", LAYER_CANVAS, (0, 0, 0, 0)).save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


__all__ = [
    "prepare_scene_data",
    "load_video",
    "planned_video",
    "require_stage",
    "run_generate",
    "run_preview",
    "target_scene_ids",
]
