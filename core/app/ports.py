"""Ports between services and the outside world.

Only the standard library and the contract schemas may be imported here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO, Literal, Protocol

from app.schemas.api import ActivitySpan, CatalogItem, Metrics
from app.schemas.artifact import Artifact, ArtifactKind
from app.schemas.change import ChangePlan, Op
from app.schemas.common import ContractModel, EntityId, PinnedRef
from app.schemas.job import Checkpoint, Job, JobError, JobKind, Stage, Usage, WaitingOn
from app.schemas.preset import Preset
from app.schemas.project import Project
from app.schemas.sandbox_io import SandboxRequest
from app.schemas.scene import Scene
from app.schemas.video import RevisionInfo, Video
from app.schemas.voice_manifest import VoiceManifest


class Cancelled(Exception):
    """Raised when a cancel token is set."""


class UnknownCatalogId(Exception):
    """Raised when a catalog id or pinned revision is not registered."""


def _check_numbers(value: Any) -> None:
    if isinstance(value, float):
        raise TypeError("canonical JSON must not contain floats")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            _check_numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_numbers(item)


def canonical_json(value: Any) -> bytes:
    """Canonical JSON: UTF-8, sorted keys, no whitespace, integers only."""
    _check_numbers(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class AppError(Exception):
    """External failure translated by an adapter into an app or job error code."""

    def __init__(self, code: str, *, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = dict(detail or {})


class AppSettings(Protocol):
    """Settings surface shared with factories. Concrete settings live in app.settings."""

    profile: str
    deployment: str
    app_version: str
    port: int
    lan: bool
    bind_host: str
    data_dir: Path
    cache_dir: Path
    model_dir: Path
    runtime_dir: Path


class CancelToken(Protocol):
    def is_set(self) -> bool: ...

    def raise_if_set(self) -> None: ...

    def wait(self, seconds: float) -> bool:
        """Return True when cancelled during the wait."""


@dataclass(frozen=True)
class LlmPart:
    kind: Literal["text", "png"]
    text: str | None = None
    png: bytes | None = None


class LlmTask(StrEnum):
    draft = "draft"
    script = "script"
    split = "split"
    scene_data = "scene_data"
    chat = "chat"
    scene_rewrite = "scene_rewrite"
    precheck = "precheck"
    reference_vision = "reference_vision"
    style_code = "style_code"
    template_code = "template_code"
    bgm_code = "bgm_code"


@dataclass(frozen=True)
class LlmRequest:
    task: LlmTask
    route: str
    system: str
    parts: list[LlmPart]
    output_schema: dict[str, Any] | None
    max_output_tokens: int


@dataclass(frozen=True)
class LlmResult:
    text: str
    parsed: dict[str, Any] | None
    usage: Usage


class LlmPort(Protocol):
    def complete(self, req: LlmRequest, *, cancel: CancelToken, deadline: float) -> LlmResult: ...

    def auth_state(self) -> Literal["ok", "missing", "expired", "unknown"]: ...


@dataclass(frozen=True)
class TtsEngineInfo:
    engine_id: str
    runtime_digest: str
    sample_rate: int
    languages: tuple[str, ...]


@dataclass(frozen=True)
class SynthResult:
    wav_path: Path
    duration_ms: int


class TtsPort(Protocol):
    def info(self) -> TtsEngineInfo: ...

    def ready(self) -> list[str]: ...

    def synthesize(
        self,
        text: str,
        language: str,
        voice: VoiceManifest,
        *,
        out_dir: Path,
        cancel: CancelToken,
    ) -> SynthResult: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class PhraseSpan:
    start_char: int
    end_char: int
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AlignResult:
    phrases: list[PhraseSpan] | None
    failure: (
        Literal[
            "align_failed",
            "align_low_confidence",
            "align_missing_words",
            "align_unavailable",
        ]
        | None
    )


class AlignerPort(Protocol):
    def align(
        self,
        wav: Path,
        speech_text: str,
        display_text: str,
        language: str,
        *,
        cancel: CancelToken,
    ) -> AlignResult: ...


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int
    text: str


class TranscriberPort(Protocol):
    def transcribe(
        self, wav: Path, language: str | None, *, cancel: CancelToken
    ) -> list[Segment]: ...


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    fps: int | None = None
    sample_rate: int | None = None
    channels: int | None = None


@dataclass(frozen=True)
class MixItem:
    path: Path
    start_ms: int
    gain_db_x10: int = 0
    ducking_db_x10: int = 0


@dataclass(frozen=True)
class MixPlan:
    items: list[MixItem]
    duration_ms: int
    loudness_lufs_x10: int = -160
    true_peak_dbtp_x10: int = -10
    sample_rate: int = 44100


class MediaPort(Protocol):
    def encode_frames(
        self,
        frames: Iterable[bytes],
        *,
        width: int,
        height: int,
        fps: int,
        out: Path,
        cancel: CancelToken,
    ) -> MediaInfo: ...

    def mix(self, plan: MixPlan, *, out: Path, cancel: CancelToken) -> MediaInfo: ...

    def mux_concat(
        self, clips: list[Path], audio: Path, *, out: Path, cancel: CancelToken
    ) -> MediaInfo: ...

    def decode_audio(
        self,
        src: Path,
        *,
        out: Path,
        sample_rate: int,
        channels: int,
        max_ms: int,
        cancel: CancelToken,
    ) -> MediaInfo: ...

    def extract_frames(
        self,
        src: Path,
        *,
        every_ms: int,
        max_frames: int,
        max_side: int,
        out_dir: Path,
        cancel: CancelToken,
    ) -> list[Path]: ...

    def extract_audio(
        self, src: Path, *, out: Path, max_ms: int, cancel: CancelToken
    ) -> MediaInfo: ...

    def probe(self, src: Path) -> MediaInfo: ...


@dataclass(frozen=True)
class ValidatedOutput:
    files: dict[str, bytes]
    meta: dict[str, Any]


class SandboxPort(Protocol):
    def run(self, request: SandboxRequest, *, cancel: CancelToken) -> ValidatedOutput: ...

    def runtime_digest(self) -> str: ...


class DownloaderPort(Protocol):
    def fetch(
        self,
        url: str,
        *,
        out_dir: Path,
        max_bytes: int,
        max_ms: int,
        cancel: CancelToken,
    ) -> Path: ...


class ProjectStore(Protocol):
    def new_id(self, prefix: str) -> str: ...

    def put_project(self, project: Project) -> None: ...

    def get_project(self, project_id: str) -> Project: ...

    def list_projects(self, owner_id: str) -> list[Project]: ...

    def delete_project(self, project_id: str) -> None: ...

    def append_revision(self, video: Video) -> Video:
        """Append immutable content; register new videos in the project in the same write."""
        ...

    def get_video(self, video_id: str, revision: int | None = None) -> Video: ...

    def list_revisions(self, video_id: str) -> list[RevisionInfo]: ...

    def put_change(self, plan: ChangePlan) -> None: ...

    def get_change(self, change_id: str) -> ChangePlan: ...

    def list_changes(self, video_id: str) -> list[ChangePlan]: ...

    def put_preset(self, preset: Preset) -> None: ...

    def list_presets(self, project_id: str) -> list[Preset]: ...

    def add_activity(self, video_id: str, spans: list[ActivitySpan]) -> None: ...

    def metrics(self, video_id: str) -> Metrics: ...


class ArtifactStore(Protocol):
    def find(self, cache_key: str) -> Artifact | None: ...

    def publish(
        self,
        kind: ArtifactKind,
        cache_key: str,
        tmp: Path,
        media: dict[str, Any],
        job_id: str | None,
    ) -> Artifact: ...

    def path(self, artifact_id: str) -> Path: ...

    def download_path(self, video_id: str, kind: str) -> Path: ...

    def job_dir(self, job_id: str) -> Path: ...

    def hold(self, artifact_ids: list[str], holder: str) -> None: ...

    def release(self, holder: str) -> None: ...

    def sweep(self) -> int: ...


class JobStore(Protocol):
    def create(self, job: Job) -> Job: ...

    def get(self, job_id: str) -> Job: ...

    def claim(self, queue: str) -> Job | None: ...

    def progress(self, job_id: str, attempt: int, progress: dict[str, Any]) -> None: ...

    def stage(self, job_id: str, attempt: int, record: dict[str, Any]) -> None: ...

    def checkpoint(self, job_id: str, attempt: int, cp: dict[str, Any]) -> None: ...

    def usage(self, job_id: str, attempt: int, usage: dict[str, Any]) -> None: ...

    def finish(
        self,
        job_id: str,
        attempt: int,
        state: str,
        result: dict[str, Any] | None,
        error: JobError | None,
        partial: bool,
    ) -> bool: ...

    def request_cancel(self, job_id: str) -> Job: ...

    def requeue(self, job_id: str) -> Job: ...

    def unfinished(self) -> list[Job]: ...


class CatalogPort(Protocol):
    def list(self, kind: str, *, video: Video | None = None) -> list[CatalogItem]: ...

    def get(self, kind: str, item_id: str, revision: str | None = None) -> ContractModel: ...

    def pin(self, kind: str, item_id: str) -> PinnedRef: ...

    def package_dir(self, kind: str, ref: PinnedRef) -> Path: ...

    def register_generated(self, kind: str, staged_dir: Path) -> PinnedRef: ...


class PartsBuilder(Protocol):
    def build_parts(
        self,
        style: PinnedRef,
        character: Any | None,
        expression_id: str,
        pose_id: str,
        seed: int,
        *,
        cancel: CancelToken,
    ) -> dict[str, bytes]: ...


class LayerDrawer(Protocol):
    def draw_layer(
        self,
        template: PinnedRef,
        scene: Scene,
        canvas: tuple[int, int],
        parts: dict[str, bytes],
        seed: int,
        *,
        cancel: CancelToken,
    ) -> tuple[bytes | None, dict[str, Any]]: ...


@dataclass(frozen=True)
class Issue:
    pointer: str
    code: str


@dataclass(frozen=True)
class Proposal:
    ops: list[Op]
    notes: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReferenceOutcome:
    change_id: EntityId | None
    reference: Any


class JobContext(Protocol):
    @property
    def cancel(self) -> CancelToken: ...

    @property
    def deadline(self) -> float: ...

    @property
    def job_dir(self) -> Path: ...

    @property
    def input(self) -> dict[str, Any]:
        """Validated request body read back from server-only storage."""

    def progress(
        self, *, done: int, total: int, waiting_on: WaitingOn | None = None
    ) -> None: ...

    def stage(self, stage: Stage) -> AbstractContextManager[None]: ...

    def checkpoint(self, record: Checkpoint) -> None: ...

    def record_usage(self, usage: Usage) -> None: ...


class JobInputStore(Protocol):
    """Server-only storage of validated job input, never part of a Job response."""

    def save(self, job_id: str, payload: Mapping[str, Any]) -> None: ...

    def load(self, job_id: str) -> dict[str, Any] | None: ...


class JobSubmitter(Protocol):
    """Creates a queued job or returns the active job for the same request."""

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
    ) -> Job: ...


@dataclass(frozen=True)
class UploadSource:
    """One multipart file handed to a service without reading it into memory.

    The stream is open and positioned at the start. A background implementation
    copies it to a durable path before returning from submit_upload.
    """

    filename: str | None
    content_type: str | None
    stream: BinaryIO


@dataclass(frozen=True)
class ServiceDeps:
    """Concrete ports handed to service factories by the bootstrap."""

    project_store: ProjectStore
    artifact_store: ArtifactStore
    job_store: JobStore
    catalog: CatalogPort
    llm: LlmPort
    tts: TtsPort
    aligner: AlignerPort
    transcriber: TranscriberPort
    media: MediaPort
    sandbox: SandboxPort
    downloader: DownloaderPort
