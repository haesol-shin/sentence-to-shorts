"""Development setup puts a single-file program where the runtime lock says and runs it."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("dev_setup", ROOT / "scripts" / "dev_setup.py")
assert SPEC is not None and SPEC.loader is not None
dev_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev_setup)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_dev_setup_installs_a_single_file_program_executable_below_its_install_path(
    tmp_path: Path,
) -> None:
    downloaded = tmp_path / "download" / "yt-dlp_linux"
    downloaded.parent.mkdir()
    downloaded.write_bytes(b"synthetic program")
    downloaded.chmod(0o644)
    item = {"id": "yt-dlp", "install_path": "yt-dlp"}
    entry = {"os": "linux", "arch": "x86_64", "file": "yt-dlp_linux"}
    root = tmp_path / "rt"
    dev_setup.extract_item(item, entry, downloaded, root)
    installed = root / "yt-dlp" / "yt-dlp_linux"
    assert installed.read_bytes() == b"synthetic program"
    assert os.access(installed, os.X_OK)
    assert not (root / "yt-dlp_linux").exists()
