"""Entry point of an installed distribution.

The Windows shortcut and `start.sh` run this file with the bundled interpreter. It sits
outside the app package so it may import the composition root, which the launcher
module must not. Everything else, the lock, the port, the pairing and the server, is
in `app.runtime.launcher`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    for name in ("core", "site-packages"):
        folder = ROOT / name
        if folder.is_dir():
            sys.path.insert(0, str(folder))
    from app.access import SECURITY_HEADERS
    from app.bootstrap import declare
    from app.llm.providers.claude_cli.adapter import MINIMUM_VERSION
    from app.main import create_app
    from app.runtime.launcher import Parts, adapter_choices, read_distribution, run
    from app.settings import Settings

    dist = read_distribution(ROOT)

    def load_settings(port: int | None) -> Settings:
        settings = Settings(port=port) if port else Settings()
        settings.providers.adapters.update(adapter_choices(dist, settings.profile, os.environ))
        return settings

    def build_app(settings: Settings, display):  # type: ignore[no-untyped-def]
        return create_app(declaration=declare(settings), pairing_display=display)

    parts = Parts(
        load_settings=load_settings,  # type: ignore[arg-type]
        build_app=build_app,  # type: ignore[arg-type]
        headers=SECURITY_HEADERS,
        claude_minimum=MINIMUM_VERSION,
    )
    return run(ROOT, parts)


if __name__ == "__main__":
    raise SystemExit(main())
