"""Generated code BGM registration uses the same registry as builtin audio."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.plugins.registry import Registry, RegistryError, file_list_revision
from app.schemas.bgm_entry import BuiltinBgm, CodeBgm
from tests.sandbox.conftest import tone_wav_bytes
from tests.templates.conftest import HostLauncher, bgm_answer, build_harness, program
from tests.templates.scenarios import bgm_request

VALID = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "valid"


def _stage(root: Path) -> Path:
    raw = json.loads((VALID / "bgm_code.json").read_text(encoding="utf-8"))
    staged = root / raw["id"]
    staged.mkdir(parents=True)
    files = {"program.py": program("bgm_arpeggio").encode("utf-8"), "loop.wav": tone_wav_bytes()}
    for name, data in files.items():
        (staged / name).write_bytes(data)
    raw["duration_ms"] = 1000
    raw["sha256"] = hashlib.sha256(files["loop.wav"]).hexdigest()
    raw["program_digest"] = hashlib.sha256(files["program.py"]).hexdigest()
    (staged / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    return staged


def test_bgm_code_generation_is_listed_and_restored_after_restart(tmp_path: Path) -> None:
    harness = build_harness(tmp_path, HostLauncher())
    harness.llm.queue(bgm_answer(program("bgm_arpeggio")))
    ref = harness.service.generate_bgm(bgm_request(), ctx=harness.ctx())
    package = harness.catalog.package_dir("bgm", ref)
    original = harness.catalog.get("bgm", ref.id, ref.revision)
    assert isinstance(original, CodeBgm)
    assert package.parent == tmp_path / "data" / "s"
    assert file_list_revision(package) == ref.revision
    with_wave = (package / original.file).read_bytes()

    restored = Registry(data_dir=tmp_path / "data")
    entry = restored.get("bgm", ref.id)
    assert isinstance(entry, CodeBgm) and entry == original
    assert restored.get("bgm", ref.id, ref.revision) == original
    assert restored.pin("bgm", ref.id) == ref
    assert (restored.package_dir("bgm", ref) / entry.file).read_bytes() == with_wave
    listed = next(item for item in restored.list("bgm") if item.id == ref.id)
    assert listed.revision == ref.revision and listed.origin == "generated"
    assert any(
        isinstance(restored.get("bgm", item.id), BuiltinBgm)
        for item in restored.list("bgm")
    )


@pytest.mark.parametrize("name", ["program.py", "loop.wav"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_bgm_code_rejects_missing_or_changed_package_files(
    tmp_path: Path, name: str, damage: str
) -> None:
    staged = _stage(tmp_path / "staging")
    if damage == "missing":
        (staged / name).unlink()
    else:
        with (staged / name).open("ab") as handle:
            handle.write(b"changed")
    registry = Registry(data_dir=tmp_path / "data")
    before = registry.list("bgm")
    with pytest.raises(RegistryError) as failure:
        registry.register_generated("bgm", staged)
    assert failure.value.code == ("missing_file" if damage == "missing" else "digest_mismatch")
    assert registry.list("bgm") == before
    assert not (tmp_path / "data" / "s").exists()


def test_bgm_code_rejects_a_changed_package_under_the_same_id(tmp_path: Path) -> None:
    registry = Registry(data_dir=tmp_path / "data")
    staged = _stage(tmp_path / "first")
    ref = registry.register_generated("bgm", staged)
    package = registry.package_dir("bgm", ref)
    before = (package / "program.py").read_bytes()
    changed = _stage(tmp_path / "second")
    raw = json.loads((changed / "manifest.json").read_text(encoding="utf-8"))
    raw["seed"] += 1
    (changed / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RegistryError) as failure:
        registry.register_generated("bgm", changed)
    assert failure.value.code == "duplicate_id"
    assert (package / "program.py").read_bytes() == before
    assert file_list_revision(package) == ref.revision


def test_bgm_code_registration_retry_keeps_the_revision(tmp_path: Path) -> None:
    registry = Registry(data_dir=tmp_path / "data")
    ref = registry.register_generated("bgm", _stage(tmp_path / "first"))
    assert registry.register_generated("bgm", _stage(tmp_path / "second")) == ref
    restored = Registry(data_dir=tmp_path / "data")
    assert restored.get("bgm", ref.id, ref.revision).seed == 42


def test_bgm_code_registration_rejects_builtin_source(tmp_path: Path) -> None:
    registry = Registry(data_dir=tmp_path / "data")
    staged = tmp_path / "staged" / "not_generated"
    staged.mkdir(parents=True)
    raw = json.loads((VALID / "bgm_builtin.json").read_text(encoding="utf-8"))
    raw["id"] = staged.name
    (staged / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RegistryError) as failure:
        registry.register_generated("bgm", staged)
    assert failure.value.code == "invalid_manifest"
    assert not (tmp_path / "data" / "s").exists()
