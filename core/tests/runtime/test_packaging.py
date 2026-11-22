"""Packaging inputs: brand-only names, notices, build info, profiles, tarball, start script."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.ports import canonical_digest
from app.runtime.launcher import adapter_choices, read_distribution
from app.schemas.common import PERSONAL_OWNER_ID

REPO = Path(__file__).resolve().parents[3]
PACKAGING = REPO / "packaging"


def load_build() -> ModuleType:
    spec = importlib.util.spec_from_file_location("packaging_build", PACKAGING / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["packaging_build"] = module
    spec.loader.exec_module(module)
    return module


build = load_build()
BRAND = {
    "app_id": "zz9id",
    "display_name_ko": "시험 표시 이름",
    "display_name_en": "Sample Display",
    "repository": "sample-repo",
}


def test_packaging_installer_script_takes_every_name_from_the_brand_values(tmp_path: Path) -> None:
    script = build.render_installer_script(BRAND, "9.8.7", tmp_path / "bundle", tmp_path / "out")
    assert "AppId=zz9id" in script
    assert "AppName=시험 표시 이름" in script
    assert r"DefaultDirName={localappdata}\Programs\zz9id\9.8.7" in script
    assert "PrivilegesRequired=lowest" in script
    assert not re.search(r"@[A-Z_]+@", script)


def test_packaging_template_rejects_a_placeholder_nobody_filled() -> None:
    with pytest.raises(build.BuildError):
        build.render_template("Name=@MISSING_NAME@", {"OTHER": "x"})


def test_packaging_files_hold_no_brand_name() -> None:
    brand = build.read_brand()
    names = {value for key, value in brand.items() if value and value != "app"}
    for path in PACKAGING.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".json", ".sh", ".in", ".md"}:
            text = path.read_text(encoding="utf-8")
            for name in names:
                assert name not in text, f"{path.name} contains a brand name"


def test_packaging_notices_file_matches_the_runtime_lock() -> None:
    lock = json.loads((REPO / "core" / "config" / "runtime.lock.json").read_text("utf-8"))
    lock = build.lock_with_ffmpeg(lock, "linux-x86_64")
    text = build.render_notices(lock)
    assert (REPO / "THIRD_PARTY_NOTICES.md").read_text("utf-8") == text
    assert "| ffmpeg | 9.0.2 | GPL-3.0-or-later |" in text
    for item in lock["items"]:
        assert f"| {item['id']} | {item['version']} | {item['license']['spdx']} |" in text
    assert "\u2014" not in text


def test_packaging_ffmpeg_pins_are_complete_and_the_shipped_lock_swaps_the_contract_item() -> None:
    pin = json.loads((PACKAGING / "ffmpeg.lock.json").read_text("utf-8"))
    assert set(pin["builds"]) == {"linux-x86_64", "linux-aarch64", "windows-x86_64"}
    for label, build_pin in pin["builds"].items():
        assert label == f"{build_pin['os']}-{build_pin['arch']}"
        for key in ("archive_sha256", "sha256"):
            assert re.fullmatch(r"[0-9a-f]{64}", build_pin[key])
        assert build_pin["url"].startswith("https://")
        assert build_pin["bytes"] > 0 and build_pin["archive_bytes"] > 0
        assert "/" in build_pin["member"] and build_pin["license_members"]
    contract = json.loads((REPO / "core" / "config" / "runtime.lock.json").read_text("utf-8"))
    development = [item for item in contract["items"] if item["id"] == "ffmpeg"]
    assert len(development) == 1
    shipped = build.lock_with_ffmpeg(contract, "linux-x86_64")
    ffmpeg = [item for item in shipped["items"] if item["id"] == "ffmpeg"]
    assert len(ffmpeg) == 1 and len(shipped["items"]) == len(contract["items"])
    (entry,) = ffmpeg[0]["files"]
    linux = pin["builds"]["linux-x86_64"]
    assert (entry["url"], entry["sha256"], entry["file"]) == (
        linux["url"], linux["archive_sha256"], linux["member"],
    )
    assert ffmpeg[0] != development[0]
    others = [item for item in contract["items"] if item["id"] != "ffmpeg"]
    assert [item for item in shipped["items"] if item["id"] != "ffmpeg"] == others


@pytest.mark.parametrize("label", ["linux-x86_64", "linux-aarch64", "windows-x86_64"])
def test_packaging_shipped_lock_lets_the_media_adapter_find_the_bundled_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str,
) -> None:
    from app.settings import RuntimeFile
    from app.tools.media import adapter as media

    contract = json.loads((REPO / "core" / "config" / "runtime.lock.json").read_text("utf-8"))
    monkeypatch.setattr(media, "_platform", lambda: tuple(label.split("-")))
    shipped = build.lock_with_ffmpeg(contract, label)
    settings = SimpleNamespace(runtime_dir=tmp_path, runtime=RuntimeFile.model_validate(shipped))
    path = media.runtime_executable(settings)
    build_pin = json.loads((PACKAGING / "ffmpeg.lock.json").read_text("utf-8"))["builds"][label]
    assert path == (tmp_path / "ffmpeg" / Path(*build_pin["member"].split("/"))).resolve()


def test_packaging_gpl_text_ships_with_the_ffmpeg_pin() -> None:
    text = (PACKAGING / "licenses" / "GPL-3.0.txt").read_text("utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text


def test_packaging_corresponding_source_pins_the_exact_shipped_ffmpeg_executables() -> None:
    pin = json.loads((PACKAGING / "ffmpeg.lock.json").read_text("utf-8"))
    manifest = json.loads((PACKAGING / "ffmpeg-sources.lock.json").read_text("utf-8"))
    assert set(manifest["builds"]) == set(pin["builds"])
    for label, shipped in pin["builds"].items():
        source = manifest["builds"][label]
        for key in ("url", "archive_bytes", "archive_sha256", "member", "bytes", "sha256"):
            assert source["binary"][key] == shipped[key], f"{label} {key}"
        assert source["revision"] == pin["revision"]
        assert source["sources"], f"{label} has no source archives"
        for name in source["sources"]:
            assert name in manifest["artifacts"], f"{label} names unknown artifact {name}"
    text = build.render_notices({"items": []})
    for label in pin["builds"]:
        assert f"`{build.corresponding_source.asset_name(label)}`" in text


def test_packaging_notices_in_a_distribution_list_the_python_packages() -> None:
    lock = json.loads((REPO / "core" / "config" / "runtime.lock.json").read_text("utf-8"))
    text = build.render_notices(lock, [("pydantic", "2.0.0", "MIT")])
    assert "| pydantic | 2.0.0 | MIT |" in text


def test_packaging_build_info_digest_matches_the_app_digest() -> None:
    lock = json.loads((REPO / "core" / "config" / "runtime.lock.json").read_text("utf-8"))
    info = build.render_build_info(
        commit="a" * 40, os_name="linux", arch="x86_64", profile="release",
        python_version="3.11.18", dry_run=False,
    )
    assert info["runtime_manifest_digest"] == canonical_digest(lock)
    assert re.fullmatch(r"[0-9a-f]{64}", str(info["lock_hash"]))
    assert info["commit"] == "a" * 40 and info["dry_run"] is False


def write_generated_dist(root: Path, profile: str) -> None:
    """Write the distribution file the builder produces for one default profile."""
    (root / "dist.json").write_text(
        json.dumps(build.distribution_settings(profile, "python/bin/python3.11"), indent=2)
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("distribution", ["release", "dev"])
def test_packaging_generated_distribution_has_its_default_and_every_profile_choice(
    tmp_path: Path, distribution: str
) -> None:
    write_generated_dist(tmp_path, distribution)
    dist = read_distribution(tmp_path)
    assert dist is not None
    assert dist.profile == distribution and dist.deployment == "local"
    assert set(dist.profile_adapters) == {"dev", "release", "fixture"}


@pytest.mark.parametrize("distribution", ["release", "dev"])
@pytest.mark.parametrize(
    ("profile", "adapter"),
    [("release", "anthropic_api"), ("dev", "openai_compat"), ("fixture", "fixture")],
)
def test_packaging_profiles_select_the_effective_llm_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    distribution: str, profile: str, adapter: str,
) -> None:
    from app.bootstrap import ADAPTER_FACTORIES
    from app.settings import Settings

    monkeypatch.setenv("APP_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    write_generated_dist(tmp_path, distribution)
    dist = read_distribution(tmp_path)
    monkeypatch.setenv("APP_PROFILE", profile)
    settings = Settings()
    settings.providers.adapters.update(adapter_choices(dist, settings.profile, os.environ))
    assert settings.providers.adapters["llm"] == adapter
    built = ADAPTER_FACTORIES["llm"][adapter](settings)
    assert built.auth_state(PERSONAL_OWNER_ID) in {"ok", "missing", "expired", "unknown"}


def test_packaging_python_lock_pins_one_hashed_interpreter_per_platform() -> None:
    lock = json.loads((PACKAGING / "python.lock.json").read_text("utf-8"))
    assets = lock["python"]["assets"]
    assert set(assets) == {"linux-x86_64", "windows-x86_64"}
    for asset in assets.values():
        assert asset["url"].startswith("https://") and asset["bytes"] > 0
        assert re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])
        assert lock["python"]["version"] in asset["name"]
    assert set(lock["tools"]) == {"uv", "poetry", "poetry-plugin-export"}


def test_packaging_bundled_runtime_items_exist_in_the_shipped_runtime_lock() -> None:
    wanted = json.loads((PACKAGING / "bundle.json").read_text("utf-8"))["bundled_runtime_items"]
    lock = json.loads((REPO / "core" / "config" / "runtime.lock.json").read_text("utf-8"))
    shipped = build.lock_with_ffmpeg(lock, "linux-x86_64")
    assert set(wanted) <= {item["id"] for item in shipped["items"]}


def test_packaging_names_a_developer_build_apart_from_a_release_build() -> None:
    assert build.bundle_name(BRAND, "1.2.3", "linux", "x86_64") == "zz9id-1.2.3-linux-x86_64"
    dev = build.bundle_name(BRAND, "1.2.3", "windows", "x86_64", "dev")
    assert dev == "zz9id-1.2.3-windows-x86_64-dev"


def test_packaging_checksums_file_lists_name_and_digest(tmp_path: Path) -> None:
    first, second = tmp_path / "b.txt", tmp_path / "a.txt"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    build.write_sums([first, second], tmp_path / "SHA256SUMS")
    lines = (tmp_path / "SHA256SUMS").read_text("utf-8").splitlines()
    assert [line.split("  ")[1] for line in lines] == ["a.txt", "b.txt"]
    assert lines[1].split("  ")[0] == build.sha256_file(first)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX tar modes")
def test_packaging_tarball_keeps_the_executable_bit_of_the_start_script(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle-name"
    (bundle / "python" / "bin").mkdir(parents=True)
    start = bundle / "start.sh"
    start.write_text("#!/bin/sh\n", encoding="utf-8")
    start.chmod(0o755)
    (bundle / "python" / "bin" / "python3.11").write_text("x", encoding="utf-8")
    (bundle / "python" / "bin" / "python3.11").chmod(0o755)
    archive = build.make_tarball(bundle, tmp_path)
    with tarfile.open(archive) as tar:
        modes = {member.name: member.mode for member in tar.getmembers()}
    assert modes["bundle-name/start.sh"] & stat.S_IXUSR
    assert modes["bundle-name/python/bin/python3.11"] & stat.S_IXUSR


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell script")
def test_packaging_start_script_finds_its_folder_without_any_command_on_path(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "한글 폴더 이름"
    (folder / "python" / "bin").mkdir(parents=True)
    shutil.copy2(PACKAGING / "start.sh", folder / "start.sh")
    interpreter = folder / "python" / "bin" / "python3.11"
    interpreter.write_text('#!/bin/sh\necho "$0|$1|$2"\n', encoding="utf-8")
    interpreter.chmod(0o755)
    (folder / "launch.py").write_text("", encoding="utf-8")
    done = subprocess.run(
        [str(folder / "start.sh"), "--no-browser"],
        env={"PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == f"{interpreter}|{folder / 'launch.py'}|--no-browser"
    assert os.access(PACKAGING / "start.sh", os.X_OK)
