"""FastAPI application factory: app creation, error translation and router wiring."""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from app.access import SECURITY_HEADERS
from app.access.idempotency import IdempotencyGate, IdempotencyMiddleware, keyed_routes
from app.access.middleware import AccessMiddleware
from app.bootstrap import AppDeclaration, AppRuntime, build_runtime, declare
from app.ports import AppError, UnknownCatalogId
from app.routers import artifacts, catalog, changes, jobs, media, projects, system, videos
from app.schemas.api import ApiErrorCode, ErrorItem, Problem
from app.storage.paths import Layout

PROBLEM_MEDIA_TYPE = "application/problem+json"
API_TITLE = "Video studio API"
PROBLEM_RESPONSES = {
    422: {
        "model": Problem,
        "description": "The request body or parameters do not match the contract.",
        "content": {PROBLEM_MEDIA_TYPE: {}},
    },
    500: {
        "model": Problem,
        "description": "Unexpected server failure.",
        "content": {PROBLEM_MEDIA_TYPE: {}},
    },
    501: {
        "model": Problem,
        "description": "The service behind this route is not implemented yet.",
        "content": {PROBLEM_MEDIA_TYPE: {}},
    },
}

STATUS_BY_CODE: dict[str, int] = {
    "validation_failed": 422,
    "unauthenticated": 401,
    "csrf_failed": 403,
    "forbidden_host": 403,
    "forbidden_origin": 403,
    "loopback_only": 403,
    "pair_invalid": 401,
    "rate_limited": 429,
    "not_found": 404,
    "revision_conflict": 409,
    "idempotency_mismatch": 409,
    "job_running": 409,
    "job_terminal": 409,
    "job_not_retryable": 409,
    "script_missing": 409,
    "script_not_confirmed": 409,
    "scene_data_missing": 409,
    "scenes_not_confirmed": 409,
    "concept_missing": 409,
    "concept_locked": 409,
    "nothing_to_undo": 409,
    "change_stale": 409,
    "not_built": 409,
    "unknown_catalog_id": 404,
    "invalid_combination": 422,
    "invalid_op": 422,
    "payload_too_large": 413,
    "unsupported_media": 415,
    "unsupported_version": 422,
    "link_disabled": 403,
    "url_not_allowed": 422,
    "runtime_not_ready": 503,
    "llm_auth_required": 503,
    "not_implemented": 501,
    "internal": 500,
}
RETRYABLE = frozenset({"rate_limited", "job_running", "internal"})
CONTEXT_FIELDS = ("current_revision", "job_id", "found", "supported")


def problem(
    request: Request,
    status: int,
    code: ApiErrorCode,
    detail: str,
    *,
    errors: list[ErrorItem] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "type": f"https://app.invalid/problems/{code.value}",
        "title": code.value.replace("_", " ").capitalize(),
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "code": code.value,
        "message_key": f"error.{code.value}",
        "retryable": code.value in RETRYABLE,
        "errors": [item.model_dump(mode="json") for item in (errors or [])],
    }
    for key in CONTEXT_FIELDS:
        if extra and key in extra:
            payload[key] = extra[key]
    body = Problem.model_validate(payload)
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json"),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=SECURITY_HEADERS,
    )


def _reject(scope: Scope, code: str, detail: str) -> JSONResponse:
    """Problem response for a request refused before routing."""
    error = ApiErrorCode(code)
    return problem(Request(scope), STATUS_BY_CODE[error.value], error, detail)


def _use_problem_media_type(document: dict[str, Any]) -> None:
    """FastAPI documents additional response models as application/json. Move the
    Problem schema to the media type the server actually returns."""
    for path_item in document.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for response in operation.get("responses", {}).values():
                content = response.get("content")
                if not content:
                    continue
                json_media = content.get("application/json", {})
                schema = json_media.get("schema", {})
                if str(schema.get("$ref", "")).endswith("/Problem"):
                    content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")


def _display_pairing_url(url: str) -> None:
    """Show pairing on a local screen, not on a redirected logging stream."""
    if sys.stdout.isatty():
        print(f"Pair this browser: {url}")
        return
    try:
        with open("/dev/tty", "w", encoding="utf-8") as terminal:
            terminal.write(f"Pair this browser: {url}\n")
    except OSError as error:
        raise RuntimeError(
            "Pairing requires a local terminal or a launcher pairing_display callback."
        ) from error


def create_app(
    runtime: AppRuntime | None = None,
    *,
    declaration: AppDeclaration | None = None,
    pairing_display: Callable[[str], None] | None = None,
) -> FastAPI:
    """Declare the app. Adapters and packages are built in the lifespan, not here."""
    declared = declaration or declare(runtime.settings if runtime is not None else None)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = runtime if runtime is not None else build_runtime(declared.settings)
        settings = active.settings
        gate = None
        try:
            gate = IdempotencyGate.open(
                Layout.from_settings(settings).state_db,
                ttl_hours=settings.app.limits.idempotency_key_ttl_hours,
            )
            app.state.runtime = active
            app.state.idempotency = gate
            code = active.access.issue_pairing_code()
            host = settings.bind_host if settings.lan else "127.0.0.1"
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            display = pairing_display if pairing_display is not None else _display_pairing_url
            display(f"http://{host}:{settings.port}/#pair={code}")
            yield
        finally:
            if gate is not None:
                gate.close()
            app.state.idempotency = None
            active.close()
            if runtime is None:
                app.state.runtime = None

    docs_path = "/docs" if declared.docs_enabled else None
    openapi_path = "/openapi.json" if declared.docs_enabled else None
    app = FastAPI(
        title=API_TITLE,
        version=declared.version,
        docs_url=docs_path,
        redoc_url=None,
        openapi_url=openapi_path,
        lifespan=lifespan,
        responses=PROBLEM_RESPONSES,
    )
    app.state.runtime = runtime
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        document = original_openapi()
        _use_problem_media_type(document)
        return document

    app.openapi = openapi  # type: ignore[method-assign]

    for router in (
        system.router,
        catalog.router,
        projects.router,
        videos.router,
        changes.router,
        jobs.router,
        artifacts.router,
        media.router,
    ):
        app.include_router(router, prefix="/api/v1")

    uploads = declared.settings.app.uploads
    upload_limits = {
        "/api/v1/videos/{vid}/references": uploads.reference_max_bytes,
        "/api/v1/bgm/uploads": uploads.bgm_max_bytes,
    }
    # The last middleware added runs first: access checks precede body reads.
    app.add_middleware(
        IdempotencyMiddleware, routes=keyed_routes(app.openapi(), upload_limits), reject=_reject
    )
    app.add_middleware(AccessMiddleware, reject=_reject)

    @app.exception_handler(NotImplementedError)
    async def not_implemented(request: Request, exc: NotImplementedError) -> JSONResponse:
        return problem(
            request,
            501,
            ApiErrorCode.not_implemented,
            "This service is part of the execution skeleton and is not implemented yet.",
        )

    @app.exception_handler(UnknownCatalogId)
    async def unknown_catalog(request: Request, exc: UnknownCatalogId) -> JSONResponse:
        return problem(request, 404, ApiErrorCode.not_found, "Unknown catalog id.")

    @app.exception_handler(RequestValidationError)
    async def validation_failed(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return problem(
            request,
            422,
            ApiErrorCode.validation_failed,
            "The request body or parameters do not match the contract.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = ApiErrorCode.not_found if exc.status_code == 404 else ApiErrorCode.internal
        return problem(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        try:
            code = ApiErrorCode(exc.code)
        except ValueError:
            code = ApiErrorCode.internal
        status = STATUS_BY_CODE.get(code.value, 500)
        return problem(
            request,
            status,
            code,
            f"Adapter failed with {code.value}.",
            extra=exc.detail,
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        return problem(
            request,
            500,
            ApiErrorCode.internal,
            "The server could not complete the request.",
        )

    return app
