"""Install the bundled runtime items into the distribution's `rt` folder.

`build.py` runs this file with the bundled interpreter after the app and its packages
are in place. It uses the same `prepare` the app uses at first run, so the journal in
`rt/installed.json` is the one the app reads and a first run downloads nothing for the
items listed in `bundle.json`.

    python prepare_runtime.py <bundle folder> <bundle.json>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


class NeverCancelled:
    def is_set(self) -> bool:
        return False

    def raise_if_set(self) -> None:
        return None

    def wait(self, seconds: float) -> bool:
        return False


def main(argv: list[str]) -> int:
    bundle = Path(argv[1]).resolve()
    wanted = json.loads(Path(argv[2]).read_text(encoding="utf-8"))["bundled_runtime_items"]
    sys.path[:0] = [str(bundle / "core"), str(bundle / "site-packages")]
    os.environ["APP_RUNTIME_DIR"] = str(bundle / "rt")
    from app.runtime import prepare
    from app.runtime.lock import lock_items
    from app.settings import Settings

    settings = Settings()
    items = [item for item in lock_items(settings) if item["id"] in wanted]
    missing = sorted(set(wanted) - {item["id"] for item in items})
    if missing:
        print(f"runtime lock has no item: {', '.join(missing)}", file=sys.stderr)
        return 1
    ready = prepare(settings, items, cancel=NeverCancelled())
    print(json.dumps({"prepared": ready}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
