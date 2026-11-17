"""The runtime setup service: status for `GET /runtime` and the `runtime_prepare` job."""

from __future__ import annotations

import secrets
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from app.ports import AppSettings, DownloaderPort, JobContext, JobStore, canonical_digest
from app.runtime import download
from app.runtime.prepare import Hooks, prepare, status
from app.schemas.api import RuntimeItem
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import Job, JobKind, JobState, Progress, Stage, WaitingOn

DEFAULT_MAX_ATTEMPTS = 3
PROGRESS_INTERVAL_S = 0.5
_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
_STAGES = {"download": Stage.model_download, "verify": Stage.model_verify}
_REQUEST_DIGEST = canonical_digest({"kind": JobKind.runtime_prepare.value})


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


class RuntimeSetup:
    """Creates the background job that prepares missing runtime files and runs it.

    `downloader` is the app's link downloader. Runtime files never go through it: they
    come from the URLs in the lock and are checked against the locked bytes and hash, so
    the argument only keeps the composition root's call shape.
    """

    def __init__(
        self,
        settings: AppSettings,
        downloader: DownloaderPort,
        jobs: JobStore,
        *,
        transport: download.Transport | None = None,
    ) -> None:
        self.settings = settings
        self.downloader = downloader
        self.jobs = jobs
        self.transport = transport

    def status(self) -> list[RuntimeItem]:
        return status(self.settings)

    def submit_prepare(
        self, *, idempotency_key: str | None, owner_id: str = PERSONAL_OWNER_ID
    ) -> Job:
        """Queue the prepare job, or return the one that is already queued or running."""
        for job in self.jobs.unfinished():
            if (
                job.owner_id == owner_id
                and job.kind is JobKind.runtime_prepare
                and job.state in (JobState.queued, JobState.running)
            ):
                return job
        attempts = _max_attempts(self.settings)
        job = Job(
            id=_new_job_id(),
            kind=JobKind.runtime_prepare,
            owner_id=owner_id,
            state=JobState.queued,
            project_id=None,
            video_id=None,
            base_revision=None,
            request_digest=_REQUEST_DIGEST,
            idempotency_key=idempotency_key,
            attempt=1,
            max_attempts=attempts,
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

    def run_job(self, job: Job, ctx: JobContext) -> dict[str, Any]:
        """Body of a `runtime_prepare` job. Failures keep the files a retry can reuse."""
        last = [0.0]

        def progress(done: int, total: int) -> None:
            now = time.monotonic()
            if done < total and now - last[0] < PROGRESS_INTERVAL_S:
                return
            last[0] = now
            ctx.progress(done=done, total=total, waiting_on=WaitingOn.download)

        def stage(name: str) -> AbstractContextManager[None]:
            return ctx.stage(_STAGES[name])

        ready = prepare(
            self.settings,
            cancel=ctx.cancel,
            transport=self.transport,
            hooks=Hooks(progress=progress, stage=stage),
        )
        return {"prepared": ready}


def create(
    settings: AppSettings,
    downloader: DownloaderPort,
    jobs: JobStore,
) -> RuntimeSetup:
    return RuntimeSetup(settings, downloader, jobs)
