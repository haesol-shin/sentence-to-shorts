"""Start the app with the fixture profile for the browser end-to-end tests.

The Playwright web server runs this module. `tests.e2e.server` still owns the
process and the pairing URL; this helper only gives that URL the dev server's
origin, writes it where the tests read it, and stops the process on SIGTERM.
"""

from __future__ import annotations

import os
import shutil
import signal
import threading
from pathlib import Path

from tests.e2e.support import Server


def _app_pairing_url(server: Server, app_url: str) -> str:
    """The fixture pairing code on the origin the browser tests open."""
    backend_url = server.pairing.read_text(encoding="utf-8").strip()
    code = backend_url.split("#pair=", 1)[1]
    return f"{app_url.rstrip('/')}/#pair={code}"


def main() -> None:
    root = Path(os.environ["E2E_UI_ROOT"])
    pairing_file = Path(os.environ["E2E_UI_PAIRING_FILE"])
    app_url = os.environ["E2E_APP_URL"]

    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    pairing_file.parent.mkdir(parents=True, exist_ok=True)

    server = Server(root)
    server.port = int(os.environ["APP_PORT"])
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    try:
        server.start()
        pairing_file.write_text(_app_pairing_url(server, app_url), encoding="utf-8")
        stopping.wait()
    finally:
        server.kill()


if __name__ == "__main__":
    main()
