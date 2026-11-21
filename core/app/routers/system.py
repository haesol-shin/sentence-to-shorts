"""Health, runtime, session and credential endpoints."""

from __future__ import annotations

from typing import Annotated

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
    RuntimePrepare,
    RuntimeStatus,
    SpeechDevice,
    SpeechDevices,
)
from app.schemas.common import PERSONAL_OWNER_ID

router = APIRouter()


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
    llm_state = app.llm.auth_state(PERSONAL_OWNER_ID)
    tts_ready = not app.tts.ready()
    items = app.runtime_setup.status()
    return RuntimeStatus(
        app_version=settings.app_version,
        profile=settings.profile,
        deployment=settings.deployment,
        brand=Brand(
            display_name_ko=settings.brand.display_name_ko,
            display_name_en=settings.brand.display_name_en,
        ),
        items=items,
        prepare=RuntimePrepare(groups=app.runtime_setup.groups(items)),
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
        speech=SpeechDevices(
            tts=_speech_device(app.tts),
            asr=_speech_device(app.transcriber),
        ),
    )


def _speech_device(adapter: object) -> SpeechDevice:
    """An adapter that does not pick a device, such as the fixtures, runs on the CPU."""
    status = getattr(adapter, "device_status", None)
    if callable(status):
        device, reason = status()
        return SpeechDevice(device=device, reason=reason)
    return SpeechDevice(
        device=getattr(adapter, "device", "cpu"),
        reason=getattr(adapter, "device_reason", "configured"),
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
    app = runtime(request)
    app.credentials.put(PERSONAL_OWNER_ID, app.llm_adapter, body.api_key, None)


@router.get(
    "/credentials/llm",
    operation_id="getCredentialsLlm",
    response_model=CredentialState,
)
def get_credentials_llm(request: Request) -> CredentialState:
    app = runtime(request)
    configured = app.credentials.credential_id(
        PERSONAL_OWNER_ID, app.llm_adapter
    ) is not None or app.llm.auth_state(PERSONAL_OWNER_ID) != "missing"
    return CredentialState(configured=configured)


@router.delete(
    "/credentials/llm",
    operation_id="deleteCredentialsLlm",
    response_model=None,
    status_code=204,
)
def delete_credentials_llm(request: Request) -> None:
    app = runtime(request)
    app.credentials.delete(PERSONAL_OWNER_ID, app.llm_adapter)
