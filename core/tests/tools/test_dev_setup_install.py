"""Development setup puts a single-file program where the runtime lock says."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("dev_setup", ROOT / "scripts" / "dev_setup.py")
assert SPEC is not None and SPEC.loader is not None
dev_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev_setup)


def test_dev_setup_installs_a_single_file_below_its_install_path(tmp_path: Path) -> None:
    downloaded = tmp_path / "download" / "yt-dlp"
    downloaded.parent.mkdir()
    downloaded.write_bytes(b"synthetic program")
    item = {"id": "yt-dlp", "install_path": "yt-dlp"}
    entry = {"os": "any", "arch": "wasm32", "file": "yt-dlp"}
    root = tmp_path / "rt"
    dev_setup.extract_item(item, entry, downloaded, root)
    assert (root / "yt-dlp" / "yt-dlp").read_bytes() == b"synthetic program"
