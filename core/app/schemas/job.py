"""Job rows returned by the jobs API, with errors and usage records."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import Field

from app.schemas.common import ContractModel, Digest, EntityId, OwnerId, Timestamp


class JobKind(StrEnum):
    draft = "draft"
    script = "script"
    chat = "chat"
    preview = "preview"
    generate = "generate"
    precheck = "precheck"
    reference = "reference"
    style = "style"
    template = "template"
    bgm_code = "bgm_code"
    bgm_upload = "bgm_upload"
    runtime_prepare = "runtime_prepare"


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelling = "cancelling"
    cancelled = "cancelled"


class Stage(StrEnum):
    llm_draft = "llm_draft"
    llm_script = "llm_script"
    llm_split = "llm_split"
    llm_scene_data = "llm_scene_data"
    llm_chat = "llm_chat"
    llm_precheck = "llm_precheck"
    layer = "layer"
    still = "still"
    tts = "tts"
    align = "align"
    clip = "clip"
    mix = "mix"
    assemble = "assemble"
    srt = "srt"
    ref_fetch = "ref_fetch"
    ref_frames = "ref_frames"
    ref_transcribe = "ref_transcribe"
    ref_llm = "ref_llm"
    code_llm = "code_llm"
    sandbox = "sandbox"
    validate = "validate"
    save = "save"
    decode = "decode"
    model_download = "model_download"
    model_verify = "model_verify"


class WaitingOn(StrEnum):
    queue = "queue"
    llm = "llm"
    llm_rate_limit = "llm_rate_limit"
    tts = "tts"
    align = "align"
    render = "render"
    encode = "encode"
    sandbox = "sandbox"
    download = "download"


class StageState(StrEnum):
    running = "running"
    done = "done"
    skipped = "skipped"
    failed = "failed"
    cancelled = "cancelled"


class Effort(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class JobErrorCode(StrEnum):
    llm_auth = "llm_auth"
    llm_quota = "llm_quota"
    llm_rate_limited = "llm_rate_limited"
    llm_timeout = "llm_timeout"
    llm_connection = "llm_connection"
    llm_invalid_output = "llm_invalid_output"
    llm_refused = "llm_refused"
    tts_not_ready = "tts_not_ready"
    tts_failed = "tts_failed"
    tts_timeout = "tts_timeout"
    render_failed = "render_failed"
    font_missing_glyph = "font_missing_glyph"
    sandbox_denied = "sandbox_denied"
    sandbox_timeout = "sandbox_timeout"
    sandbox_memory = "sandbox_memory"
    sandbox_output_invalid = "sandbox_output_invalid"
    sandbox_crashed = "sandbox_crashed"
    sandbox_unavailable = "sandbox_unavailable"
    media_failed = "media_failed"
    media_invalid_input = "media_invalid_input"
    download_blocked = "download_blocked"
    download_failed = "download_failed"
    download_too_large = "download_too_large"
    url_not_allowed = "url_not_allowed"
    upload_invalid = "upload_invalid"
    model_missing = "model_missing"
    model_hash_mismatch = "model_hash_mismatch"
    disk_full = "disk_full"
    deadline_exceeded = "deadline_exceeded"
    interrupted = "interrupted"
    stale_revision = "stale_revision"
    unsupported_version = "unsupported_version"
    internal = "internal"


class Progress(ContractModel):
    stage: Stage | None
    done: Annotated[int, Field(ge=0)]
    total: Annotated[int, Field(ge=0)]
    waiting_on: WaitingOn | None


class StageRecord(ContractModel):
    stage: Stage
    state: StageState
    started_ms: Annotated[int, Field(ge=0)]
    ended_ms: Annotated[int, Field(ge=0)] | None
    cache_hits: Annotated[int, Field(ge=0)]
    rebuilt_scene_ids: list[EntityId]


class Checkpoint(ContractModel):
    stage: Stage
    scene_id: EntityId | None
    line_id: EntityId | None
    artifact_id: EntityId
    digest: Digest


class Usage(ContractModel):
    stage: Stage
    provider: Annotated[str, Field(max_length=40)]
    model: Annotated[str, Field(max_length=80)]
    effort: Effort | None
    input_tokens: Annotated[int, Field(ge=0)] | None
    output_tokens: Annotated[int, Field(ge=0)] | None
    cache_read_tokens: Annotated[int, Field(ge=0)] | None
    cost_usd: Annotated[float, Field(ge=0)] | None
    wall_ms: Annotated[int, Field(ge=0)]
    retries: Annotated[int, Field(ge=0)]


class JobError(ContractModel):
    code: JobErrorCode
    retryable: bool
    stage: Stage | None
    scene_id: EntityId | None
    detail: Annotated[dict[str, Any], Field(max_length=8)]


class Job(ContractModel):
    id: EntityId
    kind: JobKind
    owner_id: OwnerId
    state: JobState
    project_id: EntityId | None
    video_id: EntityId | None
    base_revision: Annotated[int, Field(ge=1)] | None
    request_digest: Digest
    idempotency_key: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")] | None
    attempt: Annotated[int, Field(ge=1)]
    max_attempts: Annotated[int, Field(ge=1, le=5)]
    created_at: Timestamp
    started_at: Timestamp | None
    ended_at: Timestamp | None
    deadline_at: Timestamp | None
    progress: Progress
    stages: list[StageRecord]
    checkpoints: list[Checkpoint]
    usage: list[Usage]
    result: dict[str, Any] | None
    error: JobError | None
    partial: bool
