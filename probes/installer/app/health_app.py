"""The empty FastAPI app the probe installs.

It answers only `/health` and reports the absolute interpreter that serves it. The probe
compares that path with the install directory to prove the request did not reach a Python
interpreter on PATH.
"""

from __future__ import annotations

import platform
import sys

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "python": sys.executable,
        "base_prefix": sys.base_prefix,
        "version": platform.python_version(),
    }
