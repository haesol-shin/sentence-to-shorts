"""The aligner environment carries the alignment path and the pinned wheel."""

from __future__ import annotations

import hashlib
import importlib.util
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ALIGN = REPO / "core" / "align_runtime"
SPEC = importlib.util.spec_from_file_location("install_whisperx", ALIGN / "install_whisperx.py")
assert SPEC is not None and SPEC.loader is not None
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def test_install_whisperx_accepts_only_the_pinned_bytes(tmp_path) -> None:
    wheel = tmp_path / "whisperx.whl"
    content = b"synthetic wheel"
    wheel.write_bytes(content)
    pin = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    assert installer.verified(wheel, pin)
    wheel.write_bytes(b"synthetic wheeX")
    assert not installer.verified(wheel, pin)
    wheel.write_bytes(content + b"x")
    assert not installer.verified(wheel, pin)
    wheel.write_bytes(content)
    pin["sha256"] = "0" * 64
    assert not installer.verified(wheel, pin)
    assert not installer.verified(tmp_path / "missing.whl", pin)


def test_install_whisperx_checks_the_alignment_module(monkeypatch) -> None:
    def failing(name: str) -> None:
        assert name == "whisperx.alignment"
        raise ImportError("missing numpy")

    monkeypatch.setattr(installer.importlib, "import_module", failing)
    error = installer.alignment_import_error()
    assert error is not None and "missing numpy" in error
    monkeypatch.setattr(installer.importlib, "import_module", lambda name: None)
    assert installer.alignment_import_error() is None


def test_install_whisperx_check_reports_stale_environment(monkeypatch) -> None:
    monkeypatch.setattr(installer, "unused_packages", lambda: ["pyannote"])
    assert installer.main(["--check"]) == 2
    monkeypatch.setattr(installer, "unused_packages", lambda: [])
    assert installer.main(["--check"]) == 0


def test_install_whisperx_reads_the_pin_from_the_lock() -> None:
    lock = tomllib.loads((ALIGN / "poetry.lock").read_text(encoding="utf-8"))
    whisperx = next(item for item in lock["package"] if item["name"] == "whisperx")
    pin = installer.pinned()
    filename = pin["url"].rsplit("/", 1)[-1]
    hashes = {entry["file"]: entry["hash"] for entry in whisperx["files"]}
    assert pin["name"] == "whisperx"
    assert pin["version"] == whisperx["version"]
    assert hashes[filename] == f"sha256:{pin['sha256']}"
    assert pin["bytes"] > 0


def test_align_runtime_lock_installs_only_the_alignment_path() -> None:
    lock = tomllib.loads((ALIGN / "poetry.lock").read_text(encoding="utf-8"))
    groups = {package["name"]: set(package.get("groups", [])) for package in lock["package"]}
    installed = {name for name, names in groups.items() if "main" in names}
    assert installed.isdisjoint(
        {"pyannote-audio", "torchcodec", "torchvision", "triton", "whisperx"}
    )
    audit = {name for name, names in groups.items() if "audit" in names}
    assert "whisperx" in audit
    assert installer.pinned()["name"] == "whisperx"
