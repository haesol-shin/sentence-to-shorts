"""Jobs: run context, SQLite job store, queue runner, start recovery and the JSON log.

app.jobs sits beside app.storage in the import layers, so the state.db handle and
the artifact store arrive as injected objects; this module never imports storage.

State changes follow the transition table of CONTRACTS 5.1. Every write is one
short transaction that checks the expected state and attempt, so a late result of
a cancelled or older attempt changes nothing. The light and heavy queues each run
one job at a time. `run_job` is injected; it is the pipeline in the app and a fake
in tests. Child processes stop through the cancel token: the process tool kills the
whole tree when the token is set and returns only after the tree is gone.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import math
import re
import secrets
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Protocol

from app.ports import AppError, ArtifactStore, Cancelled, CancelToken, JobInputStore
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import (
    Checkpoint,
    Job,
    JobError,
    JobErrorCode,
    JobKind,
    JobState,
    Progress,
    Stage,
    StageRecord,
    Usage,
    WaitingOn,
)

LIGHT = "light"
HEAVY = "heavy"
QUEUE_BY_KIND: dict[JobKind, str] = {
    JobKind.draft: LIGHT,
    JobKind.script: LIGHT,
    JobKind.chat: LIGHT,
    JobKind.precheck: LIGHT,
    JobKind.bgm_upload: LIGHT,
    JobKind.preview: HEAVY,
    JobKind.generate: HEAVY,
    JobKind.reference: HEAVY,
    JobKind.style: HEAVY,
    JobKind.template: HEAVY,
    JobKind.bgm_code: HEAVY,
    JobKind.runtime_prepare: HEAVY,
}
RESUMABLE_KINDS = frozenset(
    {JobKind.preview, JobKind.generate, JobKind.runtime_prepare, JobKind.reference}
)
# Errors that the same input would hit again, so a retry is not offered.
PERMANENT_ERRORS = frozenset(
    {
        JobErrorCode.font_missing_glyph,
        JobErrorCode.sandbox_denied,
        JobErrorCode.media_invalid_input,
        JobErrorCode.download_blocked,
        JobErrorCode.download_too_large,
        JobErrorCode.url_not_allowed,
        JobErrorCode.upload_invalid,
        JobErrorCode.model_hash_mismatch,
        JobErrorCode.stale_revision,
        JobErrorCode.unsupported_version,
    }
)
JOB_ID = re.compile(r"^j_[0-7][0-9a-hjkmnp-tv-z]{25}$")
_ENTITY_ID = re.compile(r"^[a-z]{1,2}_[0-7][0-9a-hjkmnp-tv-z]{25}$")
_CHUNK = 1 << 20
REFERENCE_UPLOAD_DIR = "reference-uploads"
REFERENCE_UPLOAD_NAME = re.compile(r"^upload-[A-Za-z0-9_-]{1,64}\.(?:part|src)$")

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class CancelFlag(CancelToken):
    """Thread-safe cancel token shared by a job and its child processes."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def raise_if_set(self) -> None:
        if self._event.is_set():
            raise Cancelled("job cancelled")

    def wait(self, seconds: float) -> bool:
        """Wait for at most the given seconds; True when cancelled during the wait."""
        return self._event.wait(max(0.0, seconds))


ProgressCallback = Callable[[int, int, WaitingOn | None], None]
StageCallback = Callable[[Stage, str], None]
CheckpointCallback = Callable[[Checkpoint], None]
UsageCallback = Callable[[Usage], None]


@dataclass
class LocalJobContext:
    """JobContext implementation used by the local job runner and by tests."""

    cancel_token: CancelToken
    deadline: float
    job_dir: Path
    owner_id: str = PERSONAL_OWNER_ID
    input_payload: dict[str, Any] = field(default_factory=dict)
    on_progress: ProgressCallback | None = None
    on_stage: StageCallback | None = None
    on_checkpoint: CheckpointCallback | None = None
    on_usage: UsageCallback | None = None
    _stages: list[tuple[Stage, str]] = field(default_factory=list)

    @property
    def cancel(self) -> CancelToken:
        return self.cancel_token

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    @property
    def input(self) -> dict[str, Any]:
        return dict(self.input_payload)

    def progress(
        self, *, done: int, total: int, waiting_on: WaitingOn | None = None
    ) -> None:
        if self.on_progress is not None:
            self.on_progress(done, total, waiting_on)

    def _report(self, stage: Stage, state: str) -> None:
        self._stages.append((stage, state))
        if self.on_stage is not None:
            self.on_stage(stage, state)

    @contextmanager
    def stage(self, stage: Stage) -> Iterator[None]:
        self._report(stage, "running")
        try:
            yield
        except Cancelled:
            self._report(stage, "cancelled")
            raise
        except BaseException:
            self._report(stage, "failed")
            raise
        else:
            self._report(stage, "done")

    def checkpoint(self, record: Checkpoint) -> None:
        if self.on_checkpoint is not None:
            self.on_checkpoint(record)

    def record_usage(self, usage: Usage) -> None:
        if self.on_usage is not None:
            self.on_usage(usage)

    @property
    def stages(self) -> list[tuple[Stage, str]]:
        return list(self._stages)


class UnavailableJobSubmitter:
    """Submission seam owned by the jobs lane. Creating a job currently fails loudly."""

    def __init__(self, jobs: Any) -> None:
        self.jobs = jobs

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
    ) -> Job:
        raise NotImplementedError("jobs")


# --- log ------------------------------------------------------------------------------

LOG_FIELDS = (
    "ts",
    "level",
    "event",
    "job_id",
    "attempt",
    "kind",
    "stage",
    "project_id",
    "video_id",
    "scene_id",
    "error_code",
    "http_status",
    "provider",
    "model",
    "effort",
    "input_tokens",
    "output_tokens",
    "cache_hit",
    "duration_ms",
    "retries",
)
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3


class JsonLinesFormatter(logging.Formatter):
    """One JSON object per record with the CONTRACTS 7 fields only.

    The message text, its arguments, exception text and every other attribute are
    dropped, so a caller cannot leak a prompt, a path or a traceback through a log
    call. Values must be scalars; anything else is dropped.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
        }
        for name in LOG_FIELDS[2:]:
            value = record.__dict__.get(name)
            if isinstance(value, Enum):
                value = value.value
            if isinstance(value, (str, int, float, bool)):
                entry[name] = value
        return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def open_app_log(data_dir: Path) -> logging.Handler:
    """`DATA_DIR/log/app.log`: JSON lines, rotated at 5 MB, 3 files kept."""
    path = data_dir / "log" / "app.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8", delay=True
    )
    handler.setFormatter(JsonLinesFormatter())
    return handler


def _job_fields(job: Job, **extra: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "job_id": job.id,
        "attempt": job.attempt,
        "kind": job.kind.value,
        "project_id": job.project_id,
        "video_id": job.video_id,
    }
    fields.update(extra)
    return fields


# --- store ----------------------------------------------------------------------------


class StateDb(Protocol):
    """The state.db handle: a read context and a short IMMEDIATE write transaction."""

    def read(self) -> AbstractContextManager[sqlite3.Connection]: ...

    def write(self) -> AbstractContextManager[sqlite3.Connection]: ...


def _load(conn: sqlite3.Connection, job_id: str) -> Job:
    row = conn.execute("SELECT doc FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise AppError("not_found")
    return Job.model_validate_json(row[0])


def _store(conn: sqlite3.Connection, job: Job, *, state: JobState, attempt: int) -> bool:
    """Write the new document only if the row is still in the expected state and attempt."""
    cursor = conn.execute(
        "UPDATE jobs SET state = ?, attempt = ?, doc = ? "
        "WHERE id = ? AND state = ? AND attempt = ?",
        (job.state.value, job.attempt, job.model_dump_json(), job.id, state.value, attempt),
    )
    return cursor.rowcount == 1


def _next_attempt(job: Job) -> Job:
    """queued again as attempt + 1. Checkpoints and usage stay for reuse and records."""
    return job.model_copy(
        update={
            "state": JobState.queued,
            "attempt": job.attempt + 1,
            "started_at": None,
            "ended_at": None,
            "deadline_at": None,
            "progress": Progress(stage=None, done=0, total=0, waiting_on=WaitingOn.queue),
            "stages": [],
            "result": None,
            "error": None,
            "partial": False,
        }
    )


class SqliteJobStore:
    """JobStore on the `jobs` table: indexed columns plus the full Job document."""

    def __init__(
        self,
        db: StateDb,
        *,
        deadlines_s: Mapping[str, int | None],
        clock: Callable[[], datetime] = _now,
    ) -> None:
        missing = sorted(kind.value for kind in JobKind if kind.value not in deadlines_s)
        if missing:
            raise ValueError(f"no deadline configured for: {', '.join(missing)}")
        self._db = db
        self._deadlines = {kind: deadlines_s[kind.value] for kind in JobKind}
        self._clock = clock

    def _change(
        self,
        job_id: str,
        attempt: int,
        states: frozenset[JobState],
        change: Callable[[Job], Job],
    ) -> Job | None:
        with self._db.write() as conn:
            job = _load(conn, job_id)
            if job.attempt != attempt or job.state not in states:
                return None
            updated = change(job)
            if not _store(conn, updated, state=job.state, attempt=attempt):
                return None
            return updated

    def create(self, job: Job) -> Job:
        if job.state is not JobState.queued:
            raise ValueError("a new job starts queued")
        if not JOB_ID.fullmatch(job.id):
            raise ValueError("job id must use the j_ prefix")
        with self._db.write() as conn:
            conn.execute(
                "INSERT INTO jobs "
                "(id, owner_id, kind, queue, state, attempt, video_id, created_at, doc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.owner_id,
                    job.kind.value,
                    QUEUE_BY_KIND[job.kind],
                    job.state.value,
                    job.attempt,
                    job.video_id,
                    _utc_text(job.created_at),
                    job.model_dump_json(),
                ),
            )
        return job

    def get(self, job_id: str) -> Job:
        with self._db.read() as conn:
            return _load(conn, job_id)

    def claim(self, queue: str) -> Job | None:
        """Atomic queued -> running of the oldest job, only while the queue is idle."""
        if queue not in (LIGHT, HEAVY):
            raise ValueError(f"unknown queue: {queue!r}")
        with self._db.write() as conn:
            busy = conn.execute(
                "SELECT 1 FROM jobs WHERE queue = ? AND state IN ('running', 'cancelling') "
                "LIMIT 1",
                (queue,),
            ).fetchone()
            if busy is not None:
                return None
            row = conn.execute(
                "SELECT doc FROM jobs WHERE queue = ? AND state = 'queued' "
                "ORDER BY created_at, id LIMIT 1",
                (queue,),
            ).fetchone()
            if row is None:
                return None
            job = Job.model_validate_json(row[0])
            now = self._clock()
            limit = self._deadlines[job.kind]
            running = job.model_copy(
                update={
                    "state": JobState.running,
                    "started_at": now,
                    "ended_at": None,
                    "deadline_at": None if limit is None else now + timedelta(seconds=limit),
                    "progress": Progress(stage=None, done=0, total=0, waiting_on=None),
                }
            )
            if not _store(conn, running, state=JobState.queued, attempt=job.attempt):
                return None
            return running

    def progress(self, job_id: str, attempt: int, progress: dict[str, Any]) -> None:
        value = Progress.model_validate(progress)
        self._change(
            job_id,
            attempt,
            frozenset({JobState.running, JobState.cancelling}),
            lambda job: job.model_copy(update={"progress": value}),
        )

    def stage(self, job_id: str, attempt: int, record: dict[str, Any]) -> None:
        """Append a stage record, or update the open record of the same stage."""
        value = StageRecord.model_validate(record)

        def change(job: Job) -> Job:
            stages = list(job.stages)
            for index in range(len(stages) - 1, -1, -1):
                if stages[index].stage is value.stage and stages[index].ended_ms is None:
                    stages[index] = value
                    break
            else:
                stages.append(value)
            return job.model_copy(update={"stages": stages})

        self._change(
            job_id, attempt, frozenset({JobState.running, JobState.cancelling}), change
        )

    def checkpoint(self, job_id: str, attempt: int, cp: dict[str, Any]) -> None:
        """Record a published artifact; one entry per stage, scene and line."""
        value = Checkpoint.model_validate(cp)
        slot = (value.stage, value.scene_id, value.line_id)

        def change(job: Job) -> Job:
            kept = [c for c in job.checkpoints if (c.stage, c.scene_id, c.line_id) != slot]
            return job.model_copy(update={"checkpoints": [*kept, value]})

        self._change(
            job_id, attempt, frozenset({JobState.running, JobState.cancelling}), change
        )

    def keep_checkpoints(self, job_id: str, attempt: int, checkpoints: list[Checkpoint]) -> None:
        """Replace the checkpoints with the ones that passed the artifact check."""
        self._change(
            job_id,
            attempt,
            frozenset({JobState.running}),
            lambda job: job.model_copy(update={"checkpoints": list(checkpoints)}),
        )

    def usage(self, job_id: str, attempt: int, usage: dict[str, Any]) -> None:
        value = Usage.model_validate(usage)
        self._change(
            job_id,
            attempt,
            frozenset({JobState.running, JobState.cancelling}),
            lambda job: job.model_copy(update={"usage": [*job.usage, value]}),
        )

    def finish(
        self,
        job_id: str,
        attempt: int,
        state: str,
        result: dict[str, Any] | None,
        error: JobError | None,
        partial: bool,
    ) -> bool:
        """running -> succeeded or failed for the given attempt. False when stale."""
        target = JobState(state)
        if target not in (JobState.succeeded, JobState.failed):
            raise ValueError("finish ends a job as succeeded or failed")
        if (target is JobState.failed) != (error is not None):
            raise ValueError("a failed job needs an error and a succeeded job none")
        now = self._clock()

        def change(job: Job) -> Job:
            return job.model_copy(
                update={
                    "state": target,
                    "ended_at": now,
                    "result": None if result is None else dict(result),
                    "error": error,
                    "partial": partial,
                    "progress": job.progress.model_copy(update={"waiting_on": None}),
                }
            )

        return self._change(job_id, attempt, frozenset({JobState.running}), change) is not None

    def confirm_cancelled(self, job_id: str, attempt: int) -> bool:
        """cancelling -> cancelled once the attempt's process tree has stopped."""
        now = self._clock()
        return (
            self._change(
                job_id,
                attempt,
                frozenset({JobState.cancelling}),
                lambda job: job.model_copy(
                    update={"state": JobState.cancelled, "ended_at": now}
                ),
            )
            is not None
        )

    def request_cancel(self, job_id: str) -> Job:
        """queued -> cancelled at once; running -> cancelling until the runner confirms."""
        now = self._clock()
        with self._db.write() as conn:
            job = _load(conn, job_id)
            if job.state is JobState.queued:
                updated = job.model_copy(update={"state": JobState.cancelled, "ended_at": now})
            elif job.state is JobState.running:
                updated = job.model_copy(update={"state": JobState.cancelling})
            elif job.state is JobState.cancelling:
                return job
            else:
                raise AppError("job_terminal")
            if not _store(conn, updated, state=job.state, attempt=job.attempt):
                raise RuntimeError("job row changed inside its write transaction")
            return updated

    def requeue(self, job_id: str) -> Job:
        """failed or cancelled -> queued as the next attempt while attempts remain."""
        with self._db.write() as conn:
            job = _load(conn, job_id)
            if (
                job.state not in (JobState.failed, JobState.cancelled)
                or job.attempt >= job.max_attempts
            ):
                raise AppError("job_not_retryable")
            updated = _next_attempt(job)
            if not _store(conn, updated, state=job.state, attempt=job.attempt):
                raise RuntimeError("job row changed inside its write transaction")
            return updated

    def unfinished(self) -> list[Job]:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT doc FROM jobs WHERE state IN ('queued', 'running', 'cancelling') "
                "ORDER BY created_at, id"
            ).fetchall()
        return [Job.model_validate_json(row[0]) for row in rows]

    def retryable_failures(self) -> list[Job]:
        """Failed jobs that still allow another attempt while their input is kept."""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT doc FROM jobs WHERE state = 'failed' ORDER BY created_at, id"
            ).fetchall()
        jobs = [Job.model_validate_json(row[0]) for row in rows]
        return [
            job
            for job in jobs
            if job.error is not None
            and job.error.retryable
            and job.attempt < job.max_attempts
        ]

    def recover(self) -> list[tuple[Job, str]]:
        """Steps 1 to 5 of CONTRACTS 5.3 in one transaction, before any job runs.

        Returns each changed job with `cancelled`, `requeued` or `interrupted`.
        """
        now = self._clock()
        changed: list[tuple[Job, str]] = []
        with self._db.write() as conn:
            rows = conn.execute(
                "SELECT doc FROM jobs WHERE state IN ('running', 'cancelling') "
                "ORDER BY created_at, id"
            ).fetchall()
            for (doc,) in rows:
                job = Job.model_validate_json(doc)
                if job.state is JobState.cancelling:
                    updated = job.model_copy(update={"state": JobState.cancelled, "ended_at": now})
                    outcome = "cancelled"
                elif job.attempt < job.max_attempts and job.kind in RESUMABLE_KINDS:
                    updated = _next_attempt(job)
                    outcome = "requeued"
                else:
                    error = JobError(
                        code=JobErrorCode.interrupted,
                        retryable=job.attempt < job.max_attempts,
                        stage=job.progress.stage,
                        scene_id=None,
                        detail={},
                    )
                    updated = job.model_copy(
                        update={
                            "state": JobState.failed,
                            "ended_at": now,
                            "error": error,
                            "partial": bool(job.checkpoints),
                        }
                    )
                    outcome = "interrupted"
                if _store(conn, updated, state=job.state, attempt=job.attempt):
                    changed.append((updated, outcome))
        return changed


# --- runner ---------------------------------------------------------------------------


RunJob = Callable[[Job, LocalJobContext], Mapping[str, Any] | None]


@dataclass
class _Active:
    job: Job
    flag: CancelFlag
    deadline: float
    deadline_hit: bool = False
    shutdown: bool = False


def _file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _job_error(job: Job, error: BaseException, stage: Stage | None) -> JobError:
    code = JobErrorCode.internal
    detail: dict[str, Any] = {}
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        code = JobErrorCode.disk_full
    elif isinstance(error, AppError) and error.code in JobErrorCode.__members__:
        code = JobErrorCode(error.code)
        detail = {
            key: value
            for key, value in list(error.detail.items())[:8]
            if isinstance(value, (str, int, float, bool)) or value is None
        }
    scene_id = detail.get("scene_id")
    return JobError(
        code=code,
        retryable=code not in PERMANENT_ERRORS and job.attempt < job.max_attempts,
        stage=stage,
        scene_id=scene_id if isinstance(scene_id, str) and _ENTITY_ID.fullmatch(scene_id) else None,
        detail=detail,
    )


def _remove_dir(path: Path) -> None:
    """Delete an app-owned job folder. A symlink is never followed or removed."""
    if path.is_symlink() or not path.is_dir():
        return
    shutil.rmtree(path, ignore_errors=True)


def _keeps_upload(job: Job) -> bool:
    """True while a retry or restart can still read the job's staged reference."""
    if job.state in (JobState.queued, JobState.running, JobState.cancelling):
        return True
    return (
        job.state is JobState.failed
        and job.error is not None
        and job.error.retryable
        and job.attempt < job.max_attempts
    )


def _unlink_upload(path: Path) -> bool:
    """Remove one staged reference file. A symlink is unlinked, never followed."""
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
            return True
    except OSError:
        return False
    return False


class JobRunner:
    """One worker thread per queue and one watcher for cancel requests and deadlines."""

    def __init__(
        self,
        store: SqliteJobStore,
        artifacts: ArtifactStore,
        inputs: JobInputStore,
        run_job: RunJob,
        *,
        cache_dir: Path,
        poll_s: float = 0.5,
        watch_s: float = 0.1,
    ) -> None:
        self._store = store
        self._artifacts = artifacts
        self._inputs = inputs
        self._run_job = run_job
        self._cache_dir = cache_dir
        self._poll_s = poll_s
        self._watch_s = watch_s
        self._active: dict[str, _Active] = {}
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._wake = {LIGHT: threading.Event(), HEAVY: threading.Event()}
        self._threads: list[threading.Thread] = []

    # lifecycle

    def start(self) -> None:
        """Recover state left by the previous process, then start the threads."""
        self.recover()
        self._stopping.clear()
        self._threads = [
            threading.Thread(target=self._work, args=(queue,), name=f"jobs-{queue}", daemon=True)
            for queue in (LIGHT, HEAVY)
        ]
        self._threads.append(
            threading.Thread(target=self._watch, name="jobs-watch", daemon=True)
        )
        for thread in self._threads:
            thread.start()

    def stop(self, timeout_s: float = 10.0) -> None:
        """Stop claiming and cancel running attempts. They stay running for recovery."""
        self._stopping.set()
        with self._lock:
            for active in self._active.values():
                active.shutdown = True
                active.flag.cancel()
        for event in self._wake.values():
            event.set()
        for thread in self._threads:
            thread.join(timeout_s)
        self._threads = []

    def notify(self) -> None:
        """Wake the workers after a job was queued."""
        for event in self._wake.values():
            event.set()

    def recover(self) -> list[tuple[Job, str]]:
        """CONTRACTS 5.3: close interrupted attempts, then delete stale job folders."""
        changed = self._store.recover()
        for job, outcome in changed:
            log.warning(
                "job recovered",
                extra=_job_fields(
                    job,
                    event=f"job_recovered_{outcome}",
                    error_code=None if outcome == "cancelled" else "interrupted",
                ),
            )
        active = {job.id for job in self._store.unfinished()}
        for name in ("j", "r"):
            root = self._cache_dir / name
            if root.is_symlink() or not root.is_dir():
                continue
            for entry in root.iterdir():
                if JOB_ID.fullmatch(entry.name) and entry.name not in active:
                    _remove_dir(entry)
        self.cleanup_reference_uploads()
        return changed

    # reference sources

    def _uploads_dir(self) -> Path:
        return self._cache_dir / REFERENCE_UPLOAD_DIR

    def stage_reference_upload(self) -> tuple[Path, Path]:
        """Names for one new staged upload: a partial file and the final source.

        Staging and cleanup share one folder and one name shape, so a file made
        here is always one the cleanup recognizes. The folder is created here.
        """
        folder = self._uploads_dir()
        if folder.is_symlink():
            raise AppError("internal")
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        token = secrets.token_hex(16)
        part = folder / f"upload-{token}.part"
        source = folder / f"upload-{token}.src"
        if not (REFERENCE_UPLOAD_NAME.fullmatch(part.name)
                and REFERENCE_UPLOAD_NAME.fullmatch(source.name)):
            raise ValueError("staged upload name does not match the cleanup pattern")
        return part, source

    def reference_source_available(self, job_id: str) -> bool:
        """False when a reference upload job has lost its staged source.

        A cancelled job drops its source, so another attempt could not read it.
        Jobs of other kinds and link jobs have no staged source and are available.
        """
        try:
            job = self._store.get(job_id)
            if job.kind is not JobKind.reference:
                return True
            payload = self._inputs.load(job_id)
        except (AppError, OSError, ValueError):
            return True
        value = None if payload is None else payload.get("upload_path")
        return not isinstance(value, str) or Path(value).is_file()

    def _staged_upload(self, job: Job) -> Path | None:
        """The app-owned staged source of a reference job, if its input names one."""
        if job.kind is not JobKind.reference:
            return None
        payload = self._inputs.load(job.id)
        if payload is None:
            raise ValueError("reference job input is unavailable")
        value = payload.get("upload_path")
        if not isinstance(value, str):
            return None
        uploads = self._uploads_dir()
        if uploads.is_symlink():
            return None
        path = Path(value)
        if path.parent != uploads or not REFERENCE_UPLOAD_NAME.fullmatch(path.name):
            return None
        return path

    def discard_reference_upload(self, job_id: str) -> bool:
        """Delete the staged source once no attempt can read it again.

        A queued, running, cancelling or retryable failed job keeps its source.
        True means a file was removed.
        """
        try:
            job = self._store.get(job_id)
        except AppError:
            return False
        if _keeps_upload(job):
            return False
        try:
            path = self._staged_upload(job)
        except (OSError, ValueError):
            log.warning(
                "reference source cleanup deferred",
                extra=_job_fields(job, event="reference_cleanup_deferred"),
            )
            return False
        if path is None:
            return False
        return _unlink_upload(path)

    def cleanup_reference_uploads(self) -> None:
        """Remove staged sources no remaining attempt can read, plus orphan staging files."""
        folder = self._uploads_dir()
        if folder.is_symlink() or not folder.is_dir():
            return
        try:
            entries = list(folder.iterdir())
        except OSError:
            return
        keep: set[Path] = set()
        for job in (*self._store.unfinished(), *self._store.retryable_failures()):
            try:
                path = self._staged_upload(job)
            except (OSError, ValueError):
                log.warning(
                    "reference source cleanup deferred",
                    extra=_job_fields(job, event="reference_cleanup_deferred"),
                )
                return
            if path is not None:
                keep.add(path)
        for entry in entries:
            if REFERENCE_UPLOAD_NAME.fullmatch(entry.name) and entry not in keep:
                _unlink_upload(entry)

    # execution

    def run_once(self, queue: str) -> Job | None:
        """Claim and run one job of the queue in this thread. None when nothing ran."""
        job = self._store.claim(queue)
        if job is None:
            return None
        self._execute(job)
        return self._store.get(job.id)

    def _work(self, queue: str) -> None:
        wake = self._wake[queue]
        while not self._stopping.is_set():
            if self.run_once(queue) is None:
                wake.wait(self._poll_s)
                wake.clear()

    def _watch(self) -> None:
        while not self._stopping.wait(self._watch_s):
            with self._lock:
                running = list(self._active.values())
            for active in running:
                if active.flag.is_set():
                    continue
                if time.monotonic() >= active.deadline:
                    active.deadline_hit = True
                    active.flag.cancel()
                elif self._store.get(active.job.id).state is JobState.cancelling:
                    active.flag.cancel()

    def _intact(self, checkpoint: Checkpoint) -> bool:
        try:
            path = self._artifacts.path(checkpoint.artifact_id)
        except AppError:
            return False
        if path.is_symlink() or not path.is_file():
            return False
        return _file_sha256(path) == checkpoint.digest

    def _execute(self, claimed: Job) -> None:
        started = time.monotonic()
        limit = (
            None
            if claimed.deadline_at is None or claimed.started_at is None
            else (claimed.deadline_at - claimed.started_at).total_seconds()
        )
        flag = CancelFlag()
        active = _Active(
            job=claimed, flag=flag, deadline=math.inf if limit is None else started + limit
        )
        with self._lock:
            self._active[claimed.id] = active
        log.info("job started", extra=_job_fields(claimed, event="job_started"))
        try:
            try:
                kept = [cp for cp in claimed.checkpoints if self._intact(cp)]
            except OSError as error:
                # Reading a checkpoint file is preparation of this attempt; a store
                # error is not caught here and reaches the caller.
                duration_ms = int((time.monotonic() - started) * 1000)
                self._close(claimed, active, None, error, None, False, duration_ms)
                return
            if len(kept) != len(claimed.checkpoints):
                self._store.keep_checkpoints(claimed.id, claimed.attempt, kept)
                log.warning(
                    "checkpoint dropped",
                    extra=_job_fields(claimed, event="job_checkpoint_dropped"),
                )
            job = claimed.model_copy(update={"checkpoints": kept})
            self._run(job, active, started, has_checkpoints=bool(kept))
        finally:
            with self._lock:
                self._active.pop(claimed.id, None)
            _remove_dir(self._cache_dir / "j" / claimed.id)
            _remove_dir(self._cache_dir / "r" / claimed.id)
            if claimed.kind is JobKind.reference:
                self.discard_reference_upload(claimed.id)

    def _run(self, job: Job, active: _Active, started: float, *, has_checkpoints: bool) -> None:
        store = self._store
        current: list[Stage | None] = [None]
        opened: dict[Stage, int] = {}
        recorded = [has_checkpoints]

        def elapsed_ms() -> int:
            return int((time.monotonic() - started) * 1000)

        def on_progress(done: int, total: int, waiting_on: WaitingOn | None) -> None:
            store.progress(
                job.id,
                job.attempt,
                {"stage": current[0], "done": done, "total": total, "waiting_on": waiting_on},
            )

        def on_stage(stage: Stage, state: str) -> None:
            current[0] = stage
            if state == "running":
                opened[stage] = elapsed_ms()
            start_ms = opened.get(stage, elapsed_ms())
            store.stage(
                job.id,
                job.attempt,
                {
                    "stage": stage,
                    "state": state,
                    "started_ms": start_ms,
                    "ended_ms": None if state == "running" else elapsed_ms(),
                    "cache_hits": 0,
                    "rebuilt_scene_ids": [],
                },
            )

        def on_checkpoint(record: Checkpoint) -> None:
            if not self._intact(record):
                raise ValueError("checkpoint artifact is missing or differs from its digest")
            store.checkpoint(job.id, job.attempt, record.model_dump(mode="json"))
            recorded[0] = True

        def on_usage(usage: Usage) -> None:
            store.usage(job.id, job.attempt, usage.model_dump(mode="json"))
            log.info(
                "llm usage",
                extra=_job_fields(
                    job,
                    event="job_usage",
                    stage=usage.stage.value,
                    provider=usage.provider,
                    model=usage.model,
                    effort=None if usage.effort is None else usage.effort.value,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_hit=None
                    if usage.cache_read_tokens is None
                    else usage.cache_read_tokens > 0,
                    duration_ms=usage.wall_ms,
                    retries=usage.retries,
                ),
            )

        result: Mapping[str, Any] | None = None
        failure: BaseException | None = None
        try:
            # Preparing the context belongs to the attempt: a full disk while creating
            # the job folder fails the job instead of the queue worker.
            ctx = LocalJobContext(
                cancel_token=active.flag,
                deadline=active.deadline,
                job_dir=self._artifacts.job_dir(job.id),
                owner_id=job.owner_id,
                input_payload=self._inputs.load(job.id) or {},
                on_progress=on_progress,
                on_stage=on_stage,
                on_checkpoint=on_checkpoint,
                on_usage=on_usage,
            )
            result = self._run_job(job, ctx)
        except Exception as error:  # noqa: BLE001 - every failure becomes a job error
            failure = error
        self._close(job, active, result, failure, current[0], recorded[0], elapsed_ms())

    def _close(
        self,
        job: Job,
        active: _Active,
        result: Mapping[str, Any] | None,
        failure: BaseException | None,
        stage: Stage | None,
        partial: bool,
        duration_ms: int,
    ) -> None:
        if active.shutdown:
            log.info(
                "job left for recovery",
                extra=_job_fields(job, event="job_shutdown", duration_ms=duration_ms),
            )
            return
        # The watcher ticks; a job that returns between ticks past its deadline is
        # still a timeout, so the deadline is checked again here.
        if active.deadline_hit or time.monotonic() >= active.deadline:
            error: JobError | None = JobError(
                code=JobErrorCode.deadline_exceeded,
                retryable=job.attempt < job.max_attempts,
                stage=stage,
                scene_id=None,
                detail={},
            )
        elif failure is not None:
            error = _job_error(job, failure, stage)
        else:
            error = None
        if error is None:
            done = self._store.finish(
                job.id, job.attempt, JobState.succeeded.value, dict(result or {}), None, False
            )
            event = "job_succeeded"
        else:
            done = self._store.finish(
                job.id, job.attempt, JobState.failed.value, None, error, partial
            )
            event = "job_failed"
        if not done and self._store.confirm_cancelled(job.id, job.attempt):
            event, error = "job_cancelled", None
        elif not done:
            event, error = "job_result_discarded", None
        log.info(
            "job closed",
            extra=_job_fields(
                job,
                event=event,
                stage=None if stage is None else stage.value,
                error_code=None if error is None else error.code.value,
                duration_ms=duration_ms,
            ),
        )


__all__ = [
    "HEAVY",
    "LIGHT",
    "LOG_FIELDS",
    "QUEUE_BY_KIND",
    "RESUMABLE_KINDS",
    "CancelFlag",
    "JobRunner",
    "JsonLinesFormatter",
    "LocalJobContext",
    "RunJob",
    "SqliteJobStore",
    "UnavailableJobSubmitter",
    "open_app_log",
]
