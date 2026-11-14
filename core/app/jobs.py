"""Cancellation and the job context handed to services.

The queue and persistence live in app.storage; this module owns only the run
context so services never import a storage implementation.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from app.ports import Cancelled, CancelToken
from app.schemas.job import Checkpoint, Job, JobKind, Stage, Usage, WaitingOn


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

    @contextmanager
    def stage(self, stage: Stage) -> Iterator[None]:
        self._stages.append((stage, "running"))
        if self.on_stage is not None:
            self.on_stage(stage, "running")
        try:
            yield
        except BaseException:
            self._stages.append((stage, "failed"))
            if self.on_stage is not None:
                self.on_stage(stage, "failed")
            raise
        else:
            self._stages.append((stage, "done"))
            if self.on_stage is not None:
                self.on_stage(stage, "done")

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
        project_id: str | None,
        video_id: str | None,
        base_revision: int | None,
        request_digest: str,
        input: Mapping[str, Any],
        idempotency_key: str | None,
    ) -> Job:
        raise NotImplementedError("jobs")
