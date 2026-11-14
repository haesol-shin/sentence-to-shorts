"""A deliberate reverse import must fail lint-imports."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "reverse_import"


def _executable(scripts_dir: Path) -> Path | None:
    for name in (
        "lint-imports",
        "lint-imports.exe",
        "lint-imports.cmd",
        "lint-imports.bat",
    ):
        candidate = scripts_dir / name
        if candidate.is_file():
            return candidate
    return None


def test_executable_lookup_accepts_windows_shim(tmp_path: Path) -> None:
    (tmp_path / "lint-imports.exe").write_bytes(b"")
    executable = _executable(tmp_path)
    assert executable is not None
    assert executable.name == "lint-imports.exe"


def test_reverse_import_fails_lint_imports(tmp_path: Path) -> None:
    workdir = tmp_path / "reverse"
    shutil.copytree(FIXTURE, workdir)
    executable = _executable(Path(sys.executable).parent)
    assert executable is not None, "lint-imports must be installed in the test environment"
    environment = {**os.environ, "PYTHONPATH": str(workdir)}
    result = subprocess.run(
        [str(executable), "--config", "importlinter.toml"],
        cwd=workdir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "fakeapp" in output
