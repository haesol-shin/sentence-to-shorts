"""Verified model preparation and the demo-free official inference package."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import site
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("dev_setup", ROOT / "scripts" / "dev_setup.py")
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def model_lock(source: Path) -> dict:
    content = source.read_bytes()
    return {
        "items": [{
            "id": "model-synthetic",
            "version": "1",
            "revision": "a" * 40,
            "install_path": "synthetic",
            "files": [{
                "file": "codec/weights.bin",
                "url": source.as_uri(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }],
        }],
    }


def archive_lock(source: Path) -> dict:
    content = source.read_bytes()
    return {
        "items": [{
            "id": "model-nltk-punkt-tab",
            "version": "1",
            "revision": "b" * 40,
            "install_path": "nltk_data/tokenizers",
            "files": [{
                "file": "punkt_tab.zip",
                "url": source.as_uri(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }],
        }],
    }


def test_model_prepare_reuses_verified_files_and_repairs_corruption(tmp_path, capsys) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"synthetic model")
    lock = model_lock(source)
    root = tmp_path / "models"
    setup.install_models(lock, root, force=False)
    assert "model downloads: 1" in capsys.readouterr().out
    installed = root / "synthetic" / "codec" / "weights.bin"
    assert installed.read_bytes() == source.read_bytes()
    journal = json.loads((root / "installed.json").read_text())
    assert journal["model-synthetic"]["files"]["codec/weights.bin"]["sha256"] == (
        hashlib.sha256(source.read_bytes()).hexdigest()
    )
    source.rename(tmp_path / "offline.bin")
    setup.install_models(lock, root, force=False)
    assert "model downloads: 0" in capsys.readouterr().out
    (tmp_path / "offline.bin").rename(source)
    installed.write_bytes(b"x" * len(source.read_bytes()))
    setup.install_models(lock, root, force=False)
    assert "model downloads: 1" in capsys.readouterr().out
    assert installed.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("corruption", [b"short", b"x" * len(b"synthetic model")])
def test_model_prepare_rejects_bad_download_without_replacing_file(tmp_path, corruption) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"synthetic model")
    lock = model_lock(source)
    root = tmp_path / "models"
    setup.install_models(lock, root, force=False)
    source.write_bytes(corruption)
    with pytest.raises(SystemExit, match="bytes or sha256 mismatch"):
        setup.install_models(lock, root, force=True)
    assert (root / "synthetic" / "codec" / "weights.bin").read_bytes() == b"synthetic model"
    assert len(list((root / "synthetic" / "codec").iterdir())) == 1


@pytest.mark.parametrize("location", ["install_path", "file"])
def test_model_prepare_rejects_escaping_paths(tmp_path, location) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"synthetic model")
    lock = model_lock(source)
    if location == "install_path":
        lock["items"][0][location] = "../escaped"
    else:
        lock["items"][0]["files"][0][location] = "../../escaped.bin"
    with pytest.raises(SystemExit, match="escapes installation directory"):
        setup.install_models(lock, tmp_path / "models", force=False)
    assert not (tmp_path / "escaped").exists()
    assert not (tmp_path / "escaped.bin").exists()


def test_model_prepare_extracts_a_zip_and_repairs_a_missing_member(tmp_path, capsys) -> None:
    source = tmp_path / "punkt_tab.zip"
    with zipfile.ZipFile(source, "w") as bundle:
        bundle.writestr("punkt_tab/english/collocations.tab", b"collocations")
        bundle.writestr("punkt_tab/english/sent_starters.txt", b"starters")
    lock = archive_lock(source)
    root = tmp_path / "models"
    setup.install_models(lock, root, force=False)
    assert "model downloads: 1" in capsys.readouterr().out
    english = root / "nltk_data" / "tokenizers" / "punkt_tab" / "english"
    assert (english / "collocations.tab").read_bytes() == b"collocations"
    if os.name != "nt":
        assert (root / "nltk_data").stat().st_mode & 0o077 == 0
    source.rename(tmp_path / "offline.zip")
    setup.install_models(lock, root, force=False)
    assert "model downloads: 0" in capsys.readouterr().out
    (english / "collocations.tab").unlink()
    setup.install_models(lock, root, force=False)
    assert "model downloads: 0" in capsys.readouterr().out
    assert (english / "collocations.tab").read_bytes() == b"collocations"
    (tmp_path / "offline.zip").rename(source)


def test_environment_specs_read_the_align_runtime_lock() -> None:
    align = ROOT / "core" / "align_runtime"
    assert setup.direct_requirements(align) == [
        "huggingface-hub",
        "nltk",
        "numpy",
        "pandas",
        "torch",
        "torchaudio",
        "transformers",
    ]
    locked = setup.locked_versions(align)
    assert "whisperx" in locked
    assert locked["torch"] == {"2.8.0+cpu"}


def test_environment_verify_rejects_a_version_outside_the_lock(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "synthetic"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\ndependencies = ["pytest"]\n',
        encoding="utf-8",
    )
    (project / "poetry.lock").write_text(
        '[[package]]\nname = "pytest"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="does not match its poetry.lock"):
        setup.verify_environment(Path(sys.executable), project)


def test_distribution_name_normalizes_separators() -> None:
    assert setup.distribution_name("huggingface_hub") == "huggingface-hub"
    assert setup.distribution_name("Typing.Extensions") == "typing-extensions"


def test_packages_to_remove_keeps_the_main_group_and_wheel() -> None:
    align = ROOT / "core" / "align_runtime"
    installed = {
        "torch",
        "torchaudio",
        "huggingface_hub",
        "transformers",
        "whisperx",
        "pip",
        "pyannote-audio",
        "torchvision",
        "triton",
    }
    removed = setup.packages_to_remove(installed, align)
    assert "pyannote-audio" in removed
    assert "torchvision" in removed
    assert "triton" in removed
    for kept in ("torch", "torchaudio", "huggingface_hub", "transformers", "whisperx", "pip"):
        assert kept not in removed


def test_poetry_environment_ignores_active_venv_and_conda(monkeypatch) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", "/synthetic/venv")
    monkeypatch.setenv("CONDA_PREFIX", "/synthetic/conda")
    env = setup.poetry_environment()
    assert "VIRTUAL_ENV" not in env
    assert "CONDA_PREFIX" not in env


def test_in_project_python_uses_dot_venv(tmp_path) -> None:
    python = setup.in_project_python(tmp_path)
    assert python.parent.parent == tmp_path / ".venv"
    assert python.name in ("python", "python.exe")


def test_environment_install_keeps_each_project_in_its_own_env(tmp_path, monkeypatch) -> None:
    active = Path(sys.prefix)
    monkeypatch.setenv("VIRTUAL_ENV", str(active))
    monkeypatch.setenv("POETRY_VIRTUALENVS_IN_PROJECT", "true")
    projects = []
    for name in ("first", "second"):
        project = tmp_path / name
        project.mkdir()
        (project / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "0.1.0"\n'
            'requires-python = ">=3.11,<3.12"\ndependencies = []\n\n'
            '[tool.poetry]\npackage-mode = false\n',
            encoding="utf-8",
        )
        projects.append(project)
        setup.install_environment(project)
    paths = [setup.environment_python(project) for project in projects]
    assert paths[0] != paths[1]
    assert active not in paths[0].parents
    assert active not in paths[1].parents


def test_model_prepare_is_discoverable_by_the_existing_transcriber(tmp_path) -> None:
    from app.tools.asr.faster_whisper.adapter import find_model

    lock = json.loads(setup.LOCK.read_text(encoding="utf-8"))
    item = next(item for item in lock["items"] if item["id"] == "model-asr-small")
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    for entry in item["files"]:
        source = source_dir / entry["file"]
        content = b"synthetic " + entry["file"].encode()
        source.write_bytes(content)
        entry.update(
            url=source.as_uri(), bytes=len(content), sha256=hashlib.sha256(content).hexdigest()
        )
    root = tmp_path / "models"
    setup.install_models({"items": [item]}, root, force=False)
    prepared = find_model(root)
    assert prepared == root / "faster-whisper-small" / item["revision"]
    assert (prepared / "model.bin").read_bytes() == b"synthetic model.bin"


def test_tts_package_journal_records_only_successful_isolated_installs(tmp_path) -> None:
    wheel = tmp_path / "synthetic_inference-1.0-py3-none-any.whl"
    metadata_dir = "synthetic_inference-1.0.dist-info"
    files = {
        "synthetic_inference.py": 'VERSION = "1.0"\n',
        f"{metadata_dir}/METADATA": (
            "Metadata-Version: 2.1\nName: synthetic-inference\nVersion: 1.0\n"
            "Requires-Dist: synthetic-demo==1.0\n"
        ),
        f"{metadata_dir}/WHEEL": (
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    files[f"{metadata_dir}/RECORD"] = "".join(f"{name},,\n" for name in files) + (
        f"{metadata_dir}/RECORD,,\n"
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    content = wheel.read_bytes()
    entry = {
        "os": "any", "arch": setup.host_arch(), "file": wheel.name,
        "url": wheel.as_uri(), "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    item = {
        "id": "package-qwen-tts", "version": "1.0",
        "revision": hashlib.sha1(content).hexdigest(),
        "install_path": "python-wheels/synthetic", "files": [entry],
    }
    manifest = tmp_path / "lock.json"
    manifest.write_text(json.dumps({"items": [item]}), encoding="utf-8")
    environment = tmp_path / "isolated"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    root = tmp_path / "runtime"
    root.mkdir()
    runtime_journal = root / "installed.json"
    runtime_journal.write_text('{"deno": {"version": "synthetic"}}', encoding="utf-8")
    env = os.environ | {"APP_RUNTIME_DIR": str(root)}
    env.pop("PYTHONPATH", None)
    command = [
        str(python), "-c",
        "import importlib.util,sys; from pathlib import Path; "
        "spec=importlib.util.spec_from_file_location('setup',sys.argv[1]); "
        "setup=importlib.util.module_from_spec(spec); spec.loader.exec_module(setup); "
        "setup.LOCK=Path(sys.argv[2]); setup.main(['--tts-package'])",
        str(ROOT / "scripts" / "dev_setup.py"), str(manifest),
    ]
    subprocess.run(command, env=env, check=True, capture_output=True, text=True, timeout=60)
    journal_path = root / "packages.installed.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    record = journal["package-qwen-tts"]
    assert record["version"] == "1.0"
    assert record["sha256"] == entry["sha256"]
    assert record["bytes"] == entry["bytes"]
    assert Path(record["python"]) == python
    assert json.loads(runtime_journal.read_text()) == {"deno": {"version": "synthetic"}}
    subprocess.run(
        [
            str(python), "-c",
            "import synthetic_inference; assert synthetic_inference.VERSION=='1.0'",
        ],
        env=env, check=True, capture_output=True, text=True, timeout=30,
    )
    wheel.unlink()
    result = subprocess.run(
        command, env=env, check=True, capture_output=True, text=True, timeout=60
    )
    assert "download " not in result.stdout
    wheel.write_bytes(b"invalid wheel")
    entry.update(bytes=wheel.stat().st_size, sha256=setup.sha256(wheel))
    manifest.write_text(json.dumps({"items": [item]}), encoding="utf-8")
    failed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert failed.returncode != 0
    assert json.loads(journal_path.read_text(encoding="utf-8")) == journal


def test_tts_inference_import_does_not_import_gradio(tmp_path) -> None:
    if platform.machine().lower() not in ("x86_64", "amd64"):
        pytest.skip("The locked CPU inference wheels are verified on x86_64 CI only")
    environment = tmp_path / "inference"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    env = os.environ | {"APP_RUNTIME_DIR": str(tmp_path / "runtime")}
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [str(python), str(ROOT / "scripts" / "dev_setup.py"), "--tts-package"],
        env=env, check=True, capture_output=True, text=True, timeout=180,
    )
    probe = '''
import importlib.metadata
import importlib.abc
import json
import sys
from pathlib import Path
sys.path.extend(json.loads(sys.argv[1]))
class NoDemo(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'gradio':
            raise AssertionError('inference attempted to import gradio')
sys.meta_path.insert(0, NoDemo())
import qwen_tts
package_path = Path(qwen_tts.__file__).resolve()
assert package_path.is_relative_to(Path(sys.prefix).resolve()), package_path
distribution = importlib.metadata.distribution('qwen-tts')
assert distribution.version == '0.1.1', distribution.version
assert package_path.is_relative_to(Path(distribution.locate_file('')).resolve()), package_path
from qwen_tts import Qwen3TTSModel
assert callable(Qwen3TTSModel.from_pretrained)
assert not any(name == 'gradio' or name.startswith('gradio.') for name in sys.modules)
print('inference import: no gradio')
'''
    result = subprocess.run(
        [str(python), "-c", probe, json.dumps(site.getsitepackages())], env=env, check=True,
        capture_output=True, text=True, timeout=120,
    )
    assert "inference import: no gradio" in result.stdout
