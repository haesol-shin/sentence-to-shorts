"""`status` reports the model and package items that the development setup installs."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from app.runtime import status
from app.schemas.api import RuntimeItemState
from tests.runtime.support import TARGET, lock_item, make_settings

MODEL_ID = "model-tts-synthetic"
PACKAGE_ID = "package-synthetic"
REVISION = "a" * 40
MODEL_FILES = {"config.json": b"config", "weights/model.bin": b"w" * 32}
WHEEL = b"wheel" * 10


def model_item(revision: str = REVISION) -> dict[str, Any]:
    return {
        "id": MODEL_ID,
        "version": "1.0.0",
        "revision": revision,
        "install_path": "Synthetic-TTS",
        "license": {"spdx": "MIT", "source_url": "https://source.invalid/x"},
        "files": [
            {
                "os": "any",
                "arch": "wasm32",
                "file": name,
                "url": f"https://download.invalid/{name}",
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in MODEL_FILES.items()
        ],
    }


def package_item() -> dict[str, Any]:
    return lock_item(
        PACKAGE_ID, "python-wheels/synthetic", "synthetic-1.0-py3-none-any.whl", WHEEL
    )


def write_model_files(root: Path, item: dict[str, Any], names: list[str] | None = None) -> None:
    for name in list(MODEL_FILES) if names is None else names:
        path = root.joinpath(
            *PurePosixPath(str(item["install_path"])).parts,
            *PurePosixPath(name).parts,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(MODEL_FILES[name])


def write_model_journal(
    settings: Any, item: dict[str, Any], revision: str = REVISION
) -> None:
    path = settings.model_dir / "installed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                str(item["id"]): {
                    "revision": revision,
                    "install_path": item["install_path"],
                    "files": {
                        name: {"bytes": len(data)} for name, data in MODEL_FILES.items()
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def write_package_journal(
    settings: Any, item: dict[str, Any], *, sha256: str | None = None, python: str | None = None
) -> None:
    path = settings.runtime_dir / "packages.installed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                str(item["id"]): {
                    "sha256": sha256 or item["files"][0]["sha256"],
                    "python": python or sys.executable,
                }
            }
        ),
        encoding="utf-8",
    )


def states(settings: Any) -> dict[str, tuple[RuntimeItemState, int]]:
    return {row.id: (row.state, row.bytes) for row in status(settings, TARGET)}


def test_external_status_reports_prepared_models_and_packages(tmp_path: Path) -> None:
    model, package = model_item(), package_item()
    settings = make_settings(tmp_path, [model, package])
    write_model_files(settings.model_dir, model)
    write_model_journal(settings, model)
    write_package_journal(settings, package)

    assert states(settings) == {
        MODEL_ID: (RuntimeItemState.ready, sum(len(data) for data in MODEL_FILES.values())),
        PACKAGE_ID: (RuntimeItemState.ready, len(WHEEL)),
    }


def test_external_status_reports_unprepared_items_as_missing(tmp_path: Path) -> None:
    model, package = model_item(), package_item()
    settings = make_settings(tmp_path, [model, package])

    assert states(settings) == {
        MODEL_ID: (RuntimeItemState.missing, sum(len(data) for data in MODEL_FILES.values())),
        PACKAGE_ID: (RuntimeItemState.missing, len(WHEEL)),
    }


@pytest.mark.parametrize("missing", [False, True])
def test_external_status_reports_a_model_whose_files_do_not_match_as_corrupt(
    tmp_path: Path, missing: bool
) -> None:
    model, package = model_item(), package_item()
    settings = make_settings(tmp_path, [model, package])
    write_model_files(settings.model_dir, model, [] if missing else ["config.json"])
    write_model_journal(settings, model)

    assert states(settings)[MODEL_ID][0] is RuntimeItemState.corrupt


def test_external_status_reports_a_model_with_a_different_size_as_corrupt(tmp_path: Path) -> None:
    model, package = model_item(), package_item()
    settings = make_settings(tmp_path, [model, package])
    write_model_files(settings.model_dir, model)
    weights = settings.model_dir / "Synthetic-TTS" / "weights" / "model.bin"
    weights.write_bytes(b"short")
    write_model_journal(settings, model)

    assert states(settings)[MODEL_ID][0] is RuntimeItemState.corrupt


def test_external_status_reports_a_model_from_another_revision_as_missing(tmp_path: Path) -> None:
    model, package = model_item(), package_item()
    settings = make_settings(tmp_path, [model, package])
    write_model_files(settings.model_dir, model)
    write_model_journal(settings, model, revision="b" * 40)

    assert states(settings)[MODEL_ID][0] is RuntimeItemState.missing


@pytest.mark.parametrize(
    "journal",
    [
        pytest.param({"sha256": "0" * 64}, id="sha256"),
        pytest.param({"python": "/elsewhere/python"}, id="interpreter"),
    ],
)
def test_external_status_reports_a_package_that_does_not_match_as_corrupt(
    tmp_path: Path, journal: dict[str, str]
) -> None:
    model, package = model_item(), package_item()
    settings = make_settings(tmp_path, [model, package])
    write_package_journal(settings, package, **journal)

    assert states(settings)[PACKAGE_ID][0] is RuntimeItemState.corrupt


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("{", id="not-json"),
        pytest.param("[]", id="not-an-object"),
        pytest.param(json.dumps({MODEL_ID: 1}), id="record-not-an-object"),
    ],
)
def test_external_status_counts_a_malformed_journal_as_missing(
    tmp_path: Path, payload: str
) -> None:
    model, package = model_item(), package_item()
    settings = make_settings(tmp_path, [model, package])
    write_model_files(settings.model_dir, model)
    (settings.model_dir / "installed.json").write_text(payload, encoding="utf-8")
    (settings.runtime_dir).mkdir(parents=True, exist_ok=True)
    (settings.runtime_dir / "packages.installed.json").write_text(payload, encoding="utf-8")

    assert states(settings) == {
        MODEL_ID: (RuntimeItemState.missing, sum(len(data) for data in MODEL_FILES.values())),
        PACKAGE_ID: (RuntimeItemState.missing, len(WHEEL)),
    }


def test_external_status_counts_an_unreadable_journal_as_missing(tmp_path: Path) -> None:
    model, package = model_item(), package_item()
    settings = make_settings(tmp_path, [model, package])
    write_model_files(settings.model_dir, model)
    (settings.model_dir / "installed.json").mkdir()
    (settings.runtime_dir / "packages.installed.json").mkdir(parents=True)

    assert states(settings)[MODEL_ID][0] is RuntimeItemState.missing
    assert states(settings)[PACKAGE_ID][0] is RuntimeItemState.missing
