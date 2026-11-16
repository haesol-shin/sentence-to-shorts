"""Health, runtime, session and credential endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request

from app.routers.deps import runtime
from app.schemas.api import (
    ApiKeyRequest,
    Brand,
    Capabilities,
    CredentialState,
    CsrfResponse,
    Health,
    Job,
    LlmAdapter,
    LlmAuth,
    PairRequest,
    PairResponse,
    RuntimeItem,
    RuntimeItemState,
    RuntimeStatus,
)

router = APIRouter()


def _runtime_journal(settings: Any) -> dict[str, Any]:
    path = settings.runtime_dir / "installed.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _runtime_item_ready(base: Path, item: Any, journal: dict[str, Any]) -> bool:
    record = journal.get(item.id)
    if not isinstance(record, dict):
        return False
    if record.get("install_path") != item.install_path:
        return False
    known = {(entry.file, entry.sha256) for entry in item.files}
    if (record.get("file"), record.get("sha256")) not in known:
        return False
    if item.id == "deno":
        return (base / "deno").is_file() or (base / "deno.exe").is_file()
    if item.id == "pyodide-core":
        return all(
            (base / name).is_file()
            for name in ("pyodide.asm.wasm", "python_stdlib.zip")
        )
    if item.id == "pyodide-pillow":
        return isinstance(record.get("file"), str) and (base / record["file"]).is_file()
    return base.is_dir() and any(path.is_file() for path in base.rglob("*"))


def _runtime_items(settings: Any) -> list[RuntimeItem]:
    items = []
    journal = _runtime_journal(settings)
    for item in settings.runtime.items:
        base = settings.runtime_dir / item.install_path
        installed = _runtime_item_ready(base, item, journal)
        items.append(
            RuntimeItem(
                id=item.id,
                state=RuntimeItemState.ready if installed else RuntimeItemState.missing,
                bytes=sum(entry.bytes for entry in item.files),
            )
        )
    return items


@router.get("/health", operation_id="getHealth", response_model=Health)
def get_health(request: Request) -> Health:
    settings = runtime(request).settings
    return Health(
        version=settings.app_version,
        profile=settings.profile,
        deployment=settings.deployment,
    )


@router.get("/runtime", operation_id="getRuntime", response_model=RuntimeStatus)
def get_runtime(request: Request) -> RuntimeStatus:
    app = runtime(request)
    settings = app.settings
    llm_state = app.llm.auth_state()
    tts_ready = not app.tts.ready()
    return RuntimeStatus(
        app_version=settings.app_version,
        profile=settings.profile,
        deployment=settings.deployment,
        brand=Brand(
            display_name_ko=settings.brand.display_name_ko,
            display_name_en=settings.brand.display_name_en,
        ),
        items=_runtime_items(settings),
        llm_auth=LlmAuth(
            adapter=LlmAdapter(app.llm_adapter),
            state=llm_state,
        ),
        capabilities=Capabilities(
            open_edit_play=True,
            render=app.render_ready,
            tts=tts_ready,
            llm=llm_state == "ok",
            link_download=False,
        ),
    )


@router.post(
    "/runtime/prepare",
    operation_id="postRuntimePrepare",
    response_model=Job,
    status_code=202,
)
def post_runtime_prepare(
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    return runtime(request).runtime_setup.submit_prepare(idempotency_key=idempotency_key)


@router.post("/session/pair", operation_id="postSessionPair", response_model=PairResponse)
def post_session_pair(request: Request, body: PairRequest) -> PairResponse:
    return runtime(request).access.pair(body)


@router.get("/session/csrf", operation_id="getSessionCsrf", response_model=CsrfResponse)
def get_session_csrf(request: Request) -> CsrfResponse:
    """Same-origin re-issue for a reloaded tab or a second tab."""
    return runtime(request).access.csrf(dict(request.headers))


@router.put(
    "/credentials/llm",
    operation_id="putCredentialsLlm",
    response_model=None,
    status_code=204,
)
def put_credentials_llm(request: Request, body: ApiKeyRequest) -> None:
    runtime(request).access.set_llm_credentials(body)


@router.get(
    "/credentials/llm",
    operation_id="getCredentialsLlm",
    response_model=CredentialState,
)
def get_credentials_llm(request: Request) -> CredentialState:
    return runtime(request).access.llm_credentials()


@router.delete(
    "/credentials/llm",
    operation_id="deleteCredentialsLlm",
    response_model=None,
    status_code=204,
)
def delete_credentials_llm(request: Request) -> None:
    runtime(request).access.clear_llm_credentials()
