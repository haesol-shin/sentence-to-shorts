"""The runtime setup service: status for `GET /runtime` and the `runtime_prepare` job.

A `runtime_prepare` job prepares the runtime files that are not ready (Deno, Pyodide,
FFmpeg) and the model files of the need groups in its input. There is one job per group,
so the first group is usable as soon as it is ready. `ensure` is the only place that
creates a group job; the app calls it at start and when a job that needs a group is
submitted. A job that needs a group which is not ready stays queued (see `needs`).
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ports import (
    AppError,
    AppSettings,
    Cancelled,
    CancelToken,
    DownloaderPort,
    JobContext,
    JobInputStore,
    JobStore,
    canonical_digest,
)
from app.runtime import download
from app.runtime.lock import all_lock_items, model_items
from app.runtime.models import (
    ALIGN_EN,
    GROUP_ORDER,
    GROUP_PACKAGES,
    TRANSCRIBE,
    VOICE,
    HfDownload,
    group_bytes,
    group_items,
    prepare_models,
)
from app.runtime.prepare import Hooks, prepare, status
from app.schemas.api import (
    PrepareErrorCode,
    PrepareGroup,
    PrepareGroupId,
    PrepareGroupState,
    RuntimeItem,
    RuntimeItemState,
)
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import Job, JobKind, JobState, Progress, Stage, WaitingOn

log = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
PROGRESS_INTERVAL_S = 0.5
RETRY_DELAYS_S = (5.0, 15.0, 45.0, 120.0)
"""Waits between tries after a lost connection; the last one repeats until it works."""
WAKE_POLL_S = 0.2
_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
_STAGES = {"download": Stage.model_download, "verify": Stage.model_verify}
# Errors that the same input would hit again, so the group stops and says why.
_STOPPING = frozenset(
    {"model_hash_mismatch", "disk_full", "download_blocked", "download_too_large", "model_missing"}
)
_PREPARE_CODES = frozenset(code.value for code in PrepareErrorCode)

LanguageOf = Callable[[Job], str | None]
Pause = Callable[[CancelToken, float, threading.Event], None]


def _new_job_id() -> str:
    """TypeID with a UUIDv7 body, the same shape the job store accepts."""
    raw = bytearray((time.time_ns() // 1_000_000).to_bytes(6, "big"))
    bits = secrets.randbits(74)
    raw += (0x7000 | (bits >> 62)).to_bytes(2, "big")
    raw += (0x8000_0000_0000_0000 | (bits & ((1 << 62) - 1))).to_bytes(8, "big")
    value = int.from_bytes(raw, "big")
    body = "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))
    return f"j_{body}"


def _max_attempts(settings: AppSettings) -> int:
    jobs = getattr(getattr(settings, "app", None), "jobs", None)
    table = getattr(jobs, "max_attempts", None) or {}
    return int(table.get(JobKind.runtime_prepare.value, DEFAULT_MAX_ATTEMPTS))


def pause(cancel: CancelToken, seconds: float, wake: threading.Event) -> None:
    """Wait `seconds`, ending early when `wake` is set and raising when `cancel` is set."""
    deadline = time.monotonic() + seconds
    while True:
        left = deadline - time.monotonic()
        if left <= 0 or wake.is_set():
            wake.clear()
            return
        if cancel.wait(min(WAKE_POLL_S, left)):
            cancel.raise_if_set()


@dataclass(frozen=True)
class _Track:
    """What the running job knows about a group that is not ready."""

    state: PrepareGroupState
    done: int = 0
    total: int = 0
    error_code: str | None = None
    retry_at: datetime | None = None


class RuntimeSetup:
    """Creates the background jobs that prepare runtime files and models, and runs them.

    `enabled` is false for the fixture profile and for a hosted deployment: nothing is
    downloaded there, so no job waits for a group. `downloader` is the app's link
    downloader. Runtime files never go through it: they come from the URLs in the lock and
    are checked against the locked bytes and hash, so the argument only keeps the
    composition root's call shape.
    """

    def __init__(
        self,
        settings: AppSettings,
        downloader: DownloaderPort,
        jobs: JobStore,
        *,
        inputs: JobInputStore | None = None,
        transport: download.Transport | None = None,
        hf: HfDownload | None = None,
        enabled: bool = True,
        language_of: LanguageOf | None = None,
        pause_for: Pause = pause,
    ) -> None:
        self.settings = settings
        self.downloader = downloader
        self.jobs = jobs
        self.inputs = inputs
        self.transport = transport
        self.hf = hf
        self.enabled = enabled
        self._language_of = language_of
        self._pause = pause_for
        self._tracks: dict[str, _Track] = {}
        self._tracks_lock = threading.Lock()
        self._ensure_lock = threading.Lock()
        self._wake = threading.Event()

    # status

    def status(self) -> list[RuntimeItem]:
        return status(self.settings)

    def groups(self, items: Sequence[RuntimeItem] | None = None) -> list[PrepareGroup]:
        """One entry per need group, for `GET /runtime`. `items` is a status already read."""
        states = {item.id: item.state for item in (items or self.status())}
        locked = all_lock_items(self.settings)
        result = []
        with self._tracks_lock:
            tracks = dict(self._tracks)
        for group in GROUP_ORDER:
            total = group_bytes(locked, group)
            if self._ready(group, states):
                result.append(self._group(group, PrepareGroupState.ready, total, total))
                continue
            track = tracks.get(group)
            if track is None:
                result.append(self._group(group, PrepareGroupState.queued, 0, total))
                continue
            result.append(
                self._group(
                    group,
                    track.state,
                    min(track.done, total),
                    total,
                    error_code=track.error_code,
                    retry_at=track.retry_at,
                )
            )
        return result

    @staticmethod
    def _group(
        group: str,
        state: PrepareGroupState,
        done: int,
        total: int,
        *,
        error_code: str | None = None,
        retry_at: datetime | None = None,
    ) -> PrepareGroup:
        return PrepareGroup(
            id=PrepareGroupId(group),
            state=state,
            done=done,
            total=total,
            error_code=PrepareErrorCode(error_code) if error_code in _PREPARE_CODES else None,
            retry_at=retry_at,
        )

    def _ready(self, group: str, states: dict[str, RuntimeItemState]) -> bool:
        names = (
            *(str(item["id"]) for item in group_items(all_lock_items(self.settings), group)),
            *GROUP_PACKAGES.get(group, ()),
        )
        return all(
            states.get(name, RuntimeItemState.ready) is RuntimeItemState.ready for name in names
        )

    def groups_ready(self, groups: Iterable[str]) -> bool:
        """True when every named group has its files. Sizes only, so it is cheap to poll."""
        states = {item.id: item.state for item in self.status()}
        return all(self._ready(group, states) for group in groups)

    def groups_failed(self, groups: Iterable[str]) -> dict[str, str | None]:
        """The groups of `groups` that stopped, each with its error code (None: unexpected)."""
        states = {item.id: item.state for item in self.status()}
        with self._tracks_lock:
            tracks = dict(self._tracks)
        return {
            group: tracks[group].error_code
            for group in groups
            if group in tracks
            and tracks[group].state is PrepareGroupState.failed
            and not self._ready(group, states)
        }

    def needs(self, job: Job) -> list[str]:
        """The groups a job waits for before it may run.

        Generate speaks and times the script, so it needs `voice`, and `align_en` for an
        English video (the Korean aligner model is part of `voice`). A reference needs the
        transcriber. Preview only draws pictures and uses no model, so it waits for none.
        Every other kind needs nothing.
        """
        if not self.enabled:
            return []
        if job.kind is JobKind.reference:
            return [TRANSCRIBE]
        if job.kind is not JobKind.generate:
            return []
        groups = [VOICE]
        if self._language(job) == "en":
            groups.append(ALIGN_EN)
        return groups

    def _language(self, job: Job) -> str | None:
        if self._language_of is None:
            return None
        try:
            return self._language_of(job)
        except AppError:
            # A video that is gone fails by itself when the job runs.
            return None

    # jobs

    def ensure(
        self,
        groups: Sequence[str],
        *,
        owner_id: str = PERSONAL_OWNER_ID,
        retry_failed: bool = False,
    ) -> list[Job]:
        """Queue one prepare job for each group that is not ready and has no open job.

        Returns the jobs that now cover those groups. A group that failed is queued again
        only when `retry_failed` is set, so a job that needs it fails at once instead of
        waiting for another attempt that would end the same way.
        """
        if not self.enabled:
            return []
        covering: list[Job] = []
        with self._ensure_lock:
            states = {item.id: item.state for item in self.status()}
            opened = [
                (job, self._job_groups(job))
                for job in self.jobs.unfinished()
                if job.kind is JobKind.runtime_prepare
                and job.state in (JobState.queued, JobState.running)
            ]
            failed = self.groups_failed(groups)
            for group in groups:
                if self._ready(group, states):
                    continue
                known = next((job for job, covered in opened if group in covered), None)
                if known is not None:
                    covering.append(known)
                    continue
                if group in failed and not retry_failed:
                    continue
                self._forget(group)
                job = self._create([group], owner_id=owner_id, idempotency_key=None)
                opened.append((job, [group]))
                covering.append(job)
        return covering

    def ensure_language(self, language: str) -> list[Job]:
        """Queue what a project of this language needs: the English aligner model for `en`."""
        return self.ensure([ALIGN_EN]) if language == "en" else []

    def submit_prepare(
        self, *, idempotency_key: str | None, owner_id: str = PERSONAL_OWNER_ID
    ) -> Job:
        """Queue every group that is not ready again, or the job for the runtime files.

        Cuts a retry wait, makes a failed group start again, and returns the first job
        that covers the groups that are not ready. With every group ready it returns the
        open job for the runtime files, or queues one.
        """
        self._wake.set()
        jobs = self.ensure(GROUP_ORDER, owner_id=owner_id, retry_failed=True)
        if jobs:
            return jobs[0]
        with self._ensure_lock:
            for job in self.jobs.unfinished():
                if (
                    job.owner_id == owner_id
                    and job.kind is JobKind.runtime_prepare
                    and job.state in (JobState.queued, JobState.running)
                ):
                    return job
            return self._create([], owner_id=owner_id, idempotency_key=idempotency_key)

    def _job_groups(self, job: Job) -> list[str]:
        payload = None if self.inputs is None else self.inputs.load(job.id)
        groups = (payload or {}).get("groups")
        if not isinstance(groups, list):
            return []
        return [group for group in groups if group in GROUP_ORDER]

    def _create(
        self, groups: list[str], *, owner_id: str, idempotency_key: str | None
    ) -> Job:
        job_id = _new_job_id()
        if self.inputs is not None:
            # The input exists before the row, so a worker that claims the job finds it.
            self.inputs.save(job_id, {"groups": groups})
        job = Job(
            id=job_id,
            kind=JobKind.runtime_prepare,
            owner_id=owner_id,
            state=JobState.queued,
            project_id=None,
            video_id=None,
            base_revision=None,
            request_digest=canonical_digest(
                {"kind": JobKind.runtime_prepare.value, "groups": groups}
            ),
            idempotency_key=idempotency_key,
            attempt=1,
            max_attempts=_max_attempts(self.settings),
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
        return self.jobs.create(job)

    # running

    def _track(self, group: str, track: _Track | None) -> None:
        with self._tracks_lock:
            if track is None:
                self._tracks.pop(group, None)
            else:
                self._tracks[group] = track

    def _forget(self, group: str) -> None:
        self._track(group, None)

    def run_job(self, job: Job, ctx: JobContext) -> dict[str, Any]:
        """Body of a `runtime_prepare` job. Failures keep the files a retry can reuse."""

        def runtime_files() -> list[str]:
            return prepare(
                self.settings,
                cancel=ctx.cancel,
                transport=self.transport,
                hooks=self._hooks(ctx, None),
            )

        groups = self._job_groups(job)
        if not groups:
            return {"prepared": runtime_files()}
        ready: list[str] = []
        for index, group in enumerate(groups):
            # The runtime files come first and belong to the first group's try: a lost
            # connection there waits and retries, and a permanent error there fails the
            # group, so a job held for it fails with that error instead of looping.
            ready.extend(self._prepare_group(group, ctx, runtime_files if index == 0 else None))
        return {"prepared": ready}

    def _hooks(self, ctx: JobContext, group: str | None) -> Hooks:
        """Progress and stage hooks of a job; a group's progress also feeds `GET /runtime`."""
        last = [0.0]

        def progress(done: int, total: int) -> None:
            now = time.monotonic()
            if done < total and now - last[0] < PROGRESS_INTERVAL_S:
                return
            last[0] = now
            ctx.progress(done=done, total=total, waiting_on=WaitingOn.download)
            if group is not None:
                self._track(group, _Track(PrepareGroupState.downloading, done, total))

        def stage(name: str) -> AbstractContextManager[None]:
            return ctx.stage(_STAGES[name])

        return Hooks(progress=progress, stage=stage)

    def _prepare_group(
        self, group: str, ctx: JobContext, before: Callable[[], list[str]] | None = None
    ) -> list[str]:
        """Download one group, waiting out lost connections, and record how it ended.

        `before` prepares the runtime files; it runs inside the same retry and failure record.
        """
        items = group_items(model_items(self.settings), group)
        total = group_bytes(all_lock_items(self.settings), group)
        hooks = self._hooks(ctx, group)
        self._track(group, _Track(PrepareGroupState.downloading, 0, total))
        attempt = 0
        try:
            while True:
                try:
                    ids = before() if before is not None else []
                    ids += prepare_models(
                        self.settings.model_dir,
                        items,
                        cancel=ctx.cancel,
                        transport=self.transport,
                        hooks=hooks,
                        hf=self.hf,
                    )
                    break
                except AppError as error:
                    if error.code != "download_failed":
                        raise
                    delay = RETRY_DELAYS_S[min(attempt, len(RETRY_DELAYS_S) - 1)]
                    attempt += 1
                    self._retrying(group, delay, error)
                    self._pause(ctx.cancel, delay, self._wake)
                    self._update(
                        group,
                        state=PrepareGroupState.downloading,
                        error_code=None,
                        retry_at=None,
                    )
            self._check_packages(group)
        except AppError as error:
            code = error.code if error.code in _STOPPING else None
            self._track(group, _Track(PrepareGroupState.failed, 0, total, error_code=code))
            raise
        except BaseException as error:
            if isinstance(error, Cancelled):
                self._forget(group)
            else:
                self._track(group, _Track(PrepareGroupState.failed, 0, total))
            raise
        self._forget(group)
        return ids

    def _retrying(self, group: str, delay: float, error: AppError) -> None:
        log.warning(
            "model download will retry",
            extra={"group": group, "delay_s": delay, "reason": error.detail.get("reason")},
        )
        self._update(
            group,
            state=PrepareGroupState.retrying,
            error_code=error.code,
            retry_at=datetime.now(UTC) + timedelta(seconds=delay),
        )

    def _update(self, group: str, **changes: Any) -> None:
        with self._tracks_lock:
            track = self._tracks.get(group)
            if track is not None:
                self._tracks[group] = replace(track, **changes)

    def _check_packages(self, group: str) -> None:
        """A wheel the group needs is installed by the build, so a missing one is a failure."""
        locked = {str(item["id"]) for item in all_lock_items(self.settings)}
        states = {item.id: item.state for item in self.status()}
        for name in GROUP_PACKAGES.get(group, ()):
            state = states.get(name, RuntimeItemState.ready)
            if name in locked and state is not RuntimeItemState.ready:
                raise AppError(
                    "model_missing", detail={"item": name, "reason": f"package_{state.value}"}
                )


def create(
    settings: AppSettings,
    downloader: DownloaderPort,
    jobs: JobStore,
    **options: Any,
) -> RuntimeSetup:
    return RuntimeSetup(settings, downloader, jobs, **options)
