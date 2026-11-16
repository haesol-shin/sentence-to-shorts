"""Runtime preparation and the local launcher.

`prepare` downloads, verifies and installs the pinned Deno and Pyodide files and any
model files of the runtime lock. `RuntimeSetup` is the service behind `GET /runtime`
and the `runtime_prepare` job. The launcher starts the server and opens the browser.
"""

from __future__ import annotations

from app.runtime.lock import installed_path
from app.runtime.prepare import Hooks, is_ready, prepare, status
from app.runtime.setup import RuntimeSetup, create

__all__ = [
    "Hooks",
    "RuntimeSetup",
    "create",
    "installed_path",
    "is_ready",
    "prepare",
    "status",
]
