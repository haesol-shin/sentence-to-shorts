"""The bundle holds two environments; these checks pin how the builder makes and gates them."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.runtime.test_packaging import PACKAGING, REPO, build

WORKFLOW = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def make_dist_info(site: Path, name: str, version: str) -> None:
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8"
    )


def test_21_dist_json_names_the_bundled_interpreter_and_the_aligner_folder() -> None:
    payload = build.distribution_settings("release", "python/bin/python3.11")
    assert payload["align_python"] == "python/bin/python3.11"
    assert payload["align_site"] == "align-site"


def test_21_build_info_carries_the_hash_of_the_aligner_lock() -> None:
    info = build.render_build_info(
        commit="a" * 40, os_name="linux", arch="x86_64", profile="release",
        python_version="3.11.18", dry_run=False,
    )
    expected = hashlib.sha256((REPO / "core" / "align_runtime" / "poetry.lock").read_bytes())
    assert info["align_lock_hash"] == expected.hexdigest()
    assert info["align_lock_hash"] != info["lock_hash"]


def test_21_notices_list_the_aligner_packages_in_their_own_section() -> None:
    lock = {"items": []}
    packages = [("pydantic", "2.0.0", "MIT")]
    text = build.render_notices(lock, packages, [("whisperx", "3.4.2", "BSD")])
    assert "## Aligner packages" in text
    assert text.index("| pydantic | 2.0.0 | MIT |") < text.index("## Aligner packages")
    assert text.index("## Aligner packages") < text.index("| whisperx | 3.4.2 | BSD |")
    assert "## Aligner packages" not in build.render_notices(lock, [("pydantic", "2.0.0", "MIT")])


def test_21_pth_file_in_the_aligner_folder_fails_the_build(tmp_path: Path) -> None:
    build.check_no_pth(tmp_path, "align-site")
    (tmp_path / "paths.pth").write_text("../site-packages\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="paths.pth"):
        build.check_no_pth(tmp_path, "align-site")


@pytest.mark.parametrize(
    "entry",
    ["pyannote_audio-3.3.2.dist-info", "torchcodec", "TorchVision-0.23.0.dist-info", "triton"],
)
def test_21_unused_package_in_the_aligner_folder_fails_the_build(
    tmp_path: Path, entry: str
) -> None:
    unused = ("pyannote", "torchcodec", "torchvision", "triton")
    make_dist_info(tmp_path, "torch", "2.8.0+cpu")
    (tmp_path / "whisperx").mkdir()
    build.check_unused_packages(tmp_path, unused)
    (tmp_path / entry).mkdir()
    with pytest.raises(build.BuildError, match="unused packages"):
        build.check_unused_packages(tmp_path, unused)


def test_21_the_unused_names_are_the_ones_the_aligner_installer_declares() -> None:
    installer = build.aligner_installer()
    assert set(installer.UNUSED) >= {"pyannote", "torchcodec", "torchvision", "triton"}


def test_21_torch_version_must_be_the_one_the_environment_lock_pins(tmp_path: Path) -> None:
    lock = tmp_path / "poetry.lock"
    lock.write_text('[[package]]\nname = "torch"\nversion = "2.8.0+cpu"\n', encoding="utf-8")
    site = tmp_path / "site"
    make_dist_info(site, "torch", "2.7.1+cpu")
    with pytest.raises(build.BuildError, match=re.escape("align torch is not 2.8.0+cpu")):
        build.check_torch_version(site, lock, "align")
    (site / "torch-2.7.1+cpu.dist-info" / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: torch\nVersion: 2.8.0+cpu\n", encoding="utf-8"
    )
    assert build.check_torch_version(site, lock, "align") == "2.8.0+cpu"


def test_21_the_two_locks_pin_different_torch_versions() -> None:
    main = build.locked_version(REPO / "core" / "poetry.lock", "torch")
    align = build.locked_version(REPO / "core" / "align_runtime" / "poetry.lock", "torch")
    assert main != align


def test_21_aligner_import_runs_with_a_cleared_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(argv=argv, env=kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(build, "run", fake_run)
    build.check_aligner_import(Path("python"), tmp_path)
    assert seen["argv"][-1] == "import whisperx.alignment"  # type: ignore[index]
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["PYTHONPATH"] == str(tmp_path) and env["PYTHONNOUSERSITE"] == "1"
    assert not {"PATH", "PYTHONHOME", "VIRTUAL_ENV"} & set(env)


def test_21_wheel_that_does_not_match_the_lock_fails_the_build(tmp_path: Path) -> None:
    wheel = tmp_path / "pkg-1-py3-none-any.whl"
    wheel.write_bytes(b"wheel bytes")
    good = {"bytes": 11, "sha256": hashlib.sha256(b"wheel bytes").hexdigest()}
    build.verify_wheel(wheel, good)
    with pytest.raises(build.BuildError, match="does not match"):
        build.verify_wheel(wheel, {**good, "bytes": 12})
    with pytest.raises(build.BuildError, match="does not match"):
        build.verify_wheel(wheel, {**good, "sha256": "0" * 64})


def test_21_package_wheel_downloads_the_lock_entry_and_verifies_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"fake wheel"
    entry = {
        "os": "any", "arch": "wasm32", "file": "qwen_tts-0-py3-none-any.whl",
        "url": "https://example.invalid/qwen_tts-0-py3-none-any.whl",
        "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
    }
    lock = {"items": [{"id": "package-qwen-tts", "files": [entry]}]}

    class Response:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            data, self.data = self.data, b""
            return data

    served = [payload]
    monkeypatch.setattr(
        build.urllib.request, "urlopen", lambda *a, **k: Response(served[0])
    )
    path = build.package_wheel(lock, "package-qwen-tts", "linux", tmp_path)
    assert path.read_bytes() == payload
    served[0] = b"tampered!!"
    with pytest.raises(build.BuildError, match="does not match"):
        build.package_wheel(lock, "package-qwen-tts", "linux", tmp_path)
    with pytest.raises(build.BuildError, match="no wheel"):
        build.package_wheel({"items": []}, "package-qwen-tts", "linux", tmp_path)


def test_21_the_shipped_lock_pins_the_wheel_the_builder_installs() -> None:
    lock = json.loads((REPO / "core" / "config" / "runtime.lock.json").read_text("utf-8"))
    item = next(i for i in lock["items"] if i["id"] == build.QWEN_TTS_ITEM)
    assert item["files"][0]["os"] == "any" and item["files"][0]["file"].endswith(".whl")


def test_21_wheels_install_without_dependencies_or_an_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(build.shutil, "which", lambda name: "/bin/uv")

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(build, "run", fake_run)
    build.install_wheel(tmp_path / "env" / "python", tmp_path / "a.whl")
    assert calls[0][:5] == ["/bin/uv", "pip", "install", "--no-deps", "--no-index"]
    assert calls[0][-1] == str(tmp_path / "a.whl")


def test_21_finish_bundle_writes_the_aligner_fields_and_both_package_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "core" / "config").mkdir(parents=True)
    shutil_copy = (REPO / "core" / "config" / "runtime.lock.json")
    (bundle / "core" / "config" / "runtime.lock.json").write_bytes(shutil_copy.read_bytes())
    site, align = tmp_path / "site", tmp_path / "align"
    make_dist_info(site, "pydantic", "2.0.0")
    make_dist_info(align, "whisperx", "3.4.2")
    args = SimpleNamespace(profile="dev", commit="b" * 40, python_dir=None)
    interpreter = "python/bin/python3.11"
    build.finish_bundle(bundle, args, "linux", "x86_64", "3.11.18", site, align, interpreter)
    dist = json.loads((bundle / "dist.json").read_text("utf-8"))
    assert dist["align_python"] == "python/bin/python3.11" and dist["align_site"] == "align-site"
    notices = (bundle / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
    assert "| pydantic | 2.0.0 |" in notices and "| whisperx | 3.4.2 |" in notices
    info = json.loads((bundle / "build-info.json").read_text("utf-8"))
    assert re.fullmatch(r"[0-9a-f]{64}", info["align_lock_hash"])


def test_21_installer_removes_the_aligner_folder_on_uninstall() -> None:
    text = (PACKAGING / "installer.iss.in").read_text(encoding="utf-8")
    assert 'Type: filesandordirs; Name: "{app}\\align-site"' in text


def step_text(name: str) -> str:
    start = WORKFLOW.index(f"- name: {name}")
    end = WORKFLOW.find("\n      - ", start + 1)
    return WORKFLOW[start : end if end != -1 else len(WORKFLOW)]


def test_21_workflow_passes_voice_only_to_the_release_matrix_legs() -> None:
    smoke = step_text("Install as a new user and start it")
    assert smoke.count("--voice") == 1
    assert 'if [ "${{ matrix.profile }}" = "release" ]' in smoke
    assert "$voice" in smoke


def test_21_workflow_frees_the_bundle_folder_before_the_smoke_run() -> None:
    assert "rm -rf dist" in WORKFLOW
    assert WORKFLOW.index("rm -rf dist") < WORKFLOW.index("packaging/smoke.py")
    after = WORKFLOW[WORKFLOW.index("packaging/smoke.py") :]
    assert "dist/" not in after.replace("dist-", "")


def test_21_workflow_gives_release_legs_a_longer_build_timeout() -> None:
    assert "timeout-minutes: ${{ matrix.profile == 'release' && 150 || 60 }}" in WORKFLOW


def test_21_workflow_actions_stay_pinned_to_full_commits() -> None:
    uses = re.findall(r"uses: (\S+)", WORKFLOW)
    assert uses and all(re.fullmatch(r".+@[0-9a-f]{40}", u) for u in uses)


def test_21_a_marker_for_amd64_also_matches_the_windows_machine_name() -> None:
    from packaging.markers import Marker

    line = (
        'hf-xet==1.8.0 ; platform_machine == "x86_64" or platform_machine == "amd64" '
        'or platform_machine == "arm64" \\\n    --hash=sha256:' + "0" * 64 + "\n"
    )
    marker = line.split(" ; ", 1)[1].split("\\", 1)[0].strip()
    assert Marker(marker).evaluate({"platform_machine": "AMD64"}) is False
    fixed = build.accept_windows_machine(line)
    marker = fixed.split(" ; ", 1)[1].split("\\", 1)[0].strip()
    for machine in ("AMD64", "x86_64", "amd64", "arm64"):
        assert Marker(marker).evaluate({"platform_machine": machine}) is True
    assert Marker(marker).evaluate({"platform_machine": "ppc64le"}) is False
    assert fixed.endswith("--hash=sha256:" + "0" * 64 + "\n")
    assert build.accept_windows_machine("pytest==9.0.0\n") == "pytest==9.0.0\n"
