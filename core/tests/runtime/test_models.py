"""Model preparation: resume, verification, paths, disk, zip repair and the need groups."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import tomllib
from pathlib import Path
from typing import Any

import pytest

from app.jobs import CancelFlag
from app.ports import AppError, Cancelled
from app.runtime import fsutil, journal
from app.runtime.lock import all_lock_items, model_items
from app.runtime.models import (
    GROUP_MODELS,
    GROUP_ORDER,
    GROUP_PACKAGES,
    fetch_locked_file,
    group_bytes,
    group_items,
    hf_source,
    prepare_models,
)
from app.runtime.prepare import Hooks, status
from app.schemas.api import RuntimeItemState
from app.settings import Settings
from tests.runtime.support import (
    FakeTransport,
    Flag,
    make_settings,
    make_zip,
    model_item,
    noise,
    served,
)

ROOT = Path(__file__).resolve().parents[3]
TARGET = ("linux", "x86_64")
HF_REVISION = "a" * 40


def states(model_root: Path, items: list[dict[str, Any]]) -> list[RuntimeItemState]:
    settings = make_settings(model_root.parent, items)
    settings.model_dir = model_root
    return [row.state for row in status(settings, TARGET)]


def test_21_model_download_resumes_from_the_partial_file(tmp_path: Path) -> None:
    blobs = {"weights.bin": noise(4_000, "weights"), "config.json": b'{"k": 1}'}
    item = model_item("model-synthetic", "synthetic", blobs)
    transport = FakeTransport(served(item, blobs), fail_after=[1_500])
    root = tmp_path / "models"
    with pytest.raises(AppError) as lost:
        prepare_models(root, [item], cancel=Flag(), transport=transport, target=TARGET)
    assert lost.value.code == "download_failed"
    assert states(root, [item]) == [RuntimeItemState.missing]
    assert (root / "synthetic" / "weights.bin.part").stat().st_size == 1_500

    ready = prepare_models(root, [item], cancel=Flag(), transport=transport, target=TARGET)
    assert ready == ["model-synthetic"]
    weights, config = (entry["url"] for entry in item["files"])
    assert transport.opens == [(weights, 0), (weights, 1_500), (config, 0)]
    assert (root / "synthetic" / "weights.bin").read_bytes() == blobs["weights.bin"]
    assert states(root, [item]) == [RuntimeItemState.ready]


def test_21_a_bad_download_is_refused_and_the_file_in_place_stays(tmp_path: Path) -> None:
    good = noise(2_000, "good")
    item = model_item("model-synthetic", "synthetic", {"weights.bin": good})
    root = tmp_path / "models"
    prepare_models(
        root,
        [item],
        cancel=Flag(),
        transport=FakeTransport(served(item, {"weights.bin": good})),
        target=TARGET,
    )
    changed = model_item("model-synthetic", "synthetic", {"weights.bin": noise(2_000, "next")})
    changed["revision"] = "c" * 40
    corrupt = noise(2_000, "corrupt")
    with pytest.raises(AppError) as refused:
        prepare_models(
            root,
            [changed],
            cancel=Flag(),
            transport=FakeTransport(served(changed, {"weights.bin": corrupt})),
            target=TARGET,
        )
    assert refused.value.code == "model_hash_mismatch"
    folder = root / "synthetic"
    assert (folder / "weights.bin").read_bytes() == good
    assert sorted(path.name for path in folder.iterdir()) == ["weights.bin"]


@pytest.mark.parametrize("where", ["install_path", "file"])
def test_21_a_path_that_leaves_the_model_folder_is_refused(tmp_path: Path, where: str) -> None:
    blobs = {"weights.bin": b"synthetic"}
    item = model_item("model-synthetic", "synthetic", blobs)
    if where == "install_path":
        item["install_path"] = "../escaped"
    else:
        item["files"][0]["file"] = "../../escaped.bin"
    transport = FakeTransport({entry["url"]: b"synthetic" for entry in item["files"]})
    with pytest.raises(AppError) as refused:
        prepare_models(
            tmp_path / "models", [item], cancel=Flag(), transport=transport, target=TARGET
        )
    assert refused.value.code in ("download_blocked", "model_missing")
    assert transport.count == 0
    assert not (tmp_path / "escaped").exists()
    assert not (tmp_path / "escaped.bin").exists()


def test_21_a_full_disk_stops_before_the_download_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blobs = {"weights.bin": noise(3_000, "big")}
    item = model_item("model-synthetic", "synthetic", blobs)
    transport = FakeTransport(served(item, blobs))
    monkeypatch.setattr(fsutil, "disk_free", lambda path: 1_000)
    with pytest.raises(AppError) as full:
        prepare_models(
            tmp_path / "models", [item], cancel=Flag(), transport=transport, target=TARGET
        )
    assert full.value.code == "disk_full"
    assert transport.count == 0


def test_21_a_zip_item_extracts_and_repairs_a_missing_member_without_network(
    tmp_path: Path,
) -> None:
    blob = make_zip(
        {
            "punkt_tab/english/collocations.tab": b"collocations",
            "punkt_tab/english/sent_starters.txt": b"starters",
        }
    )
    item = model_item("model-nltk-punkt-tab", "nltk_data/tokenizers", {"punkt_tab.zip": blob})
    transport = FakeTransport(served(item, {"punkt_tab.zip": blob}))
    root = tmp_path / "models"
    prepare_models(root, [item], cancel=Flag(), transport=transport, target=TARGET)
    english = root / "nltk_data" / "tokenizers" / "punkt_tab" / "english"
    assert (english / "collocations.tab").read_bytes() == b"collocations"
    if sys.platform != "win32":
        # Windows reports a fixed mode; the private-folder rule is a POSIX one.
        assert (root / "nltk_data").stat().st_mode & 0o077 == 0
    opened = transport.count

    (english / "collocations.tab").unlink()
    prepare_models(root, [item], cancel=Flag(), transport=transport, target=TARGET)
    assert transport.count == opened
    assert (english / "collocations.tab").read_bytes() == b"collocations"


def test_21_the_journal_keeps_the_shape_the_development_script_wrote(tmp_path: Path) -> None:
    blobs = {"weights.bin": noise(500, "w"), "sub/config.json": b"{}"}
    item = model_item("model-synthetic", "synthetic", blobs)
    root = tmp_path / "models"
    prepare_models(
        root,
        [item],
        cancel=Flag(),
        transport=FakeTransport(served(item, blobs)),
        target=TARGET,
    )
    record = journal.read(root)["model-synthetic"]
    assert record == {
        "version": "1",
        "revision": "b" * 40,
        "install_path": "synthetic",
        "files": {
            name: {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
            for name, blob in blobs.items()
        },
    }

    # A folder the development script prepared earlier needs no network.
    transport = FakeTransport({})
    ready = prepare_models(root, [item], cancel=Flag(), transport=transport, target=TARGET)
    assert ready == ["model-synthetic"] and transport.count == 0


def test_21_progress_counts_the_files_already_in_place(tmp_path: Path) -> None:
    blobs = {"a.bin": noise(1_000, "a"), "b.bin": noise(3_000, "b")}
    item = model_item("model-synthetic", "synthetic", blobs)
    root = tmp_path / "models"
    folder = root / "synthetic"
    folder.mkdir(parents=True)
    (folder / "a.bin").write_bytes(blobs["a.bin"])
    seen: list[tuple[int, int]] = []
    prepare_models(
        root,
        [item],
        cancel=Flag(),
        transport=FakeTransport(served(item, blobs)),
        hooks=Hooks(progress=lambda done, total: seen.append((done, total))),
        target=TARGET,
    )
    assert seen[0] == (1_000, 4_000)
    assert seen[-1] == (4_000, 4_000)
    assert all(done >= 1_000 for done, _total in seen)


def test_21_a_model_is_downloading_while_it_is_fetched(tmp_path: Path) -> None:
    blobs = {"weights.bin": noise(2_000, "d")}
    item = model_item("model-synthetic", "synthetic", blobs)
    root = tmp_path / "models"
    during: list[RuntimeItemState] = []

    def probe(done: int, total: int) -> None:
        during.extend(states(root, [item]))

    prepare_models(
        root,
        [item],
        cancel=Flag(),
        transport=FakeTransport(served(item, blobs)),
        hooks=Hooks(progress=probe),
        target=TARGET,
    )
    assert RuntimeItemState.downloading in during
    assert states(root, [item]) == [RuntimeItemState.ready]


# --- the Hugging Face client path -----------------------------------------------------


def hf_item(blobs: dict[str, bytes]) -> dict[str, Any]:
    return model_item(
        "model-hf",
        "hf-model",
        blobs,
        base=f"https://huggingface.co/owner/repo/resolve/{HF_REVISION}",
    )


class FakeHub:
    """Stands in for `hf_hub_download`: writes into `local_dir` like the client does."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, repo_id: str, filename: str, revision: str, local_dir: Path) -> str:
        self.calls.append((repo_id, filename, revision))
        target = local_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.blobs[filename])
        return str(target)


def test_21_a_hugging_face_file_goes_through_the_client_and_is_verified(tmp_path: Path) -> None:
    blobs = {"model.bin": noise(2_500, "hf"), "speech/config.json": b'{"a": 1}'}
    item = hf_item(blobs)
    hub = FakeHub(blobs)
    transport = FakeTransport({})
    root = tmp_path / "models"
    prepare_models(root, [item], cancel=Flag(), transport=transport, hf=hub, target=TARGET)
    assert hub.calls == [
        ("owner/repo", "model.bin", HF_REVISION),
        ("owner/repo", "speech/config.json", HF_REVISION),
    ]
    assert transport.count == 0
    assert (root / "hf-model" / "speech" / "config.json").read_bytes() == b'{"a": 1}'
    assert not (root / ".tmp").exists()
    assert states(root, [item]) == [RuntimeItemState.ready]


def test_21_a_hugging_face_file_with_the_wrong_hash_is_dropped_and_refused(
    tmp_path: Path,
) -> None:
    blobs = {"model.bin": noise(1_000, "hf")}
    item = hf_item(blobs)
    root = tmp_path / "models"
    with pytest.raises(AppError) as refused:
        prepare_models(
            root,
            [item],
            cancel=Flag(),
            hf=FakeHub({"model.bin": noise(1_000, "other")}),
            target=TARGET,
        )
    assert refused.value.code == "model_hash_mismatch"
    assert not (root / "hf-model" / "model.bin").exists()
    assert not (root / ".tmp").exists()


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (ConnectionError("reset"), "download_failed"),
        (TimeoutError("slow"), "download_failed"),
        (OSError(28, "No space left on device"), "disk_full"),
        (TypeError("a bug"), "internal"),
    ],
)
def test_21_client_errors_become_job_error_codes(
    tmp_path: Path, raised: BaseException, code: str
) -> None:
    item = hf_item({"model.bin": b"x" * 10})

    def failing(repo_id: str, filename: str, revision: str, local_dir: Path) -> str:
        raise raised

    with pytest.raises(AppError) as error:
        prepare_models(tmp_path / "models", [item], cancel=Flag(), hf=failing, target=TARGET)
    assert error.value.code == code


def test_21_a_missing_remote_file_is_a_permanent_error(tmp_path: Path) -> None:
    from huggingface_hub import errors

    item = hf_item({"model.bin": b"x" * 10})

    def gone(repo_id: str, filename: str, revision: str, local_dir: Path) -> str:
        raise errors.EntryNotFoundError("no such file")

    with pytest.raises(AppError) as error:
        prepare_models(tmp_path / "models", [item], cancel=Flag(), hf=gone, target=TARGET)
    assert error.value.code == "model_missing"


def test_21_an_unreachable_hub_is_a_lost_connection_not_a_missing_file(
    tmp_path: Path,
) -> None:
    from huggingface_hub import errors

    item = hf_item({"model.bin": b"x" * 10})

    def offline(repo_id: str, filename: str, revision: str, local_dir: Path) -> str:
        raise errors.LocalEntryNotFoundError("cannot reach the hub and the file is not local")

    with pytest.raises(AppError) as error:
        prepare_models(tmp_path / "models", [item], cancel=Flag(), hf=offline, target=TARGET)
    assert error.value.code == "download_failed"


def test_21_a_cancelled_client_download_is_joined_by_the_next_job(tmp_path: Path) -> None:
    blobs = {"model.bin": noise(1_000, "slow")}
    item = hf_item(blobs)
    release = threading.Event()
    calls = []

    def slow(repo_id: str, filename: str, revision: str, local_dir: Path) -> str:
        calls.append(filename)
        assert release.wait(10)
        target = local_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blobs[filename])
        return str(target)

    root = tmp_path / "models"
    flag = CancelFlag()
    timer = threading.Timer(0.3, flag.cancel)
    timer.start()
    with pytest.raises(Cancelled):
        prepare_models(root, [item], cancel=flag, hf=slow, target=TARGET)
    timer.join()
    # The client cannot be interrupted, so the first call is still running; a second job
    # waits for it instead of starting another writer on the same partial file.
    threading.Timer(0.3, release.set).start()
    prepare_models(root, [item], cancel=Flag(), hf=slow, target=TARGET)
    assert calls == ["model.bin"]
    assert states(root, [item]) == [RuntimeItemState.ready]


def test_21_only_hugging_face_resolve_urls_use_the_client() -> None:
    assert hf_source(f"https://huggingface.co/o/r/resolve/{HF_REVISION}/a/b.bin") == (
        "o/r",
        HF_REVISION,
        "a/b.bin",
    )
    assert hf_source("https://download.pytorch.org/torchaudio/models/x.pth") is None
    assert hf_source("https://raw.githubusercontent.com/o/r/abc/x.zip") is None
    assert hf_source(f"http://huggingface.co/o/r/resolve/{HF_REVISION}/x") is None


def test_21_a_file_outside_hugging_face_uses_the_resumable_downloader(tmp_path: Path) -> None:
    blob = noise(1_200, "plain")
    entry = {
        "url": "https://download.invalid/x.pth",
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
    }
    transport = FakeTransport({entry["url"]: blob})

    def never(*args: object) -> str:
        raise AssertionError("the client must not be used")

    final = tmp_path / "x.pth"
    assert fetch_locked_file(
        entry, final, staging=tmp_path / ".tmp", cancel=Flag(), transport=transport, hf=never
    )
    assert final.read_bytes() == blob


# --- the group table and the lock -----------------------------------------------------


def test_21_every_model_item_is_in_exactly_one_group() -> None:
    lock = [
        item["id"]
        for item in json.loads((ROOT / "core/config/runtime.lock.json").read_text())["items"]
        if item["id"].startswith("model-")
    ]
    listed = [name for group in GROUP_ORDER for name in GROUP_MODELS[group]]
    assert sorted(listed) == sorted(lock)
    assert len(set(listed)) == len(listed)
    assert set(GROUP_PACKAGES) <= set(GROUP_ORDER)


def test_21_group_sizes_add_up_to_the_locked_model_bytes() -> None:
    items = all_lock_items(Settings())
    wanted = sum(
        int(entry["bytes"])
        for item in model_items(Settings())
        for entry in item["files"]
        if entry["os"] == "any"
    )
    assert sum(group_bytes(items, group, TARGET) for group in GROUP_ORDER) == wanted
    assert [item["id"] for item in group_items(items, "voice")] == list(GROUP_MODELS["voice"])


def test_21_hugging_face_urls_of_the_lock_name_the_locked_revision() -> None:
    for item in model_items(Settings()):
        for entry in item["files"]:
            source = hf_source(str(entry["url"]))
            if source is not None:
                assert source[1] == item["revision"], item["id"]


def test_21_the_client_and_its_transfer_library_are_locked() -> None:
    lock = tomllib.loads((ROOT / "core" / "poetry.lock").read_text(encoding="utf-8"))
    names = {package["name"] for package in lock["package"]}
    assert {"huggingface-hub", "hf-xet"} <= names
    project = tomllib.loads((ROOT / "core" / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(
        requirement.startswith("huggingface-hub")
        for requirement in project["project"]["dependencies"]
    )
