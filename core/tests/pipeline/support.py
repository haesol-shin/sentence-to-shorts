"""Deterministic harness for pipeline tests.

Real project and artifact stores, the real catalog and the production cache-key
graph; fake media, voice, sound, assembly and template work. The fixture video is
persisted with current catalog revisions so `build_view` and `plan_change` run
against real manifests without starting a runtime model or ffmpeg.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.plugins.registry import Registry
from app.ports import (
    AppError,
    Cancelled,
    JobContext,
    Proposal,
    ReferenceOutcome,
    Usage,
)
from app.schemas.api import CreateProjectRequest, PrecheckReport
from app.schemas.artifact import Timing, TimingCaption, TimingLine
from app.schemas.bgm_entry import UploadBgm
from app.schemas.change import Op, SetOp, Target
from app.schemas.common import (
    PERSONAL_OWNER_ID,
    ArtifactRef,
    CaptionMode,
    Language,
    Origin,
    PinnedRef,
)
from app.schemas.job import (
    Checkpoint,
    Job,
    JobKind,
    JobState,
    Progress,
    Stage,
    WaitingOn,
)
from app.schemas.scene import Placement, Scene, SceneVisual
from app.schemas.video import CreatedBy, Video, VideoStage
from app.services.assemble.service import AssembleService
from app.services.pipeline.types import KeyRuntime, Services
from app.services.project.service import ProjectService
from app.storage.artifacts import FileArtifactStore
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore, new_typeid
from app.storage.sqlite import Database
from tests.conftest import load_json


def _digest(*parts: object) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            data = part
        elif isinstance(part, Mapping):
            data = repr(sorted(part.items())).encode("utf-8")
        else:
            data = str(part).encode("utf-8")
        hasher.update(data)
        hasher.update(b"\0")
    return hasher.hexdigest()


def _out(ctx: JobContext, directory: str, name: str, data: bytes) -> Path:
    path = ctx.job_dir / directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class Token:
    """Cancel token that tests can set without a runner."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_set(self) -> bool:
        return self._cancelled

    def raise_if_set(self) -> None:
        if self._cancelled:
            raise Cancelled("cancelled")

    def wait(self, seconds: float) -> bool:
        if self._cancelled:
            return True
        time.sleep(min(seconds, 0.01))
        return self._cancelled


@dataclass
class HarnessContext:
    job: Job
    job_dir: Path
    deadline: float
    input_payload: dict[str, Any] = field(default_factory=dict)
    cancel_token: Token = field(default_factory=Token)
    progress_calls: list[tuple[int, int, WaitingOn | None]] = field(default_factory=list)
    stage_events: list[tuple[Stage, str]] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)
    _stages: list[tuple[Stage, str]] = field(default_factory=list)

    @property
    def cancel(self) -> Token:
        return self.cancel_token

    @property
    def input(self) -> dict[str, Any]:
        return dict(self.input_payload)

    def progress(
        self, *, done: int, total: int, waiting_on: WaitingOn | None = None
    ) -> None:
        self.progress_calls.append((done, total, waiting_on))

    @contextmanager
    def stage(self, stage: Stage) -> Iterator[None]:
        self.stage_events.append((stage, "running"))
        try:
            yield
        except Cancelled:
            self.stage_events.append((stage, "cancelled"))
            raise
        except BaseException:
            self.stage_events.append((stage, "failed"))
            raise
        else:
            self.stage_events.append((stage, "done"))

    def checkpoint(self, record: Checkpoint) -> None:
        for index, existing in enumerate(self.checkpoints):
            if (
                existing.stage,
                existing.scene_id,
                existing.line_id,
            ) == (record.stage, record.scene_id, record.line_id):
                self.checkpoints[index] = record
                break
        else:
            self.checkpoints.append(record)

    def record_usage(self, usage: Usage) -> None:
        self.usage.append(usage)


class FakePartsBuilder:
    def __init__(self) -> None:
        self.build_calls: list[tuple[str, str, str]] = []
        self.theme_calls: list[str] = []

    def build_parts(
        self,
        style: PinnedRef,
        character: Any | None,
        expression_id: str,
        pose_id: str,
        seed: int,
        *,
        cancel: Any,
    ) -> dict[str, bytes]:
        self.build_calls.append((expression_id, pose_id, str(seed)))
        if character is None:
            return {}
        built = {
            slot: f"part:{slot}:{asset}".encode("utf-8")
            for slot, asset in character.slots.model_dump().items()
            if asset is not None
        }
        built["pose"] = f"pose:{pose_id}".encode("utf-8")
        built["expression"] = f"expression:{expression_id}".encode("utf-8")
        return built

    def theme_parts(self, style: PinnedRef, theme_id: str) -> dict[str, bytes]:
        self.theme_calls.append(theme_id)
        return {"skin": f"skin:{theme_id}".encode("utf-8")}


class FakeLayerDrawer:
    def __init__(self) -> None:
        self.draw_calls: list[str] = []

    def draw_layer(
        self,
        template: PinnedRef,
        scene: Scene,
        canvas: tuple[int, int],
        parts: dict[str, bytes],
        seed: int,
        *,
        cancel: Any,
    ) -> tuple[bytes | None, dict[str, Any]]:
        self.draw_calls.append(scene.id)
        data = b"layer:" + scene.id.encode("utf-8") + b":" + _digest(parts).encode("ascii")
        return data, {"canvas": list(canvas), "seed": seed}


class FakeRender:
    def __init__(self, artifacts: FileArtifactStore, catalog: Registry) -> None:
        self.artifacts = artifacts
        self.catalog = catalog
        self.media = None
        self.still_calls: list[str] = []
        self.clip_calls: list[str] = []
        self.fail_still: str | None = None
        self.fail_clip: str | None = None
        self.still_hook: Any = None

    def still(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
        timing: Timing | None,
        *,
        ctx: JobContext,
    ) -> Path:
        self.still_calls.append(scene_id)
        if self.fail_still == scene_id:
            raise AppError("render_failed", detail={"scene_id": scene_id})
        payload = _digest(
            scene_id,
            parts,
            layer,
            None if timing is None else timing.model_dump_json(),
        )
        path = _out(
            ctx, "fake-render", f"{scene_id}.png", f"still:{scene_id}:{payload}".encode()
        )
        if self.still_hook is not None:
            self.still_hook(scene_id)
        return path

    def clip(
        self,
        video: Video,
        scene_id: str,
        parts: dict[str, bytes],
        layer: bytes | None,
        timing: Timing,
        *,
        ctx: JobContext,
    ) -> Path:
        self.clip_calls.append(scene_id)
        if self.fail_clip == scene_id:
            raise AppError("render_failed", detail={"scene_id": scene_id})
        payload = _digest(scene_id, parts, layer, timing.model_dump_json())
        return _out(
            ctx, "fake-render", f"{scene_id}.mp4", f"clip:{scene_id}:{payload}".encode()
        )


class FakeVoice:
    def __init__(self) -> None:
        self.synthesize_calls: list[str] = []
        self.timing_calls: list[str] = []

    def estimate_ms(self, line: Any, language: str) -> int:
        return max(300, len(line.speech_text) * 80)

    def synthesize(
        self,
        voice: Any,
        language: str,
        line: Any,
        *,
        ctx: JobContext,
    ) -> Path:
        self.synthesize_calls.append(line.id)
        return _out(
            ctx,
            "fake-tts",
            f"{line.id}.wav",
            f"tts:{language}:{line.speech_text}".encode("utf-8"),
        )

    def timing(
        self,
        scene: Scene,
        voice: PinnedRef,
        tts: Mapping[str, ArtifactRef],
        caption_mode: str,
        language: str,
        *,
        ctx: JobContext,
    ) -> Timing:
        self.timing_calls.append(scene.id)
        mode = CaptionMode(caption_mode)
        lines: list[TimingLine] = []
        cursor = 0
        for line in scene.lines:
            ref = tts.get(line.id)
            if ref is None:
                raise AppError("tts_failed", detail={"reason": "tts_missing"})
            speech = max(1, self.estimate_ms(line, language))
            start = cursor
            end = start + speech
            lines.append(
                TimingLine(
                    line_id=line.id,
                    tts=ref,
                    start_ms=start,
                    end_ms=end,
                    speech_ms=speech,
                    caption=TimingCaption(
                        mode_used=mode, fallback_reason=None, phrases=[]
                    ),
                )
            )
            cursor = end
        return Timing(
            schema_version=2,
            scene_id=scene.id,
            voice=voice,
            duration_ms=cursor + 400,
            lines=lines,
        )


class FakeSound:
    def __init__(self, catalog: Registry) -> None:
        self.catalog = catalog
        self.media = None
        self.mix_calls: list[list[str]] = []
        self.import_calls: list[str] = []
        self.fail_mix = False

    def pick_bgm(self, settings: Any, recent: list[str], seed: int) -> PinnedRef:
        return self.catalog.pin("bgm", "builtin_loop")

    def import_upload(
        self,
        src: Path,
        project_id: str,
        *,
        ctx: JobContext,
        mood: Any = None,
    ) -> UploadBgm:
        self.import_calls.append(str(src))
        raw = load_json("contracts/valid/bgm_upload.json")
        raw["project_id"] = project_id
        raw["upload_id"] = new_typeid("u")
        raw["id"] = raw["upload_id"]
        if mood is not None:
            raw["mood"] = mood.value
        return UploadBgm.model_validate(raw)

    def mix(
        self,
        video: Video,
        timings: list[Timing],
        tts: dict[str, Path],
        *,
        ctx: JobContext,
    ) -> Path:
        self.mix_calls.append([timing.scene_id for timing in timings])
        if self.fail_mix:
            raise AppError("media_failed", detail={"stage": "mix"})
        payload = _digest(
            video.settings.audio.model_dump_json(),
            [timing.model_dump_json() for timing in timings],
            [f"{line}:{path.read_bytes().hex()}" for line, path in sorted(tts.items())],
        )
        return _out(ctx, "fake-sound", "mix.wav", f"mix:{payload}".encode())


class FakeAssemble(AssembleService):
    def __init__(self) -> None:
        super().__init__(None)  # type: ignore[arg-type]
        self.final_calls: list[int] = []
        self.srt_calls: list[str] = []

    def final(self, clips: list[Path], mix: Path, *, ctx: JobContext) -> Path:
        self.final_calls.append(len(clips))
        payload = _digest(
            [clip.read_bytes() for clip in clips], mix.read_bytes()
        )
        return _out(ctx, "fake-assemble", "final.mp4", f"final:{payload}".encode())

    def srt(self, video: Video, timings: list[Timing]) -> str:
        self.srt_calls.append(video.id)
        return super().srt(video, timings)


class FakeTemplates:
    def __init__(self, catalog: Registry) -> None:
        self.catalog = catalog
        self.sandbox = _SandboxIdentity()
        self.parts = FakePartsBuilder()
        self.layers = FakeLayerDrawer()
        self.style_calls: list[str] = []
        self.template_calls: list[str] = []
        self.bgm_calls: list[str] = []

    def parts_builder(self, style: PinnedRef) -> FakePartsBuilder:
        return self.parts

    def layer_drawer(self, template: PinnedRef) -> FakeLayerDrawer:
        return self.layers

    def generate_style(
        self,
        req: Any,
        video: Video,
        hints: dict[str, Any] | None,
        *,
        ctx: JobContext,
    ) -> PinnedRef:
        self.style_calls.append(req.instruction)
        return self.catalog.pin("art_style", video.settings.visual.art_style.id)

    def generate_template(
        self, req: Any, video: Video, *, ctx: JobContext
    ) -> PinnedRef:
        self.template_calls.append(req.instruction)
        return self.catalog.pin("template", "full_stage")

    def generate_bgm(self, req: Any, *, ctx: JobContext) -> PinnedRef:
        self.bgm_calls.append(req.mood.value)
        return self.catalog.pin("bgm", "builtin_loop")


class _SandboxIdentity:
    def runtime_digest(self) -> str:
        return "sandbox-test"


class FakeStory:
    def __init__(self, catalog: Registry) -> None:
        self.catalog = catalog
        self.draft_ops: list[Op] = []
        self.script_ops: list[Op] = []
        self.proposal_ops: list[Op] = []
        self.proposal_notes: list[str] = []
        self.proposal_unsupported: list[str] = []
        self.rewrite_ops_by_scene: dict[str, list[Op]] = {}
        self.rewrite_notes_by_scene: dict[str, list[str]] = {}
        self.rewrite_unsupported_by_scene: dict[str, list[str]] = {}
        self.draft_calls: list[tuple[str, str | None]] = []
        self.script_calls: list[str] = []
        self.scene_data_calls: list[list[str]] = []
        self.scene_data_ops: list[Op] | None = None
        self.interpret_calls: list[tuple[str, Target]] = []
        self.rewrite_calls: list[tuple[str, str]] = []
        self.precheck_calls: list[str] = []
        self.usage: Usage | None = None
        self.precheck_report: PrecheckReport | None = None

    def draft(
        self, video: Video, message: str, card_id: str | None, *, ctx: JobContext
    ) -> list[Op]:
        self.draft_calls.append((message, card_id))
        self._record(ctx)
        return list(self.draft_ops)

    def write_script(self, video: Video, *, ctx: JobContext) -> list[Op]:
        self.script_calls.append(video.id)
        self._record(ctx)
        return list(self.script_ops)

    def scene_data(
        self, video: Video, scene_ids: list[str], *, ctx: JobContext
    ) -> list[Op]:
        self.scene_data_calls.append(list(scene_ids))
        self._record(ctx)
        if self.scene_data_ops is not None:
            return list(self.scene_data_ops)
        return [self._scene_op(video, scene_id) for scene_id in scene_ids]

    def interpret(
        self, video: Video, text: str, target: Target, *, ctx: JobContext
    ) -> Any:
        self.interpret_calls.append((text, target))
        self._record(ctx)
        return Proposal(
            ops=list(self.proposal_ops),
            notes=list(self.proposal_notes),
            unsupported=list(self.proposal_unsupported),
        )

    def rewrite_scene(
        self, video: Video, scene_id: str, instruction: str, *, ctx: JobContext
    ) -> Proposal:
        self.rewrite_calls.append((scene_id, instruction))
        self._record(ctx)
        return Proposal(
            ops=list(self.rewrite_ops_by_scene.get(scene_id, [])),
            notes=list(self.rewrite_notes_by_scene.get(scene_id, [])),
            unsupported=list(self.rewrite_unsupported_by_scene.get(scene_id, [])),
        )

    def precheck(self, video: Video, *, ctx: JobContext) -> PrecheckReport:
        self.precheck_calls.append(video.id)
        self._record(ctx)
        if self.precheck_report is not None:
            return self.precheck_report
        return PrecheckReport(
            opening_promise="약속",
            ending_answer="답",
            claims=[],
            hypotheticals=[],
        )

    def _record(self, ctx: JobContext) -> None:
        if self.usage is not None:
            ctx.record_usage(self.usage)

    def _scene_op(self, video: Video, scene_id: str) -> Op:
        original = self._visual(video)
        return SetOp(
            op="set",
            path=f"/scenes/{scene_id}/visual",
            value=original.model_dump(mode="json"),
            origin=Origin.llm,
        )

    def _visual(self, video: Video) -> SceneVisual:
        characters = (
            [
                Placement(
                    anchor="center",
                    expression_id="expr_happy",
                    pose_id="pose_idle",
                    motion="none",
                )
            ]
            if video.settings.visual.character is not None
            else []
        )
        return SceneVisual(
            background_id="bg_village",
            characters=characters,
            elements=[],
            sfx=[],
            transition_in="cut",
        )


class FakeReference:
    def __init__(self) -> None:
        self.ingest_calls: list[str | None] = []
        self.analyze_calls: list[str] = []
        self.outcome: ReferenceOutcome | None = None

    def ingest(self, upload: Path | None, url: str | None, *, ctx: JobContext) -> Path:
        self.ingest_calls.append(url)
        source = upload
        if source is None:
            source = ctx.job_dir / "fake-reference" / "source.mp4"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"reference")
        return source

    def analyze(self, source: Path, video: Video, *, ctx: JobContext) -> ReferenceOutcome:
        self.analyze_calls.append(str(source))
        if self.outcome is None:
            return ReferenceOutcome(change_id=None, reference=None)
        return self.outcome


@dataclass
class Harness:
    root: Path
    layout: Layout
    db: Database
    catalog: Registry
    projects: SqliteProjectStore
    artifacts: FileArtifactStore
    project_service: ProjectService
    project: Any
    video: Video
    services: Services
    render: FakeRender
    voice: FakeVoice
    sound: FakeSound
    assemble: FakeAssemble
    templates: FakeTemplates
    story: FakeStory
    reference: FakeReference
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def job(
        self,
        kind: JobKind,
        *,
        video: Video | None = None,
        base_revision: int | None = None,
        input: dict[str, Any] | None = None,
    ) -> Job:
        needs_video = kind not in (JobKind.bgm_code, JobKind.bgm_upload)
        current = video or self.video
        video_id = current.id if needs_video else None
        if base_revision is None and needs_video:
            base_revision = current.revision
        job = Job(
            id=new_typeid("j"),
            kind=kind,
            owner_id=PERSONAL_OWNER_ID,
            state=JobState.queued,
            project_id=current.project_id if not needs_video else None,
            video_id=video_id,
            base_revision=base_revision,
            request_digest="0" * 64,
            idempotency_key=None,
            attempt=1,
            max_attempts=3,
            created_at=datetime.now(UTC),
            started_at=None,
            ended_at=None,
            deadline_at=None,
            progress=Progress(stage=None, done=0, total=0, waiting_on=WaitingOn.queue),
            stages=[],
            checkpoints=[],
            usage=[],
            result=None,
            error=None,
            partial=False,
        )
        self.inputs[job.id] = dict(input or {})
        return job

    def context(
        self,
        job: Job,
        *,
        deadline_seconds: float = 3600.0,
        input: dict[str, Any] | None = None,
    ) -> HarnessContext:
        job_dir = self.root / "jobs" / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(input) if input is not None else dict(self.inputs.get(job.id, {}))
        return HarnessContext(
            job=job,
            job_dir=job_dir,
            deadline=time.monotonic() + deadline_seconds,
            input_payload=payload,
        )

    def revise(self, video: Video, **updates: Any) -> Video:
        head = self.projects.get_video(video.id)
        changed = video.model_copy(update=updates)
        next_revision = changed.model_copy(
            update={
                "revision": head.revision + 1,
                "parent_revision": head.revision,
                "created_at": datetime.now(UTC),
                "created_by": CreatedBy.change,
            }
        )
        written = self.projects.append_revision(next_revision)
        if written.id == self.video.id:
            self.video = written
        return written

    def revise_scene(
        self,
        scene_id: str,
        *,
        display_text: str | None = None,
        speech_text: str | None = None,
    ) -> Video:
        video = self.video
        scene = video.scenes[scene_id]
        updates: dict[str, Any] = {}
        if display_text is not None:
            updates["display_text"] = display_text
        if speech_text is not None:
            updates["speech_text"] = speech_text
        if not updates:
            raise ValueError("a scene revision needs a changed value")
        lines = [
            line.model_copy(update=updates) if line.id == scene.lines[0].id else line
            for line in scene.lines
        ]
        scenes = dict(video.scenes)
        scenes[scene_id] = scene.model_copy(update={"lines": lines})
        return self.revise(video, scenes=scenes)

    def set_stage(self, stage: VideoStage) -> Video:
        return self.revise(self.video, stage=stage)

    def reorder(self, order: list[str]) -> Video:
        return self.revise(self.video, scene_order=list(order))

    def change_bgm(self, entry: PinnedRef | None) -> Video:
        audio = self.video.settings.audio
        bgm = audio.bgm.model_copy(update={"entry": entry})
        settings = self.video.settings.model_copy(
            update={"audio": audio.model_copy(update={"bgm": bgm})}
        )
        return self.revise(self.video, settings=settings)

    def new_video(
        self, *, stage: VideoStage = VideoStage.scenes_confirmed, visuals: bool = True
    ) -> Video:
        raw = load_json("contracts/valid/video_ko_just_three.json")
        video = Video.model_validate(raw)
        video = _repin(video, self.catalog)
        scenes = video.scenes
        if not visuals:
            scenes = {
                scene_id: scene.model_copy(update={"visual": None})
                for scene_id, scene in scenes.items()
            }
        created = video.model_copy(
            update={
                "id": new_typeid("v"),
                "project_id": self.project.id,
                "revision": 1,
                "parent_revision": None,
                "created_at": datetime.now(UTC),
                "created_by": CreatedBy.create,
                "stage": stage,
                "scenes": scenes,
            }
        )
        written = self.projects.append_revision(created)
        return written

    def close(self) -> None:
        self.db.close()


def build_harness(tmp_path: Path) -> Harness:
    layout = Layout(data=tmp_path / "data", cache=tmp_path / "cache")
    db = Database.open(layout.state_db)
    catalog = Registry()
    catalog.load()
    projects = SqliteProjectStore(db, layout)
    artifacts = FileArtifactStore(db, layout)
    project_service = ProjectService(projects, catalog)
    project = project_service.create_project(
        CreateProjectRequest(title="pipeline harness", language=Language.ko)
    )
    raw = Video.model_validate(load_json("contracts/valid/video_ko_just_three.json"))
    base = _repin(raw, catalog)
    video = base.model_copy(
        update={
            "id": new_typeid("v"),
            "project_id": project.id,
            "revision": 1,
            "parent_revision": None,
            "created_at": datetime.now(UTC),
            "created_by": CreatedBy.create,
        }
    )
    issues = project_service.validate(video)
    if issues:
        raise AssertionError(f"harness fixture is invalid: {issues}")
    written = projects.append_revision(video)
    video = projects.get_video(written.id)

    render = FakeRender(artifacts, catalog)
    voice = FakeVoice()
    sound = FakeSound(catalog)
    assemble = FakeAssemble()
    templates = FakeTemplates(catalog)
    story = FakeStory(catalog)
    reference = FakeReference()
    services = Services(
        project=project_service,
        story=story,  # type: ignore[arg-type]
        reference=reference,  # type: ignore[arg-type]
        render=render,  # type: ignore[arg-type]
        voice=voice,  # type: ignore[arg-type]
        sound=sound,  # type: ignore[arg-type]
        assemble=assemble,
        templates=templates,  # type: ignore[arg-type]
        artifacts=artifacts,
        catalog=catalog,
        key_runtime=KeyRuntime(
            tts_digest="tts-test",
            sandbox_digest="sandbox-test",
            aligner_digest="aligner-test",
            renderer_revision="renderer-test",
            encoder_digest="encoder-test",
        ),
        build_states={},
        previous_keys={},
    )
    return Harness(
        root=tmp_path,
        layout=layout,
        db=db,
        catalog=catalog,
        projects=projects,
        artifacts=artifacts,
        project_service=project_service,
        project=project,
        video=video,
        services=services,
        render=render,
        voice=voice,
        sound=sound,
        assemble=assemble,
        templates=templates,
        story=story,
        reference=reference,
    )


def _repin(video: Video, catalog: Registry) -> Video:
    settings = video.settings
    fmt = settings.format.model_copy(
        update={"layout": catalog.pin("template", settings.format.layout.id)}
    )
    visual = settings.visual.model_copy(
        update={"art_style": catalog.pin("art_style", settings.visual.art_style.id)}
    )
    bgm = settings.audio.bgm
    entry = bgm.entry
    audio = settings.audio.model_copy(
        update={
            "voice": catalog.pin("voice", settings.audio.voice.id),
            "bgm": bgm.model_copy(
                update={
                    "entry": None
                    if entry is None
                    else catalog.pin("bgm", entry.id)
                }
            ),
        }
    )
    caption = settings.caption.model_copy(
        update={"font_id": catalog.pin("font", settings.caption.font_id.id)}
    )
    settings = settings.model_copy(
        update={"format": fmt, "visual": visual, "audio": audio, "caption": caption}
    )
    return video.model_copy(update={"settings": settings})


__all__ = [
    "FakeAssemble",
    "FakeLayerDrawer",
    "FakePartsBuilder",
    "FakeReference",
    "FakeRender",
    "FakeSound",
    "FakeStory",
    "FakeTemplates",
    "FakeVoice",
    "Harness",
    "HarnessContext",
    "Token",
    "build_harness",
]
