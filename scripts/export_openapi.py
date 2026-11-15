#!/usr/bin/env python3
"""Write core/openapi.json from the FastAPI app.

`scripts/export_schemas.py` writes the JSON Schema files and the OpenAPI
document in one run. The frontend needs only the OpenAPI document to generate
its TypeScript types, so this entry point does not rewrite `schemas/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_schemas import export_openapi  # noqa: E402


def main() -> int:
    export_openapi()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
