"""Sandbox adapter boundary. The Deno runner lands with the sandbox task."""

from __future__ import annotations

from app.ports import AppSettings, CancelToken, SandboxPort, ValidatedOutput
from app.schemas.sandbox_io import SandboxRequest


class SandboxAdapter(SandboxPort):
    def run(
        self, request: SandboxRequest, *, cancel: CancelToken
    ) -> ValidatedOutput:
        raise NotImplementedError

    def runtime_digest(self) -> str:
        raise NotImplementedError


def create(settings: AppSettings) -> SandboxAdapter:
    raise NotImplementedError("tools/sandbox")


def create_skeleton(settings: AppSettings) -> SandboxAdapter:
    """Fixture-profile placeholder; every call still reports not implemented."""
    return SandboxAdapter()
