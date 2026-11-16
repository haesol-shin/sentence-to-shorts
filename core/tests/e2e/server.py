"""The app as a server process for the end-to-end tests: python -m tests.e2e.server

It builds the real runtime from the fixture profile (real stores, jobs, pipeline,
Pillow renderer and ffmpeg, the recorded LLM, the fixed_wav voice) from the product
settings alone and serves it with uvicorn. Two things come from the test:

- E2E_PAIRING_FILE: where the pairing URL is written; no terminal is attached.
- E2E_STALL_AFTER_CLIPS: when set, the server blocks before rendering the next clip
  once that many clips exist and writes E2E_STALL_READY, so a test can kill it.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import uvicorn

from app import bootstrap
from app.main import create_app
from app.settings import Settings


def _write(path: Path, text: str) -> None:
    staged = path.with_name(path.name + ".tmp")
    staged.write_text(text, encoding="utf-8")
    staged.replace(path)


def _stall_before_clip(render: Any, after: int, ready: Path) -> None:
    clip = render.clip
    seen = [0]

    def stalled(*args: Any, **kwargs: Any) -> Any:
        if seen[0] >= after:
            _write(ready, "stalled")
            threading.Event().wait()
        seen[0] += 1
        return clip(*args, **kwargs)

    render.clip = stalled


def main() -> None:
    settings = Settings()
    runtime = bootstrap.build_runtime(settings)
    after = os.environ.get("E2E_STALL_AFTER_CLIPS")
    if after is not None:
        _stall_before_clip(
            runtime.services.render, int(after), Path(os.environ["E2E_STALL_READY"])
        )
    pairing = Path(os.environ["E2E_PAIRING_FILE"])
    app = create_app(runtime, pairing_display=lambda url: _write(pairing, url))
    uvicorn.run(app, host="127.0.0.1", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
