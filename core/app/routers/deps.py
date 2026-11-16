"""Request helpers shared by the routers."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from pydantic import BaseModel

from app.ports import canonical_digest


def runtime(request: Request) -> Any:
    """The bootstrap runtime attached in create_app. Typed as Any to keep layers one-way.

    The first request after the server owns the data store starts the job workers:
    the lifespan opens that store after the runtime is built and has no hook of its
    own, so starting here keeps recovery behind the instance lock.
    """
    active = request.app.state.runtime
    active.start()
    return active


def request_digest(body: BaseModel) -> str:
    """SHA-256 of canonical JSON for a JSON request body."""
    return canonical_digest(body.model_dump(mode="json", by_alias=True))
