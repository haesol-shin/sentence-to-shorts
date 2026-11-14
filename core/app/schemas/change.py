"""Change plans: every edit becomes a plan against a base revision."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas.common import ContractModel, EntityId, Origin, Timestamp
from app.schemas.scene import Scene
from app.schemas.script import Script
from app.schemas.settings import LockKey


class ChangeSource(StrEnum):
    direct = "direct"
    card = "card"
    chat = "chat"
    scene_rewrite = "scene_rewrite"
    reference = "reference"
    style = "style"
    template = "template"
    bgm = "bgm"


class ChangeStatus(StrEnum):
    proposed = "proposed"
    applied = "applied"
    rejected = "rejected"
    stale = "stale"


class ConfirmationReason(StrEnum):
    script_rewrite = "script_rewrite"
    multi_scene = "multi_scene"
    lock_change = "lock_change"
    user_value_overwrite = "user_value_overwrite"
    rebuild_tts = "rebuild_tts"
    rebuild_render = "rebuild_render"


class WarningCode(StrEnum):
    stale_wording_in_neighbor = "stale_wording_in_neighbor"
    story_order_broken = "story_order_broken"
    weak_combination = "weak_combination"
    asset_substituted = "asset_substituted"


class Target(ContractModel):
    scene_id: EntityId | None
    pointer: Annotated[str, Field(pattern=r"^(/[A-Za-z0-9_]+)+$", max_length=200)] | None


class SetOp(ContractModel):
    op: Literal["set"]
    path: Annotated[
        str,
        Field(
            pattern=(
                r"^/(topic|material|settings(/[a-z_]+)+|scenes/[a-z]{1,2}_[0-7]"
                r"[0-9a-hjkmnp-tv-z]{25}/(beat_label|lines|visual)(/[A-Za-z0-9_]+)*)$"
            )
        ),
    ]
    value: Any
    origin: Origin


class ReorderOp(ContractModel):
    op: Literal["reorder"]
    order: Annotated[
        list[EntityId], Field(max_length=30, json_schema_extra={"uniqueItems": True})
    ]


class AddSceneOp(ContractModel):
    op: Literal["add_scene"]
    after: EntityId | None
    scene: Scene


class RemoveSceneOp(ContractModel):
    op: Literal["remove_scene"]
    scene_id: EntityId


class ReplaceSceneOp(ContractModel):
    op: Literal["replace_scene"]
    scene: Scene


class SetScriptOp(ContractModel):
    op: Literal["set_script"]
    script: Script
    scenes: Annotated[list[Scene], Field(min_length=1, max_length=30)]


Op = Annotated[
    SetOp | ReorderOp | AddSceneOp | RemoveSceneOp | ReplaceSceneOp | SetScriptOp,
    Field(discriminator="op"),
]


class Effects(ContractModel):
    script: bool
    scene_ids_text: Annotated[list[EntityId], Field(json_schema_extra={"uniqueItems": True})]
    scene_ids_tts: Annotated[list[EntityId], Field(json_schema_extra={"uniqueItems": True})]
    scene_ids_render: Annotated[
        list[EntityId], Field(json_schema_extra={"uniqueItems": True})
    ]
    mix: bool
    assemble: bool
    locked_keys: Annotated[list[LockKey], Field(json_schema_extra={"uniqueItems": True})]
    overwrites_user_values: Annotated[
        list[Annotated[str, Field(max_length=200)]],
        Field(json_schema_extra={"uniqueItems": True}),
    ]


class PlanWarning(ContractModel):
    code: WarningCode
    scene_id: EntityId | None


class ChangePlan(ContractModel):
    schema_version: Literal[1]
    id: EntityId
    video_id: EntityId
    base_revision: Annotated[int, Field(ge=1)]
    created_at: Timestamp
    source: ChangeSource
    target: Target
    ops: Annotated[list[Op], Field(min_length=1, max_length=60)]
    effects: Effects
    requires_confirmation: bool
    confirmation_reasons: Annotated[
        list[ConfirmationReason], Field(json_schema_extra={"uniqueItems": True})
    ]
    warnings: Annotated[list[PlanWarning], Field(max_length=30)]
    unsupported: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=10)
    ]
    notes: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=300)]], Field(max_length=5)
    ]
    status: ChangeStatus
    applied_revision: Annotated[int, Field(ge=1)] | None
