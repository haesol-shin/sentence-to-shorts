"""HTTP request and response bodies that are not documents themselves."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas.bgm_entry import BuiltinBgm, SfxEntry, TypingSoundEntry
from app.schemas.caption_language_manifest import CaptionLanguageManifest
from app.schemas.change import Op, Target
from app.schemas.common import (
    CatalogId,
    ContractModel,
    Digest,
    EntityId,
    Language,
    LocalizedText,
    Mood,
    PackageOrigin,
    PinnedRef,
    Timestamp,
)
from app.schemas.font_manifest import FontManifest
from app.schemas.format_card import FormatCard, StoryStructure
from app.schemas.job import Job
from app.schemas.preset import Preset
from app.schemas.style_manifest import StyleManifest
from app.schemas.template_manifest import TemplateManifest
from app.schemas.video import RevisionInfo, Video, VideoBuild
from app.schemas.voice_manifest import VoiceManifest


class ApiErrorCode(StrEnum):
    validation_failed = "validation_failed"
    unauthenticated = "unauthenticated"
    csrf_failed = "csrf_failed"
    forbidden_host = "forbidden_host"
    forbidden_origin = "forbidden_origin"
    loopback_only = "loopback_only"
    pair_invalid = "pair_invalid"
    rate_limited = "rate_limited"
    not_found = "not_found"
    revision_conflict = "revision_conflict"
    idempotency_mismatch = "idempotency_mismatch"
    job_running = "job_running"
    job_terminal = "job_terminal"
    job_not_retryable = "job_not_retryable"
    script_missing = "script_missing"
    script_not_confirmed = "script_not_confirmed"
    scene_data_missing = "scene_data_missing"
    scenes_not_confirmed = "scenes_not_confirmed"
    concept_missing = "concept_missing"
    concept_locked = "concept_locked"
    nothing_to_undo = "nothing_to_undo"
    change_stale = "change_stale"
    not_built = "not_built"
    unknown_catalog_id = "unknown_catalog_id"
    invalid_combination = "invalid_combination"
    invalid_op = "invalid_op"
    payload_too_large = "payload_too_large"
    unsupported_media = "unsupported_media"
    unsupported_version = "unsupported_version"
    link_disabled = "link_disabled"
    url_not_allowed = "url_not_allowed"
    runtime_not_ready = "runtime_not_ready"
    llm_auth_required = "llm_auth_required"
    not_implemented = "not_implemented"
    internal = "internal"


class SemanticCode(StrEnum):
    """Codes returned in the errors member of a problem body (CONTRACTS 1.3)."""

    unknown_catalog_id = "unknown_catalog_id"
    duplicate_order = "duplicate_order"
    duplicate_line_id = "duplicate_line_id"
    typewriter_layout = "typewriter_layout"
    role_none_character = "role_none_character"
    character_missing = "character_missing"
    incompatible_part = "incompatible_part"
    highlight_range = "highlight_range"
    reveal_line_unknown = "reveal_line_unknown"
    typing_sound_mode = "typing_sound_mode"
    typing_sound_kind = "typing_sound_kind"
    typing_cue = "typing_cue"
    caption_text_missing = "caption_text_missing"
    caption_mode_language = "caption_mode_language"
    caption_layer_unsupported = "caption_layer_unsupported"
    caption_overlap = "caption_overlap"
    revision_conflict = "revision_conflict"


class ErrorItem(ContractModel):
    pointer: Annotated[str, Field(max_length=200)]
    code: SemanticCode


class ApiError(ContractModel):
    code: ApiErrorCode
    message_key: Annotated[str, Field(pattern=r"^error\.[a-z_.]+$")]
    retryable: bool
    detail: Annotated[dict[str, Any], Field(max_length=8)]


class Problem(ContractModel):
    """RFC 9457 problem details plus the app extension members."""

    type: Annotated[str, Field(pattern=r"^https://app\.invalid/problems/[a-z_]+$")]
    title: Annotated[str, Field(max_length=200)]
    status: Annotated[int, Field(ge=100, le=599)]
    detail: Annotated[str, Field(max_length=2000)]
    instance: Annotated[str, Field(max_length=500)]
    code: ApiErrorCode
    message_key: Annotated[str, Field(pattern=r"^error\.[a-z_.]+$")]
    retryable: bool
    errors: Annotated[list[ErrorItem], Field(max_length=100)]
    current_revision: Annotated[int, Field(ge=1)] | None = None
    job_id: EntityId | None = None
    found: int | None = None
    supported: int | None = None


class BaseRevision(ContractModel):
    base_revision: Annotated[int, Field(ge=1)]


class Health(ContractModel):
    version: Annotated[str, Field(max_length=40)]
    profile: Literal["fixture", "dev", "release"]
    deployment: Literal["local", "hosted"]


class PairRequest(ContractModel):
    code: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")]


CsrfToken = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{32,64}$")]


class PairResponse(ContractModel):
    csrf_token: CsrfToken
    profile: Literal["fixture", "dev", "release"]
    deployment: Literal["local", "hosted"]
    ui_language: Language


class CsrfResponse(ContractModel):
    """Same-origin re-issue for a reloaded tab; the client keeps it in memory."""

    csrf_token: CsrfToken


class ApiKeyRequest(ContractModel):
    api_key: Annotated[str, Field(min_length=20, max_length=300)]


class CredentialState(ContractModel):
    configured: bool


class Brand(ContractModel):
    display_name_ko: Annotated[str, Field(max_length=60)]
    display_name_en: Annotated[str, Field(max_length=60)]


class RuntimeItemState(StrEnum):
    ready = "ready"
    missing = "missing"
    corrupt = "corrupt"
    downloading = "downloading"


class RuntimeItem(ContractModel):
    id: CatalogId
    state: RuntimeItemState
    bytes: Annotated[int, Field(ge=0)]


class LlmAuthState(StrEnum):
    ok = "ok"
    missing = "missing"
    expired = "expired"
    unknown = "unknown"


class LlmAdapter(StrEnum):
    fixture = "fixture"
    openai_compat = "openai_compat"
    claude_cli = "claude_cli"
    anthropic_api = "anthropic_api"


class LlmAuth(ContractModel):
    adapter: LlmAdapter
    state: LlmAuthState


class SpeechDevice(ContractModel):
    """The compute device a speech adapter settled on, and why."""

    device: Literal["cpu", "cuda"]
    reason: Literal["configured", "detected", "unavailable", "load_failed"]


class SpeechDevices(ContractModel):
    tts: SpeechDevice
    asr: SpeechDevice


class Capabilities(ContractModel):
    """Offline scope. open/edit/play work offline; generation needs the listed items."""

    open_edit_play: bool
    render: bool
    tts: bool
    llm: bool
    link_download: bool


class RuntimeStatus(ContractModel):
    app_version: Annotated[str, Field(max_length=40)]
    profile: Literal["fixture", "dev", "release"]
    deployment: Literal["local", "hosted"]
    brand: Brand
    items: list[RuntimeItem]
    llm_auth: LlmAuth
    capabilities: Capabilities
    speech: SpeechDevices


class CatalogKind(StrEnum):
    format_card = "format_card"
    story_structure = "story_structure"
    art_style = "art_style"
    template = "template"
    voice = "voice"
    bgm = "bgm"
    sfx = "sfx"
    font = "font"
    caption_language = "caption_language"


class Compatibility(ContractModel):
    ok: bool
    reason: Annotated[str, Field(max_length=80)] | None


class CatalogItem(ContractModel):
    kind: CatalogKind
    id: CatalogId
    revision: Digest
    label: LocalizedText
    origin: PackageOrigin
    thumbnail: Annotated[str, Field(pattern=r"^/api/v1/catalog/")] | None
    compatible: Compatibility | None


class CatalogList(ContractModel):
    items: list[CatalogItem]
    next_cursor: str | None


class CreateProjectRequest(ContractModel):
    title: Annotated[str, Field(min_length=1, max_length=80)] | None
    language: Language


class ProjectSummary(ContractModel):
    id: EntityId
    title: Annotated[str, Field(min_length=1, max_length=80)]
    updated_at: Timestamp
    video_count: Annotated[int, Field(ge=0)]


class ProjectList(ContractModel):
    items: list[ProjectSummary]
    next_cursor: str | None


class CreateVideoRequest(ContractModel):
    from_video_id: EntityId | None
    preset_id: EntityId | None


class DraftRequest(ContractModel):
    base_revision: Annotated[int, Field(ge=1)]
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    card_id: CatalogId | None


class ChangeRequest(ContractModel):
    base_revision: Annotated[int, Field(ge=1)]
    source: Literal["direct", "card"]
    target: Target
    ops: Annotated[list[Op], Field(min_length=1, max_length=60)]


class MessageRequest(ContractModel):
    base_revision: Annotated[int, Field(ge=1)]
    text: Annotated[str, Field(max_length=2000)]
    target: Target


class LinkRequest(ContractModel):
    base_revision: Annotated[int, Field(ge=1)]
    url: Annotated[str, Field(pattern=r"^https://", max_length=500)]


class StyleRequest(ContractModel):
    video_id: EntityId
    base_revision: Annotated[int, Field(ge=1)]
    instruction: Annotated[str, Field(min_length=1, max_length=2000)]
    base_style: PinnedRef | None
    use_reference: bool


class TemplateRequest(ContractModel):
    video_id: EntityId
    base_revision: Annotated[int, Field(ge=1)]
    instruction: Annotated[str, Field(min_length=1, max_length=2000)]


class BgmCodeRequest(ContractModel):
    project_id: EntityId
    mood: Mood
    instruction: Annotated[str, Field(max_length=1000)] | None
    seed: Annotated[int, Field(ge=0, le=2147483647)] | None


class PresetRequest(ContractModel):
    video_id: EntityId
    name: Annotated[str, Field(min_length=1, max_length=60)]


class PresetList(ContractModel):
    items: list[Preset]
    next_cursor: str | None


class PreviewRequest(BaseRevision):
    scene_ids: Annotated[list[EntityId], Field(max_length=30)] | None = None


class VideoView(ContractModel):
    video: Video
    build: VideoBuild
    open_jobs: list[EntityId]
    pending_change: EntityId | None


class Claim(ContractModel):
    scene_id: EntityId
    text: Annotated[str, Field(max_length=300)]
    material_id: EntityId | None


class PrecheckReport(ContractModel):
    opening_promise: Annotated[str, Field(max_length=300)]
    ending_answer: Annotated[str, Field(max_length=300)]
    claims: Annotated[list[Claim], Field(max_length=20)]
    hypotheticals: Annotated[list[EntityId], Field(max_length=20)]


class ActivityKind(StrEnum):
    active = "active"
    waiting = "waiting"


class ActivitySpan(ContractModel):
    kind: ActivityKind
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(ge=0)]


class ActivityRequest(ContractModel):
    spans: Annotated[list[ActivitySpan], Field(max_length=200)]


class Metrics(ContractModel):
    active_ms: Annotated[int, Field(ge=0)]
    waiting_ms: Annotated[int, Field(ge=0)]
    job_wall_ms: Annotated[int, Field(ge=0)]
    input_tokens: Annotated[int, Field(ge=0)] | None
    output_tokens: Annotated[int, Field(ge=0)] | None
    cost_micro_usd: Annotated[int, Field(ge=0)] | None
    regenerated_scene_ids: list[EntityId]


class RevisionList(ContractModel):
    items: list[RevisionInfo]
    next_cursor: str | None


class JobList(ContractModel):
    items: list[Job]
    next_cursor: str | None


CatalogManifest = (
    StyleManifest
    | TemplateManifest
    | VoiceManifest
    | BuiltinBgm
    | SfxEntry
    | TypingSoundEntry
    | FontManifest
    | FormatCard
    | StoryStructure
    | CaptionLanguageManifest
)
