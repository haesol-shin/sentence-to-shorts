"""Model preparation through the app's preparer and the demo-free inference package."""

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

from app.runtime import download, journal
from tests.runtime.support import FakeTransport

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("dev_setup", ROOT / "scripts" / "dev_setup.py")
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)

# Serves a `file:` URL through the downloader's transport interface, so a subprocess can
# install a synthetic wheel without a network. The product transport accepts https only.
FILE_TRANSPORT = """
import app.runtime.download as download
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname
class Response:
    def __init__(self, body, status, headers):
        self.status, self.headers, self._body, self._at = status, headers, body, 0
    def read(self, size):
        chunk = self._body[self._at:self._at + size]
        self._at += len(chunk)
        return chunk
    def close(self):
        pass
class Transport:
    def open(self, url, *, start, timeout):
        body = Path(url2pathname(urlsplit(url).path)).read_bytes()
        if start:
            headers = {"Content-Range": f"bytes {start}-{len(body) - 1}/{len(body)}"}
            return Response(body[start:], 206, headers)
        return Response(body, 200, {})
download.HttpsTransport = Transport
"""


def model_lock(blob: bytes, *, install_path: str = "synthetic", name: str = "codec/weights.bin"):
    return {
        "items": [{
            "id": "model-synthetic",
            "version": "1",
            "revision": "a" * 40,
            "install_path": install_path,
            "files": [{
                "os": "any",
                "arch": "wasm32",
                "file": name,
                "url": f"https://download.invalid/{name}",
                "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
            }],
        }],
    }


def serve(monkeypatch: pytest.MonkeyPatch, lock: dict, blobs: dict[str, bytes]) -> FakeTransport:
    """Make the app preparer's downloader answer from memory."""
    transport = FakeTransport(
        {entry["url"]: blobs[entry["file"]] for item in lock["items"] for entry in item["files"]}
    )
    monkeypatch.setattr(download, "HttpsTransport", lambda: transport)
    return transport


def test_21_dev_setup_installs_models_with_the_app_preparer(tmp_path, monkeypatch) -> None:
    blob = b"synthetic model"
    lock = model_lock(blob)
    root = tmp_path / "models"
    transport = serve(monkeypatch, lock, {"codec/weights.bin": blob})
    assert setup.install_models(lock, root) == ["model-synthetic"]
    installed = root / "synthetic" / "codec" / "weights.bin"
    assert installed.read_bytes() == blob
    record = journal.read(root)["model-synthetic"]
    assert record["files"]["codec/weights.bin"]["sha256"] == hashlib.sha256(blob).hexdigest()
    assert transport.count == 1

    setup.install_models(lock, root)
    assert transport.count == 1
    installed.write_bytes(b"x" * len(blob))
    (root / "installed.json").unlink()
    setup.install_models(lock, root)
    assert installed.read_bytes() == blob
    assert transport.count == 2


def test_21_dev_setup_keeps_the_file_in_place_when_a_download_is_refused(
    tmp_path, monkeypatch
) -> None:
    blob = b"synthetic model"
    lock = model_lock(blob)
    root = tmp_path / "models"
    serve(monkeypatch, lock, {"codec/weights.bin": blob})
    setup.install_models(lock, root)
    changed = model_lock(b"another model", install_path="synthetic")
    changed["items"][0]["revision"] = "b" * 40
    serve(monkeypatch, changed, {"codec/weights.bin": b"corrupt bytes!"})
    with pytest.raises(SystemExit, match="model_hash_mismatch"):
        setup.install_models(changed, root)
    assert (root / "synthetic" / "codec" / "weights.bin").read_bytes() == blob
    assert len(list((root / "synthetic" / "codec").iterdir())) == 1


@pytest.mark.parametrize("location", ["install_path", "file"])
def test_21_dev_setup_refuses_paths_that_leave_the_model_folder(
    tmp_path, monkeypatch, location
) -> None:
    lock = model_lock(b"synthetic model")
    if location == "install_path":
        lock["items"][0][location] = "../escaped"
    else:
        lock["items"][0]["files"][0][location] = "../../escaped.bin"
    serve(monkeypatch, lock, {entry["file"]: b"x" for entry in lock["items"][0]["files"]})
    with pytest.raises(SystemExit):
        setup.install_models(lock, tmp_path / "models")
    assert not (tmp_path / "escaped").exists()
    assert not (tmp_path / "escaped.bin").exists()


def test_21_dev_setup_extracts_a_zip_and_repairs_a_missing_member(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "punkt_tab.zip"
    with zipfile.ZipFile(source, "w") as bundle:
        bundle.writestr("punkt_tab/english/collocations.tab", b"collocations")
        bundle.writestr("punkt_tab/english/sent_starters.txt", b"starters")
    blob = source.read_bytes()
    lock = model_lock(blob, install_path="nltk_data/tokenizers", name="punkt_tab.zip")
    lock["items"][0]["id"] = "model-nltk-punkt-tab"
    root = tmp_path / "models"
    transport = serve(monkeypatch, lock, {"punkt_tab.zip": blob})
    setup.install_models(lock, root)
    english = root / "nltk_data" / "tokenizers" / "punkt_tab" / "english"
    assert (english / "collocations.tab").read_bytes() == b"collocations"
    if os.name != "nt":
        assert (root / "nltk_data").stat().st_mode & 0o077 == 0
    (english / "collocations.tab").unlink()
    setup.install_models(lock, root)
    assert transport.count == 1
    assert (english / "collocations.tab").read_bytes() == b"collocations"


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
        "networkx",
        "hf_xet",
    }
    removed = setup.packages_to_remove(installed, align)
    assert "networkx" in removed
    assert "hf_xet" in removed
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


def test_21_dev_setup_models_are_found_by_the_existing_transcriber(
    tmp_path, monkeypatch
) -> None:
    from app.tools.asr.faster_whisper.adapter import find_model

    lock = json.loads(setup.LOCK.read_text(encoding="utf-8"))
    item = next(item for item in lock["items"] if item["id"] == "model-asr-small")
    blobs = {}
    for entry in item["files"]:
        content = b"synthetic " + entry["file"].encode()
        blobs[entry["file"]] = content
        entry.update(
            url=f"https://download.invalid/{entry['file']}",
            bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
    root = tmp_path / "models"
    serve(monkeypatch, {"items": [item]}, blobs)
    setup.install_models({"items": [item]}, root)
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
    # The script imports the app's preparer, so the app's packages must be importable; the
    # wheel still goes into the isolated environment, the interpreter that runs pip.
    env = os.environ | {
        "APP_RUNTIME_DIR": str(root),
        "PYTHONPATH": os.pathsep.join(site.getsitepackages()),
    }
    command = [
        str(python), "-c",
        "import importlib.util,sys; from pathlib import Path; "
        "sys.path.insert(0, sys.argv[3]); exec(sys.argv[4]); "
        "spec=importlib.util.spec_from_file_location('setup',sys.argv[1]); "
        "setup=importlib.util.module_from_spec(spec); spec.loader.exec_module(setup); "
        "setup.LOCK=Path(sys.argv[2]); setup.main(['--tts-package'])",
        str(ROOT / "scripts" / "dev_setup.py"), str(manifest), str(ROOT / "core"),
        FILE_TRANSPORT,
    ]
    installed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert installed.returncode == 0, installed.stderr[-2000:]
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
    env = os.environ | {
        "APP_RUNTIME_DIR": str(tmp_path / "runtime"),
        "PYTHONPATH": os.pathsep.join(site.getsitepackages()),
    }
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
