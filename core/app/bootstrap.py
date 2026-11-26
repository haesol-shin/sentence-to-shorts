"""The only composition root: wire adapters from providers and assemble services.

Every factory is called here once. A provider name that is not registered, or a
registered provider that is not implemented, fails at startup with a clear error.
Only external adapters have a fixture implementation; services have one assembly.

The state.db handle is opened on first use, not while building, because the server
takes its instance lock after the runtime is built. The job runner starts after
that lock, on the first request, so recovery never runs beside another server.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from app.access import SessionGuard
from app.access import create as create_access
from app.jobs import JobRunner, LocalJobContext, SqliteJobStore
from app.llm.credentials import KeyringVault
from app.llm.providers.anthropic_api.adapter import create as create_anthropic
from app.llm.providers.claude_cli.adapter import create as create_claude_cli
from app.llm.providers.fixture.adapter import create as create_fixture_llm
from app.llm.providers.openai_compat.adapter import create as create_openai_compat
from app.plugins.registry import Registry
from app.ports import (
    AlignerPort,
    AppError,
    ArtifactStore,
    CatalogPort,
    DownloaderPort,
    JobContext,
    JobInputStore,
    LlmPort,
    MediaPort,
    ProjectStore,
    Proposal,
    SandboxPort,
    ServiceDeps,
    SubmitResult,
    TranscriberPort,
    TtsPort,
    UsageReader,
)
from app.runtime import RuntimeSetup
from app.runtime import create as create_runtime_setup
from app.runtime.models import ALIGN_EN, VOICE
from app.schemas.api import PrecheckReport
from app.schemas.change import Op, SetOp, Target
from app.schemas.common import PERSONAL_OWNER_ID, Language, Mood, Origin
from app.schemas.job import Job, JobKind, JobState, Progress, WaitingOn
from app.schemas.video import STAGE_ORDER, Video, VideoStage
from app.services.assemble import service as assemble_service
from app.services.pipeline.run import run as run_pipeline
from app.services.pipeline.types import Services
from app.services.project import service as project_service
from app.services.reference import service as reference_service
from app.services.render import BUILTIN_LAYER_DRAWERS, BUILTIN_PARTS_BUILDERS
from app.services.render import service as render_service
from app.services.sound import service as sound_service
from app.services.sound.service import SoundService
from app.services.story import draft as story_draft
from app.services.story import interpret as story_interpret
from app.services.story import precheck as story_precheck
from app.services.story import scene_data as story_scene_data
from app.services.story import scene_edit as story_scene_edit
from app.services.story import script as story_script
from app.services.story.service import StoryService
from app.services.templates import service as templates_service
from app.services.voice import service as voice_service
from app.settings import Settings
from app.storage.artifacts import FileArtifactStore
from app.storage.credentials import SqliteCredentialStore
from app.storage.job_inputs import create_job_input_store
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore, new_typeid
from app.storage.reference import FileReferenceFrames
from app.storage.sqlite import Database
from app.storage.usage import PriceTable, SqliteUsageReader
from app.tools.align import adapter as align_adapter
from app.tools.asr import adapter as asr_adapter
from app.tools.downloaders import adapter as downloader_adapter
from app.tools.media import adapter as media_adapter
from app.tools.sandbox import adapter as sandbox_adapter
from app.tools.tts.fixed_wav.adapter import create as create_fixed_wav
from app.tools.tts.qwen3_tts_0_6b.adapter import create as create_qwen3_tts

AdapterFactory = Callable[[Settings], object]
Built = TypeVar("Built")

ADAPTER_FACTORIES: dict[str, dict[str, AdapterFactory]] = {
    "llm": {
        "fixture": create_fixture_llm,
        "anthropic_api": create_anthropic,
        "openai_compat": create_openai_compat,
        "claude_cli": create_claude_cli,
    },
    "tts": {"fixed_wav": create_fixed_wav, "qwen3-tts-0.6b": create_qwen3_tts},
    "aligner": {
        "default": align_adapter.create,
        "skeleton": align_adapter.create_skeleton,
        "whisperx": align_adapter.create,
    },
    "transcriber": {"default": asr_adapter.create, "skeleton": asr_adapter.create_skeleton},
    "media": {"default": media_adapter.create, "skeleton": media_adapter.create_skeleton},
    "sandbox": {"default": sandbox_adapter.create, "skeleton": sandbox_adapter.create_skeleton},
    "downloader": {
        "default": downloader_adapter.create,
        "skeleton": downloader_adapter.create_skeleton,
    },
}

LLM_JOB_KINDS = frozenset(
    {
        JobKind.draft,
        JobKind.script,
        JobKind.chat,
        JobKind.precheck,
        JobKind.style,
        JobKind.template,
        JobKind.bgm_code,
    }
)
STAGE_GATES: dict[JobKind, tuple[VideoStage, str]] = {
    JobKind.preview: (VideoStage.script_confirmed, "script_not_confirmed"),
    JobKind.precheck: (VideoStage.scenes_confirmed, "scenes_not_confirmed"),
    JobKind.generate: (VideoStage.scenes_confirmed, "scenes_not_confirmed"),
}
BGM_MOOD_PATH = "/settings/audio/bgm/mood"
BGM_ENTRY_PATH = "/settings/audio/bgm/entry"


@dataclass(frozen=True)
class AppDeclaration:
    """What OpenAPI and the docs flags need, without building adapters."""

    version: str
    docs_enabled: bool
    settings: Settings


def declare(settings: Settings | None = None) -> AppDeclaration:
    resolved = settings or Settings()
    return AppDeclaration(
        version=resolved.app_version,
        docs_enabled=not resolved.lan,
        settings=resolved,
    )


class _StateDatabase:
    """state.db, opened on first use and never again after close."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._db: Database | None = None
        self._closed = False

    def _open(self) -> Database:
        with self._lock:
            if self._closed:
                raise RuntimeError("state.db is closed")
            if self._db is None:
                self._db = Database.open(self._path)
            return self._db

    def read(self) -> AbstractContextManager[Any]:
        return self._open().read()

    def write(self) -> AbstractContextManager[Any]:
        return self._open().write()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            db, self._db = self._db, None
        if db is not None:
            db.close()


def _render_ready(media: MediaPort) -> bool:
    """Use the same media readiness for capabilities and submission gates."""
    ffmpeg = getattr(media, "ffmpeg", None)
    return isinstance(ffmpeg, Path) and ffmpeg.is_file()


def _close_aligner(aligner: AlignerPort) -> None:
    """Stop the selected aligner's worker; the fixture and none aligners own none."""
    close = getattr(aligner, "close", None)
    if close is not None:
        close()


class LocalJobs:
    """Queues one job per request after the gates of CONTRACTS 3 and 4.1.

    A request for the same video, kind and digest as an active job gets that job;
    another active job of the same video and kind is refused with `job_running`.
    The validated input is stored before the job row exists, so a worker that
    claims the job at once always finds it.
    """

    def __init__(
        self,
        *,
        store: SqliteJobStore,
        inputs: JobInputStore,
        projects: ProjectStore,
        llm: LlmPort,
        media: MediaPort,
        db: _StateDatabase,
        max_attempts: Mapping[str, int],
        wake: Callable[[], None],
        prepare: Callable[[Job], None] = lambda job: None,
    ) -> None:
        self._store = store
        self._inputs = inputs
        self._projects = projects
        self._llm = llm
        self._media = media
        self._db = db
        self._max_attempts = max_attempts
        self._wake = wake
        self._prepare = prepare
        self._lock = threading.Lock()

    def submit(
        self,
        kind: JobKind,
        *,
        owner_id: str,
        project_id: str | None,
        video_id: str | None,
        base_revision: int | None,
        request_digest: str,
        input: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> SubmitResult:
        with self._lock:
            if project_id is not None:
                self._projects.get_project(project_id)
            self._check(owner_id, kind, video_id, base_revision)
            active = self._active(owner_id, kind, video_id, project_id)
            if active is not None:
                if active.request_digest == request_digest:
                    return SubmitResult(job=active, status=200)
                raise AppError("job_running", detail={"job_id": active.id})
            job = self._new_job(
                kind, owner_id, project_id, video_id, base_revision, request_digest,
                idempotency_key,
            )
            self._inputs.save(job.id, input)
            created = self._store.create(job)
        # Outside the lock: queueing a model download takes its own lock and reads projects.
        self._prepare(created)
        self._wake()
        return SubmitResult(job=created, status=202)

    def retry(self, job_id: str) -> Job:
        """Queue the next attempt, unless another job of the same video and kind is active."""
        with self._lock:
            job = self._store.get(job_id)
            if job.project_id is not None:
                self._projects.get_project(job.project_id)
            if job.video_id is not None:
                self._projects.get_video(job.video_id)
            self._check_runtime(job.kind)
            active = self._active(job.owner_id, job.kind, job.video_id, job.project_id)
            if active is not None and active.id != job_id:
                raise AppError("job_running", detail={"job_id": active.id})
            queued = self._store.requeue(job_id)
        self._prepare(queued)
        self._wake()
        return queued

    def delete_project(self, project_id: str) -> None:
        """Check active jobs and delete under the submission and retry lock."""
        with self._lock:
            project = self._projects.get_project(project_id)
            video_ids = set(project.video_ids)
            for job in self._store.unfinished():
                if job.project_id == project_id or job.video_id in video_ids:
                    raise AppError("job_running", detail={"job_id": job.id})
            self._projects.delete_project(project_id)

    def find(self, *, video_id: str | None = None, state: JobState | None = None) -> list[Job]:
        """Every job, newest first, optionally of one video and one state."""
        clauses: list[str] = []
        args: list[str] = []
        if video_id is not None:
            clauses.append("video_id = ?")
            args.append(video_id)
        if state is not None:
            clauses.append("state = ?")
            args.append(state.value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._db.read() as conn:
            rows = conn.execute(
                f"SELECT doc FROM jobs{where} ORDER BY created_at DESC, id DESC", args
            ).fetchall()
        return [Job.model_validate_json(row[0]) for row in rows]

    def open_for_video(self, video_id: str) -> list[Job]:
        return [job for job in self._store.unfinished() if job.video_id == video_id]

    def _check(
        self, owner_id: str, kind: JobKind, video_id: str | None, base_revision: int | None
    ) -> None:
        if video_id is not None:
            head = self._projects.get_video(video_id)
            if base_revision is not None and base_revision != head.revision:
                raise AppError("revision_conflict", detail={"current_revision": head.revision})
            gate = STAGE_GATES.get(kind)
            if gate is not None and STAGE_ORDER.index(head.stage) < STAGE_ORDER.index(gate[0]):
                raise AppError(gate[1], detail={"stage": head.stage.value})
        if (
            kind in LLM_JOB_KINDS
            and self._llm.auth_state(owner_id) in {"missing", "expired"}
        ):
            raise AppError("llm_auth_required")
        self._check_runtime(kind)

    def _check_runtime(self, kind: JobKind) -> None:
        if kind is JobKind.generate and not _render_ready(self._media):
            raise AppError("runtime_not_ready")

    def _active(
        self, owner_id: str, kind: JobKind, video_id: str | None, project_id: str | None
    ) -> Job | None:
        for job in self._store.unfinished():
            if job.owner_id != owner_id:
                continue
            if (job.kind, job.video_id, job.project_id) == (kind, video_id, project_id):
                return job
        return None

    def _new_job(
        self,
        kind: JobKind,
        owner_id: str,
        project_id: str | None,
        video_id: str | None,
        base_revision: int | None,
        request_digest: str,
        idempotency_key: str | None,
    ) -> Job:
        return Job(
            id=new_typeid("j"),
            kind=kind,
            owner_id=owner_id,
            state=JobState.queued,
            project_id=project_id,
            video_id=video_id,
            base_revision=base_revision,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            attempt=1,
            max_attempts=self._max_attempts[kind.value],
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


class ConnectedStory(StoryService):
    """The story routes behind the StoryService contract.

    The service module only declares the methods, so the bootstrap connects each
    one to its route function. A route returns ops; nothing here writes state.
    """

    def __init__(self, llm: LlmPort, catalog: CatalogPort, sound: SoundService) -> None:
        super().__init__(llm, catalog)
        self.sound = sound

    def draft(
        self, video: Video, message: str, card_id: str | None, *, ctx: JobContext
    ) -> list[Op]:
        ops = story_draft.draft(
            video, message, card_id, llm=self.llm, catalog=self.catalog, ctx=ctx
        )
        return self._with_bgm_entry(video, ops)

    def _with_bgm_entry(self, video: Video, ops: list[Op]) -> list[Op]:
        """The draft names a BGM mood and no track; a generate needs a track.

        A track already on the video, or one the draft sets, is left alone.
        """
        bgm = video.settings.audio.bgm
        mood = bgm.mood
        for op in ops:
            if isinstance(op, SetOp) and op.path == BGM_ENTRY_PATH:
                return ops
            if isinstance(op, SetOp) and op.path == BGM_MOOD_PATH:
                mood = Mood(op.value)
        if bgm.entry is not None:
            return ops
        audio = video.settings.audio
        settings = video.settings.model_copy(
            update={
                "audio": audio.model_copy(update={"bgm": bgm.model_copy(update={"mood": mood})})
            }
        )
        seed = int(hashlib.sha256(video.id.encode()).hexdigest()[:8], 16)
        track = self.sound.pick_bgm(settings, [], seed)
        entry = SetOp(
            op="set",
            path=BGM_ENTRY_PATH,
            value=track.model_dump(mode="json"),
            origin=Origin.derived,
        )
        return [*ops, entry]

    def write_script(self, video: Video, *, ctx: JobContext) -> list[Op]:
        return story_script.write_script(video, llm=self.llm, catalog=self.catalog, ctx=ctx)

    def scene_data(
        self, video: Video, scene_ids: list[str], *, ctx: JobContext
    ) -> list[Op]:
        return story_scene_data.plan_scene_data(
            video, scene_ids, llm=self.llm, catalog=self.catalog, ctx=ctx
        )

    def interpret(
        self, video: Video, text: str, target: Target, *, ctx: JobContext
    ) -> Proposal:
        return story_interpret.interpret(
            video, text, target, llm=self.llm, catalog=self.catalog, ctx=ctx
        )

    def rewrite_scene(
        self, video: Video, scene_id: str, instruction: str, *, ctx: JobContext
    ) -> Proposal:
        # The plan recomputes the neighbor warnings from these ops.
        rewrite = story_scene_edit.plan_scene_rewrite(
            video,
            scene_id,
            instruction,
            llm=self.llm,
            catalog=self.catalog,
            ctx=ctx,
        )
        return Proposal(
            ops=rewrite.ops,
            notes=rewrite.notes,
            unsupported=rewrite.unsupported,
        )

    def precheck(self, video: Video, *, ctx: JobContext) -> PrecheckReport:
        return story_precheck.run_precheck(video, llm=self.llm, ctx=ctx)


@dataclass
class AppRuntime:
    settings: Settings
    catalog: Registry
    llm: LlmPort
    llm_adapter: str
    credentials: SqliteCredentialStore
    tts: TtsPort
    media: MediaPort
    sandbox: SandboxPort
    aligner: AlignerPort
    transcriber: TranscriberPort
    downloader: DownloaderPort
    project_store: ProjectStore
    artifact_store: ArtifactStore
    job_store: SqliteJobStore
    usage: UsageReader
    job_inputs: JobInputStore
    submitter: LocalJobs
    runner: JobRunner
    state_db: _StateDatabase
    services: Services
    access: SessionGuard
    runtime_setup: RuntimeSetup
    _start_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)

    @property
    def render_ready(self) -> bool:
        """True when the media adapter has an ffmpeg file to run."""
        return _render_ready(self.media)

    def start(self) -> None:
        """Recover jobs of the last run and start the workers. Idempotent.

        Callers run it once the server owns the data store, so recovery never
        closes the jobs of another live server.
        """
        if self._started:
            return
        with self._start_lock:
            if not self._started:
                self.runner.start()
                self._prepare_at_start()
                self._started = True

    def _prepare_at_start(self) -> None:
        """Queue the voice models, and the English aligner when an English project exists.

        Nothing is queued when everything is ready. The fixture profile and a hosted
        deployment download nothing, and `ensure` returns at once for them.
        """
        if not self.runtime_setup.enabled:
            return
        groups = [VOICE]
        owner = PERSONAL_OWNER_ID
        if any(
            project.defaults.language is Language.en
            for project in self.project_store.list_projects(owner)
        ):
            groups.append(ALIGN_EN)
        self.runtime_setup.ensure(groups, owner_id=owner)

    def close(self) -> None:
        try:
            # JobRunner forwards this to Thread.join. Do not close the database
            # or release the instance lock while a worker can still use them.
            self.runner.stop(timeout_s=None)  # type: ignore[arg-type]
        finally:
            try:
                self.tts.close()
            finally:
                try:
                    _close_aligner(self.aligner)
                finally:
                    self.state_db.close()


def _prepares_models(settings: Settings) -> bool:
    """Only a local app that runs real adapters downloads models; fixtures and hosted do not."""
    return settings.deployment == "local" and settings.profile != "fixture"


def held_for_models(runtime_setup: RuntimeSetup) -> Callable[[Job], bool]:
    """The runner's `blocked` check: hold a job until its model groups are ready or failed.

    A held job always has a prepare job: one that was cancelled or ended on its own is
    replaced here, so a job never waits for a download nobody runs. A failed group does
    not hold the job; `refuse_failed_models` fails it with the group's error.
    """

    def blocked(job: Job) -> bool:
        groups = runtime_setup.needs(job)
        if not groups or runtime_setup.groups_ready(groups) or runtime_setup.groups_failed(groups):
            return False
        runtime_setup.ensure(groups)
        return True

    return blocked


def refuse_failed_models(runtime_setup: RuntimeSetup, job: Job) -> None:
    """Fail a job at its start with the error of a model group that stopped."""
    failed = runtime_setup.groups_failed(runtime_setup.needs(job))
    if failed:
        group, code = next(iter(failed.items()))
        raise AppError(code or "internal", detail={"group": group})


def _selected(name: str, settings: Settings) -> str | None:
    table = settings.providers.adapters
    if settings.profile == "fixture":
        return settings.providers.fixture_adapters.get(name, table.get(name))
    return table.get(name)


def _build_adapter(name: str, settings: Settings, **options: Any) -> Built:
    implementations = ADAPTER_FACTORIES[name]
    selected = _selected(name, settings)
    if selected is None:
        raise RuntimeError(f"app.yaml does not select a {name} adapter")
    factory = implementations.get(selected)
    if factory is None:
        known = ", ".join(sorted(implementations))
        raise RuntimeError(
            f"unknown {name} adapter {selected!r}; select one of: {known}"
        )
    if selected == "skeleton" and settings.profile != "fixture":
        raise RuntimeError(
            f"{name} adapter 'skeleton' is only available in the fixture profile"
        )
    try:
        return cast(Built, factory(settings, **options) if options else factory(settings))
    except NotImplementedError as error:
        raise RuntimeError(
            f"{name} adapter {selected!r} is not implemented"
        ) from error


def _build_services(settings: Settings, deps: ServiceDeps) -> Services:
    sound = sound_service.create(settings, deps)
    render = render_service.create(settings, deps)
    return Services(
        project=project_service.create(settings, deps),
        story=ConnectedStory(deps.llm, deps.catalog, sound),
        reference=reference_service.create(settings, deps),
        render=render,
        voice=voice_service.create(settings, deps),
        sound=sound,
        assemble=assemble_service.create(settings, deps),
        templates=templates_service.create(
            settings,
            deps,
            # Templates may not import render; the composition root hands it a factory.
            render_factory=lambda catalog: render_service.RenderService(
                render.media, render.artifacts, catalog
            ),
            builtin_parts=BUILTIN_PARTS_BUILDERS,
            builtin_layers=BUILTIN_LAYER_DRAWERS,
        ),
    )


def build_runtime(settings: Settings | None = None) -> AppRuntime:
    resolved = settings or Settings()
    catalog = Registry(data_dir=resolved.data_dir)
    catalog.load()
    layout = Layout.from_settings(resolved)
    state_db = _StateDatabase(layout.state_db)
    project_store = SqliteProjectStore(cast(Database, state_db), layout)
    artifact_store = FileArtifactStore(cast(Database, state_db), layout)
    job_store = SqliteJobStore(state_db, deadlines_s=resolved.app.jobs.deadlines_s)
    prices = PriceTable.load(resolved.config_dir / "prices.yaml")
    usage = SqliteUsageReader(cast(Database, state_db), prices)
    job_inputs = create_job_input_store(resolved)
    vault = KeyringVault(resolved.brand.app_id)
    credentials = SqliteCredentialStore(cast(Database, state_db), vault)
    llm = _build_adapter("llm", resolved, credentials=credentials)
    selected_llm = cast(str, _selected("llm", resolved))
    if selected_llm in ("anthropic_api", "openai_compat"):
        vault.move_legacy(credentials, PERSONAL_OWNER_ID, selected_llm)
    tts = _build_adapter("tts", resolved)
    aligner = _build_adapter("aligner", resolved)
    transcriber = _build_adapter("transcriber", resolved)
    media = _build_adapter("media", resolved)
    sandbox = _build_adapter("sandbox", resolved)
    downloader = _build_adapter("downloader", resolved)
    staging = resolved.data_dir / "staging" / "bgm"

    def language_of(job: Job) -> str | None:
        if job.video_id is None:
            return None
        return project_store.get_video(job.video_id).settings.language.value

    runtime_setup = create_runtime_setup(
        resolved,
        downloader,
        job_store,
        inputs=job_inputs,
        enabled=_prepares_models(resolved),
        language_of=language_of,
    )
    submitter = LocalJobs(
        store=job_store,
        inputs=job_inputs,
        projects=project_store,
        llm=cast(LlmPort, llm),
        media=cast(MediaPort, media),
        db=state_db,
        max_attempts=resolved.app.jobs.max_attempts,
        wake=lambda: runner.notify(),
        prepare=lambda job: runtime_setup.ensure(runtime_setup.needs(job)),
    )
    deps = ServiceDeps(
        project_store=project_store,
        artifact_store=artifact_store,
        job_store=job_store,
        reference_frames=FileReferenceFrames(layout),
        catalog=catalog,
        llm=cast(LlmPort, llm),
        tts=tts,
        aligner=aligner,
        transcriber=transcriber,
        media=media,
        sandbox=sandbox,
        downloader=downloader,
        submitter=submitter,
        bgm_staging_dir=resolved.data_dir / "staging" / "bgm",
    )
    services = _build_services(resolved, deps)

    blocked = held_for_models(runtime_setup)

    def run_job(job: Job, ctx: LocalJobContext) -> Mapping[str, Any]:
        if job.kind is JobKind.runtime_prepare:
            return runtime_setup.run_job(job, ctx)
        refuse_failed_models(runtime_setup, job)
        return run_pipeline(job, ctx, services)

    runner = JobRunner(
        job_store,
        artifact_store,
        job_inputs,
        run_job,
        cache_dir=resolved.cache_dir,
        bgm_staging_dir=staging,
        price_version=prices.version,
        blocked=blocked,
    )
    access = create_access(resolved)
    return AppRuntime(
        settings=resolved,
        catalog=catalog,
        llm=deps.llm,
        llm_adapter=selected_llm,
        credentials=credentials,
        tts=deps.tts,
        media=deps.media,
        sandbox=deps.sandbox,
        aligner=deps.aligner,
        transcriber=deps.transcriber,
        downloader=deps.downloader,
        project_store=project_store,
        artifact_store=artifact_store,
        job_store=job_store,
        usage=usage,
        job_inputs=job_inputs,
        submitter=submitter,
        runner=runner,
        state_db=state_db,
        services=services,
        access=access,
        runtime_setup=runtime_setup,
    )
