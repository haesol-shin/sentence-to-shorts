"""Reference video ingestion and analysis.

A reference arrives as an upload or an allowed link, is checked, and is read as
sampled frames plus a transcript. The model sees frames and transcript only; the
cut count, silence ratio and music estimate are measured here. The result is a
change plan of ``set`` ops with origin ``reference``, a ``ReferenceSummary`` and
palette hints. Up to four chosen frames are kept in the video's project storage,
with their palette, so a later style request can show the model the same look.
The attempt's source, audio and the other frames live in ``CACHE_DIR/r/<job>/``
and that folder is removed when the analysis ends, however it ends. The staged
upload is only copied, so the job runner can keep it for a retry and delete it
after the job succeeds, is cancelled or cannot be retried. No URL and no file
name is stored: a link is kept as its platform only.
"""

from __future__ import annotations

import math
import secrets
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from app.ports import (
    AppError,
    AppSettings,
    CatalogPort,
    DownloaderPort,
    JobContext,
    LlmPort,
    MediaInfo,
    MediaPort,
    ProjectStore,
    ReferenceFrameStore,
    ReferenceOutcome,
    Segment,
    ServiceDeps,
    TranscriberPort,
    UploadSource,
)
from app.schemas.change import ChangePlan, ChangeSource, ChangeStatus, Effects, Target
from app.schemas.common import ContractModel
from app.schemas.job import Job, Stage, WaitingOn
from app.schemas.video import (
    MAX_REFERENCE_FRAMES,
    Measured,
    ReferenceKind,
    ReferenceLook,
    ReferenceStatus,
    ReferenceSummary,
    Video,
)
from app.services.reference import measure, values, vision
from app.services.reference.links import platform_of

WORK_ROOT = "r"
SOURCE_NAME = "ref_{}.src"
FRAME_DIR = "frames"
AUDIO_NAME = "audio.wav"
SAMPLE_FRAMES = 60
MIN_EVERY_MS = 500
FRAME_SIDE = 1280
DOWNLOAD_MAX_MS = 300_000
UNDECODABLE = ("media_failed", "media_unreadable")
STEPS = 5


class StyleHints(ContractModel):
    """Look of the reference that a style request may use. Colours only."""

    palette: list[str]


class ReferenceReport(ContractModel):
    """The job result of an analysis: the summary to keep and what the plan left out."""

    summary: ReferenceSummary
    style_hints: StyleHints
    kept_user_values: list[str]


@dataclass(frozen=True)
class _Observed:
    info: MediaInfo
    frames: list[bytes]
    scene_count: int
    facts: measure.AudioFacts
    transcript: str


FrameT = TypeVar("FrameT")


def _spread(items: list[FrameT], count: int) -> list[FrameT]:
    """``count`` items evenly spaced over the list, first and last included."""
    if count <= 0:
        return []
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[0]]
    step = (len(items) - 1) / (count - 1)
    return [items[round(index * step)] for index in range(count)]


def _keep_indexes(count: int, subject: list[int]) -> list[int]:
    """Positions to keep: one-based subject frames first, spread over the video."""
    if count <= MAX_REFERENCE_FRAMES:
        return list(range(count))
    preferred = sorted({index - 1 for index in subject if 1 <= index <= count})
    picked = _spread(preferred, MAX_REFERENCE_FRAMES)
    rest = [index for index in range(count) if index not in picked]
    picked.extend(_spread(rest, MAX_REFERENCE_FRAMES - len(picked)))
    return sorted(picked)


class ReferenceService:
    def __init__(
        self,
        downloader: DownloaderPort,
        media: MediaPort,
        transcriber: TranscriberPort,
        llm: LlmPort,
        *,
        catalog: CatalogPort,
        project_store: ProjectStore,
        frames: ReferenceFrameStore,
        cache_dir: Path,
        max_upload_bytes: int,
        max_upload_ms: int,
        link_enabled: bool = True,
    ) -> None:
        self.downloader = downloader
        self.media = media
        self.transcriber = transcriber
        self.llm = llm
        self.catalog = catalog
        self.project_store = project_store
        self.frames = frames
        self.cache_dir = cache_dir
        self.max_upload_bytes = max_upload_bytes
        self.max_upload_ms = max_upload_ms
        self.link_enabled = link_enabled

    # Work folder

    def _work_dir(self, ctx: JobContext) -> Path:
        return self.cache_dir / WORK_ROOT / ctx.job_dir.name

    @staticmethod
    def _remove(work: Path) -> bool:
        """Delete the work folder. True when nothing of it is left."""
        if work.is_symlink():
            work.unlink(missing_ok=True)
        else:
            shutil.rmtree(work, ignore_errors=True)
        return not work.exists()

    def _invalid(self, *, link: bool, reason: str, **detail: object) -> AppError:
        code = "media_invalid_input" if link else "upload_invalid"
        return AppError(code, detail={"reason": reason, **detail})

    # Ingest

    def ingest(
        self, upload: Path | None, url: str | None, *, ctx: JobContext
    ) -> Path:
        """Put the reference file into this job's work folder and return its path.

        An upload is copied: the staged file stays where it is, so the runner can
        keep it for another attempt and remove it when the job is over. A link is
        downloaded into the work folder. The folder is removed here when ingesting
        fails.
        """
        if (upload is None) == (url is None):
            raise ValueError("ingest takes exactly one of an upload or a link")
        ctx.cancel.raise_if_set()
        work = self._work_dir(ctx)
        done = False
        try:
            with ctx.stage(Stage.ref_fetch):
                if url is not None:
                    source = self._download(url, work, ctx)
                else:
                    assert upload is not None
                    source = self._take(upload, work)
            ctx.cancel.raise_if_set()
            done = True
            return source
        finally:
            if not done:
                self._remove(work)

    def _download(self, url: str, work: Path, ctx: JobContext) -> Path:
        if not self.link_enabled:
            raise AppError("link_disabled")
        platform_of(url)
        remaining_ms = int((ctx.deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise AppError("deadline_exceeded")
        work.mkdir(parents=True, exist_ok=True)
        ctx.progress(done=0, total=STEPS, waiting_on=WaitingOn.download)
        source = self.downloader.fetch(
            url,
            out_dir=work,
            max_bytes=self.max_upload_bytes,
            max_ms=min(DOWNLOAD_MAX_MS, remaining_ms),
            cancel=ctx.cancel,
        )
        ctx.progress(done=1, total=STEPS)
        return source

    def _take(self, upload: Path, work: Path) -> Path:
        """Copy the staged upload into the attempt, leaving the staged file in place."""
        if upload.is_symlink() or not upload.is_file():
            raise self._invalid(link=False, reason="missing")
        size = upload.stat().st_size
        if size == 0:
            raise self._invalid(link=False, reason="empty")
        if size > self.max_upload_bytes:
            raise self._invalid(link=False, reason="too_large", max_bytes=self.max_upload_bytes)
        work.mkdir(parents=True, exist_ok=True)
        target = work / SOURCE_NAME.format(secrets.token_hex(8))
        try:
            shutil.copyfile(upload, target)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target

    def submit_upload(
        self,
        video_id: str,
        base_revision: int,
        upload: UploadSource,
        idempotency_key: str | None,
    ) -> Job:
        raise NotImplementedError

    # Analysis

    def analyze(
        self, source: Path, video: Video, *, ctx: JobContext
    ) -> ReferenceOutcome:
        """Read the reference and propose format values from it.

        The work folder is removed in ``finally``, so a failure and a cancel leave
        nothing behind either. The outcome carries the stored plan id, or None when
        no value is left to propose, and a ``ReferenceReport``.
        """
        link = ctx.input.get("url") is not None
        work = self._work_dir(ctx)
        try:
            host = platform_of(str(ctx.input["url"])) if link else None
            seen = self._observe(source, work, link=link, ctx=ctx)
            answer = self._ask(seen, ctx)
        finally:
            gone = self._remove(work)
        ctx.cancel.raise_if_set()
        built = values.build(video, answer, seen.scene_count, self.catalog)
        change_id = self._store(video, built) if built.ops else None
        reference_id = self.project_store.new_id("rf")
        palette = [color.lower() for color in answer.palette]
        summary = ReferenceSummary(
            id=reference_id,
            kind=ReferenceKind.link if link else ReferenceKind.file,
            host=host,
            status=ReferenceStatus.analyzed,
            source_deleted=gone and not source.exists(),
            measured=Measured(
                duration_ms=seen.info.duration_ms or 0,
                scene_count=seen.scene_count,
                silence_ratio=seen.facts.silence_ratio,
                has_bgm=seen.facts.has_bgm,
            ),
            style=ReferenceLook(
                palette=palette,
                frames=self._keep(video, reference_id, seen.frames, answer.subject_frames),
                caption_box=answer.caption_box,
            ),
        )
        report = ReferenceReport(
            summary=summary,
            style_hints=StyleHints(palette=palette),
            kept_user_values=built.kept_user_values,
        )
        ctx.progress(done=STEPS, total=STEPS)
        return ReferenceOutcome(change_id=change_id, reference=report)

    # Kept look

    def _keep(
        self, video: Video, reference_id: str, sent: list[bytes], subject: list[int]
    ) -> list[str]:
        """Store up to four of the sent frames and return their file names.

        ``_observe`` extracts the frames at ``FRAME_SIDE`` already, so the bytes
        the model saw are the bytes kept; no re-encode changes what it saw.
        """
        frames = [sent[index] for index in _keep_indexes(len(sent), subject)]
        return self.frames.put(video.project_id, video.id, reference_id, frames)

    def kept_frames(self, video: Video) -> list[bytes]:
        """The frames stored with the video's reference, in stored order."""
        reference = video.reference
        if reference is None or reference.style is None:
            return []
        return self.frames.get(
            video.project_id, video.id, reference.id, reference.style.frames
        )

    def prune_frames(self, video: Video) -> None:
        """Delete every kept-frame folder the video's reference does not use."""
        reference = video.reference
        keep = None if reference is None else reference.id
        self.frames.prune(video.project_id, video.id, keep)

    def _probe(self, source: Path, *, link: bool) -> MediaInfo:
        if not source.is_file() or source.is_symlink():
            raise self._invalid(link=link, reason="missing")
        try:
            info = self.media.probe(source)
        except AppError as error:
            if error.code in UNDECODABLE:
                raise self._invalid(link=link, reason="undecodable") from error
            raise
        if info.width is None or info.height is None:
            raise self._invalid(link=link, reason="no_video")
        if info.duration_ms is None or info.duration_ms <= 0:
            raise self._invalid(link=link, reason="undecodable")
        if info.duration_ms > self.max_upload_ms:
            raise self._invalid(link=link, reason="too_long", max_ms=self.max_upload_ms)
        return info

    def _observe(self, source: Path, work: Path, *, link: bool, ctx: JobContext) -> _Observed:
        cancel = ctx.cancel
        cancel.raise_if_set()
        info = self._probe(source, link=link)
        duration = info.duration_ms or 0
        with ctx.stage(Stage.ref_frames):
            frames = self.media.extract_frames(
                source,
                every_ms=max(MIN_EVERY_MS, math.ceil(duration / SAMPLE_FRAMES)),
                max_frames=SAMPLE_FRAMES,
                max_side=FRAME_SIDE,
                out_dir=work / FRAME_DIR,
                cancel=cancel,
            )
            if not frames:
                raise self._invalid(link=link, reason="no_frames")
            sent = [path.read_bytes() for path in _spread(frames, vision.MAX_FRAMES)]
            cuts = measure.scene_count(frames)
        ctx.progress(done=2, total=STEPS)
        wav: Path | None = None
        segments: list[Segment] = []
        with ctx.stage(Stage.ref_transcribe):
            if info.sample_rate is not None:
                wav = work / AUDIO_NAME
                self.media.extract_audio(source, out=wav, max_ms=self.max_upload_ms, cancel=cancel)
                segments = self.transcriber.transcribe(wav, None, cancel=cancel)
            facts = measure.audio_facts(wav, segments)
        ctx.progress(done=3, total=STEPS)
        transcript = "\n".join(item.text for item in segments)
        return _Observed(info, sent, cuts, facts, transcript)

    def _ask(self, seen: _Observed, ctx: JobContext) -> vision.ReferenceValues:
        allowed = {
            "story_structures": [item.id for item in self.catalog.list("story_structure")],
            "layouts": [item.id for item in self.catalog.list("template")],
        }
        ctx.progress(done=3, total=STEPS, waiting_on=WaitingOn.llm)
        answer = vision.ask(
            self.llm, frames=seen.frames, transcript=seen.transcript, allowed=allowed, ctx=ctx
        )
        ctx.progress(done=4, total=STEPS)
        return answer

    def _store(self, video: Video, built: values.Built) -> str:
        """Keep the proposal as a plan; effects and confirmation are computed from keys later."""
        plan = ChangePlan(
            schema_version=2,
            id=self.project_store.new_id("c"),
            video_id=video.id,
            base_revision=video.revision,
            created_at=datetime.now(UTC),
            source=ChangeSource.reference,
            target=Target(scene_id=None, pointer=None),
            ops=list(built.ops),
            effects=Effects(
                script=False,
                scene_ids_text=[],
                scene_ids_tts=[],
                scene_ids_render=[],
                mix=False,
                assemble=False,
                locked_keys=[],
                overwrites_user_values=[],
            ),
            requires_confirmation=False,
            confirmation_reasons=[],
            warnings=[],
            unsupported=[],
            notes=[],
            status=ChangeStatus.proposed,
            applied_revision=None,
        )
        self.project_store.put_change(plan)
        return plan.id


def create(settings: AppSettings, deps: ServiceDeps) -> ReferenceService:
    uploads = getattr(getattr(settings, "app", None), "uploads", None)
    if uploads is None:
        raise RuntimeError("the settings carry no upload limits")
    return ReferenceService(
        deps.downloader,
        deps.media,
        deps.transcriber,
        deps.llm,
        catalog=deps.catalog,
        project_store=deps.project_store,
        frames=deps.reference_frames,
        cache_dir=settings.cache_dir,
        max_upload_bytes=uploads.reference_max_bytes,
        max_upload_ms=uploads.reference_max_ms,
        link_enabled=settings.deployment != "hosted",
    )


__all__ = ["ReferenceReport", "ReferenceService", "StyleHints", "create"]
