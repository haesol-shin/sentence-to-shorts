"""Job store, runner and artifact store on one isolated state.db."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.jobs import JobRunner, RunJob, SqliteJobStore
from app.schemas.artifact import Artifact, ArtifactKind
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import Job, JobKind, JobState, Progress, WaitingOn
from app.storage.artifacts import FileArtifactStore
from app.storage.job_inputs import LocalJobInputStore
from app.storage.paths import Layout
from app.storage.projects import new_typeid
from app.storage.sqlite import Database

DEADLINES: dict[str, int | None] = {kind.value: 60 for kind in JobKind}
DEADLINES[JobKind.runtime_prepare.value] = None


@dataclass
class Env:
    layout: Layout
    db: Database
    jobs: SqliteJobStore
    artifacts: FileArtifactStore
    inputs: LocalJobInputStore

    def runner(self, run_job: RunJob) -> JobRunner:
        return JobRunner(
            self.jobs,
            self.artifacts,
            self.inputs,
            run_job,
            cache_dir=self.layout.cache,
            bgm_staging_dir=self.layout.data / "staging" / "bgm",
            poll_s=0.02,
            watch_s=0.02,
        )

    def close(self) -> None:
        self.db.close()


def open_env(root: Path, deadlines: dict[str, int | None] | None = None) -> Env:
    layout = Layout(data=root / "data", cache=root / "cache")
    db = Database.open(layout.state_db)
    return Env(
        layout=layout,
        db=db,
        jobs=SqliteJobStore(db, deadlines_s=deadlines or DEADLINES),
        artifacts=FileArtifactStore(db, layout),
        inputs=LocalJobInputStore(layout.data / "j"),
    )


def new_job(
    kind: JobKind = JobKind.generate, *, max_attempts: int = 3, video_id: str | None = None
) -> Job:
    return Job(
        id=new_typeid("j"),
        kind=kind,
        owner_id=PERSONAL_OWNER_ID,
        state=JobState.queued,
        project_id=None,
        video_id=video_id,
        base_revision=None,
        request_digest="0" * 64,
        idempotency_key=None,
        attempt=1,
        max_attempts=max_attempts,
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


def publish_clip(
    artifacts: FileArtifactStore, staging: Path, data: bytes, job_id: str
) -> Artifact:
    staging.mkdir(parents=True, exist_ok=True)
    tmp = staging / f"{hashlib.sha256(data).hexdigest()[:12]}.mp4"
    tmp.write_bytes(data)
    return artifacts.publish(
        PERSONAL_OWNER_ID,
        ArtifactKind.clip_mp4,
        hashlib.sha256(data).hexdigest(),
        tmp,
        {},
        job_id,
    )


def wait_until(check: Callable[[], bool], timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()
