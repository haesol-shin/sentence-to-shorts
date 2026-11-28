"""Sandbox runner protocol: one request on stdin, one response line on stdout."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas.common import ContractModel


class SandboxKind(StrEnum):
    style_parts = "style_parts"
    template_layer = "template_layer"
    caption_box = "caption_box"
    bgm_loop = "bgm_loop"


class SandboxAsset(ContractModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")]
    png_b64: Annotated[str, Field(max_length=2800000)]


class SandboxLimits(ContractModel):
    max_files: Annotated[int, Field(ge=1, le=64)]
    max_png_side: Annotated[int, Field(ge=16, le=1920)]
    max_wav_ms: Annotated[int, Field(ge=500, le=16000)]


class SandboxRequest(ContractModel):
    protocol: Literal[1]
    request_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
    kind: SandboxKind
    code: Annotated[str, Field(min_length=1, max_length=65536)]
    input: dict[str, Any]
    assets: Annotated[list[SandboxAsset], Field(max_length=64)]
    seed: Annotated[int, Field(ge=0, le=2147483647)]
    limits: SandboxLimits


class SandboxFile(ContractModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")]
    media_type: Literal["image/png", "audio/wav"]
    b64: Annotated[str, Field(max_length=11200000)]


class SandboxResult(ContractModel):
    type: Literal["result"]
    request_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
    files: Annotated[list[SandboxFile], Field(min_length=1, max_length=64)]
    meta: Annotated[dict[str, Any], Field(max_length=8)]


class SandboxErrorCode(StrEnum):
    python_exception = "python_exception"
    import_denied = "import_denied"
    bad_return = "bad_return"
    too_many_files = "too_many_files"
    bad_request = "bad_request"


class SandboxError(ContractModel):
    type: Literal["error"]
    request_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
    code: SandboxErrorCode
    message: Annotated[str, Field(max_length=2000)]


SandboxResponse = Annotated[SandboxResult | SandboxError, Field(discriminator="type")]
