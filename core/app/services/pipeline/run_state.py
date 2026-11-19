"""Per-run bookkeeping: gates, cache reuse, publication and stage records.

A step publishes an artifact, keeps it for the revision it was built for, then
writes its checkpoint. The published artifact and the checkpoint are separate
writes on purpose: a crash between them leaves a reusable cache entry, never a
checkpoint that names a missing file.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ports import AppError, ArtifactStore, Cancelled, JobContext
from app.schemas.artifact import Artifact, ArtifactKind
from app.schemas.job import Checkpoint, Job, Stage
from app.schemas.video import Video
from app.services.pipeline.types import Services


def elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def check_alive(ctx: JobContext) -> None:
    """Refuse cancelled or timed-out work before it starts."""
    ctx.cancel.raise_if_set()
    if time.monotonic() >= ctx.deadline:
        raise AppError("deadline_exceeded")


def check_context(video: Video, ctx: JobContext, services: Services) -> None:
    """Refuse cancelled, timed-out or no-longer-current work before it starts."""
    check_alive(ctx)
    head = services.project.view(video.id)
    if head.revision != video.revision:
        raise AppError("stale_revision", detail={"current_revision": head.revision})


@dataclass
class StageLog:
    stage: Stage
    started_ms: int
    ended_ms: int | None = None
    cache_hits: int = 0
    rebuilt_scene_ids: list[str] = field(default_factory=list)
    state: str = "running"
    worked: bool = False

    def hit(self) -> None:
        self.cache_hits += 1

    def rebuilt(self, scene_id: str) -> None:
        self.worked = True
        if scene_id not in self.rebuilt_scene_ids:
            self.rebuilt_scene_ids.append(scene_id)

    def built_artifact(self) -> None:
        self.worked = True

    def record(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "state": self.state,
            "started_ms": self.started_ms,
            "ended_ms": self.ended_ms,
            "cache_hits": self.cache_hits,
            "rebuilt_scene_ids": list(self.rebuilt_scene_ids),
        }


class RunState:
    """One job attempt against one source revision.

    ``video.revision`` is the revision every artifact is held for. A step calls
    ``guard`` before and after work that could be expensive, so a revision
    change cannot publish a result against the newer head.
    """

    def __init__(
        self, job: Job, ctx: JobContext, services: Services, video: Video
    ) -> None:
        self.job = job
        self.ctx = ctx
        self.services = services
        self.video = video
        self.revision = video.revision
        self.holder = f"rev:{video.id}:{video.revision}"
        self.stages: list[StageLog] = []
        self.artifact_ids: list[str] = []
        self.artifacts: dict[str, Any] = {
            "tts": {},
            "timing": {},
            "parts": {},
            "layer": {},
            "still": {},
            "clip": {},
            "mix": None,
            "final": None,
            "srt": None,
        }
        self.cache_hits = 0
        self.rebuilt_scene_ids: list[str] = []
        self._started = time.monotonic()
        self._kept: set[str] = set()

    @property
    def store(self) -> ArtifactStore:
        return self.services.artifact_store

    @property
    def elapsed(self) -> int:
        return elapsed_ms(self._started)

    def guard(self) -> None:
        check_context(self.video, self.ctx, self.services)

    @contextmanager
    def stage(self, stage: Stage) -> Iterator[StageLog]:
        log = StageLog(stage=stage, started_ms=self.elapsed)
        self.stages.append(log)
        try:
            with self.ctx.stage(stage):
                yield log
        except Cancelled:
            log.state = "cancelled"
            raise
        except BaseException:
            log.state = "failed"
            raise
        else:
            log.state = "skipped" if not log.worked else "done"
        finally:
            log.ended_ms = self.elapsed

    def find(
        self,
        cache_key: str | None,
        *,
        stage: StageLog,
        scene_id: str | None = None,
        line_id: str | None = None,
        slot: str | None = None,
    ) -> Artifact | None:
        """A verified cache entry, kept and checkpointed for this attempt.

        The checkpoint makes a reused result count as preserved work when a later
        step of the same attempt fails. ``None`` on a miss.
        """
        if cache_key is None:
            return None
        self.guard()
        artifact = self.store.find(self.job.owner_id, cache_key)
        if artifact is None:
            return None
        self._keep(artifact)
        self.ctx.checkpoint(
            Checkpoint(
                stage=stage.stage,
                scene_id=scene_id,
                line_id=line_id,
                artifact_id=artifact.id,
                digest=artifact.digest,
            )
        )
        stage.hit()
        self.cache_hits += 1
        self.succeeded(artifact.kind, cache_key, scene_id, line_id)
        self.record(scene_id=scene_id, line_id=line_id, slot=slot, artifact=artifact)
        return artifact

    def publish(
        self,
        kind: ArtifactKind,
        cache_key: str,
        staged: Path,
        *,
        stage: Stage,
        scene_id: str | None = None,
        line_id: str | None = None,
        slot: str | None = None,
        media: dict[str, Any] | None = None,
    ) -> Artifact:
        """Publish a verified job-folder file, keep it, then checkpoint it."""
        self.guard()
        artifact = self.store.publish(
            self.job.owner_id, kind, cache_key, staged, media or {}, self.job.id
        )
        self._keep(artifact)
        self.ctx.checkpoint(
            Checkpoint(
                stage=stage,
                scene_id=scene_id,
                line_id=line_id,
                artifact_id=artifact.id,
                digest=artifact.digest,
            )
        )
        self.succeeded(kind, cache_key, scene_id, line_id)
        self.record(scene_id=scene_id, line_id=line_id, slot=slot, artifact=artifact)
        return artifact

    def record(
        self,
        *,
        scene_id: str | None,
        line_id: str | None,
        slot: str | None,
        artifact: Artifact,
    ) -> None:
        if artifact.id not in self.artifact_ids:
            self.artifact_ids.append(artifact.id)
        kind = artifact.kind
        if kind is ArtifactKind.tts_wav and line_id is not None:
            self.artifacts["tts"][line_id] = artifact.id
        elif kind is ArtifactKind.timing_json and scene_id is not None:
            self.artifacts["timing"][scene_id] = artifact.id
        elif kind is ArtifactKind.part_png and scene_id is not None and slot is not None:
            self.artifacts["parts"].setdefault(scene_id, {})[slot] = artifact.id
        elif kind is ArtifactKind.layer_png and scene_id is not None:
            self.artifacts["layer"][scene_id] = artifact.id
        elif kind is ArtifactKind.still_png and scene_id is not None:
            self.artifacts["still"][scene_id] = artifact.id
        elif kind is ArtifactKind.clip_mp4 and scene_id is not None:
            self.artifacts["clip"][scene_id] = artifact.id
        elif kind is ArtifactKind.mix_wav:
            self.artifacts["mix"] = artifact.id
        elif kind is ArtifactKind.final_mp4:
            self.artifacts["final"] = artifact.id
        elif kind is ArtifactKind.srt:
            self.artifacts["srt"] = artifact.id

    def rebuilt(self, scene_id: str) -> None:
        if scene_id not in self.rebuilt_scene_ids:
            self.rebuilt_scene_ids.append(scene_id)

    def rebase(self, video: Video) -> None:
        """Move to the revision created after the artifacts were prepared.

        Preview can prepare scene visuals in memory, render with those keys and
        only then persist the new revision, so a failed attempt leaves the head
        and the retry input untouched.
        """
        if video.id != self.video.id:
            raise AppError("invalid_combination", detail={"reason": "video"})
        self.video = video
        self.revision = video.revision
        holder = f"rev:{video.id}:{video.revision}"
        if holder == self.holder:
            return
        self.holder = holder
        if self._kept:
            self.store.hold(sorted(self._kept), self.holder)

    def succeeded(
        self,
        kind: ArtifactKind,
        cache_key: str,
        scene_id: str | None,
        line_id: str | None,
    ) -> None:
        self.services.build_states.pop(
            self._build_key(kind, scene_id, line_id), None
        )
        self.services.previous_keys[
            (self.video.id, kind.value, scene_id, line_id)
        ] = cache_key

    def failed_state(
        self,
        kind: ArtifactKind,
        cache_key: str,
        scene_id: str | None,
        line_id: str | None,
        code: str,
    ) -> None:
        """Move a failed build observation to the key the next lookup will use."""
        self.services.build_states[self._build_key(kind, scene_id, line_id)] = {
            "state": "failed",
            "cache_key": cache_key,
            "error_code": code,
        }

    @contextmanager
    def building(
        self,
        kind: ArtifactKind,
        cache_key: str,
        scene_id: str | None = None,
        line_id: str | None = None,
    ) -> Iterator[None]:
        with self.building_many([(kind, cache_key, scene_id, line_id)]):
            yield

    @contextmanager
    def building_many(
        self,
        items: list[tuple[ArtifactKind, str, str | None, str | None]],
    ) -> Iterator[None]:
        """Mark each artifact as building for the derived view; clear or fail after."""
        keys = [
            (
                self._build_key(kind, scene_id, line_id),
                kind,
                cache_key,
                scene_id,
                line_id,
            )
            for kind, cache_key, scene_id, line_id in items
        ]
        for key, kind, cache_key, _, _ in keys:
            self.services.build_states[key] = {
                "state": "building",
                "cache_key": cache_key,
                "error_code": None,
            }
        try:
            yield
        except Cancelled:
            for key, _, _, _, _ in keys:
                self.services.build_states.pop(key, None)
            raise
        except BaseException as error:
            code = error.code if isinstance(error, AppError) else "internal"
            for key, _, cache_key, _, _ in keys:
                self.services.build_states[key] = {
                    "state": "failed",
                    "cache_key": cache_key,
                    "error_code": code,
                }
            raise

    def _build_key(
        self, kind: ArtifactKind, scene_id: str | None, line_id: str | None
    ) -> tuple[str, int, str, str | None, str | None]:
        return (self.video.id, self.revision, kind.value, scene_id, line_id)

    def staged(self, cache_key: str, suffix: str) -> Path:
        directory = self.ctx.job_dir / "pipeline"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{cache_key}{suffix}"

    def result(self) -> dict[str, object]:
        self.guard()
        return {
            "video_id": self.video.id,
            "revision": self.revision,
            "artifact_ids": list(self.artifact_ids),
            "artifacts": self.artifacts,
            "rebuilt_scene_ids": list(self.rebuilt_scene_ids),
            "cache_hits": self.cache_hits,
            "stages": [log.record() for log in self.stages],
        }

    def _keep(self, artifact: Artifact) -> None:
        if artifact.id in self._kept:
            return
        self.store.hold([artifact.id], self.holder)
        self._kept.add(artifact.id)


__all__ = ["RunState", "StageLog", "check_alive", "check_context", "elapsed_ms"]
