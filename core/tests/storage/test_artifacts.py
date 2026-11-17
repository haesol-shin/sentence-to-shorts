"""ArtifactStore: owner-scoped lookup, verified publish, digest checks, holds."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.ports import AppError
from app.schemas.artifact import ArtifactKind
from app.schemas.common import PERSONAL_OWNER_ID
from app.storage import artifacts as artifacts_module
from app.storage.artifacts import ArtifactRejected, FileArtifactStore
from app.storage.paths import Layout
from app.storage.sqlite import Database
from tests.storage.conftest import staged

OWNER = PERSONAL_OWNER_ID
OTHER_OWNER = "u_0hzb7bexv28termtt2ypc6trzt"
KEY_A = "a" * 64
KEY_B = "b" * 64
VIDEO_ID = "v_0hzb7bexv28termtt2ypc6trzt"
JOB_ID = "j_01jg7w6q3z8k4m2v9x5b7c1d3e"


def test_publish_rejects_digest_mismatch(
    artifacts: FileArtifactStore, layout: Layout, tmp_path: Path, monkeypatch
) -> None:
    real = artifacts_module.file_digest
    seen: list[Path] = []

    def changed_after_check(path: Path) -> tuple[str, int]:
        if seen and path.is_relative_to(layout.cache / "a"):
            path.write_bytes(path.read_bytes()[:-1] + b"!")
        seen.append(path)
        return real(path)

    monkeypatch.setattr(artifacts_module, "file_digest", changed_after_check)
    with pytest.raises(ArtifactRejected):
        artifacts.publish(
            OWNER, ArtifactKind.tts_wav, KEY_A, staged(tmp_path / "job", b"RIFF-wave"), {}, JOB_ID
        )
    monkeypatch.setattr(artifacts_module, "file_digest", real)

    assert artifacts.find(OWNER, KEY_A) is None
    assert not any((layout.cache / "a").rglob("*.wav"))


def test_publish_rejects_empty_or_linked_file(
    artifacts: FileArtifactStore, tmp_path: Path
) -> None:
    with pytest.raises(ArtifactRejected):
        artifacts.publish(OWNER, ArtifactKind.srt, KEY_A, staged(tmp_path / "job", b""), {}, None)
    target = staged(tmp_path / "job", b"1\n", name="real.srt")
    link = tmp_path / "job" / "link.srt"
    link.symlink_to(target)
    with pytest.raises(ArtifactRejected):
        artifacts.publish(OWNER, ArtifactKind.srt, KEY_A, link, {}, None)
    assert artifacts.find(OWNER, KEY_A) is None


def test_publish_records_digest_and_moves_file(
    artifacts: FileArtifactStore, tmp_path: Path
) -> None:
    data = b"\x89PNG synthetic"
    tmp = staged(tmp_path / "job", data)
    artifact = artifacts.publish(
        OWNER, ArtifactKind.still_png, KEY_A, tmp, {"width": 1080, "height": 1920}, JOB_ID
    )
    assert not tmp.exists()
    assert artifact.digest == hashlib.sha256(data).hexdigest()
    assert artifact.bytes == len(data)
    assert artifact.owner_id == OWNER
    assert artifact.path.startswith(f"a/{artifact.digest[:2]}/")
    assert artifacts.path(artifact.id).read_bytes() == data
    assert artifacts.find(OWNER, KEY_A) == artifact


def test_artifact_find_is_owner_scoped(
    artifacts: FileArtifactStore, tmp_path: Path
) -> None:
    mine = artifacts.publish(
        OWNER, ArtifactKind.tts_wav, KEY_A, staged(tmp_path / "job", b"RIFF-mine"), {}, None
    )
    theirs = artifacts.publish(
        OTHER_OWNER, ArtifactKind.tts_wav, KEY_A, staged(tmp_path / "job", b"RIFF-theirs"), {}, None
    )
    assert mine.id != theirs.id

    assert artifacts.find(OWNER, KEY_A) == mine
    assert artifacts.find(OTHER_OWNER, KEY_A) == theirs
    assert artifacts.find("u_nobody", KEY_A) is None
    assert artifacts.get(OWNER, mine.id) == mine
    with pytest.raises(AppError) as hidden:
        artifacts.get(OTHER_OWNER, mine.id)
    assert hidden.value.code == "not_found"


def test_find_skips_digest_mismatch(
    artifacts: FileArtifactStore, tmp_path: Path
) -> None:
    damaged = artifacts.publish(
        OWNER, ArtifactKind.tts_wav, KEY_A, staged(tmp_path / "job", b"RIFF-one"), {}, None
    )
    path = artifacts.path(damaged.id)
    path.write_bytes(b"RIFF-two")
    assert artifacts.find(OWNER, KEY_A) is None

    missing = artifacts.publish(
        OWNER, ArtifactKind.tts_wav, KEY_B, staged(tmp_path / "job", b"RIFF-three"), {}, None
    )
    artifacts.path(missing.id).unlink()
    assert artifacts.find(OWNER, KEY_B) is None

    again = artifacts.publish(
        OWNER, ArtifactKind.tts_wav, KEY_A, staged(tmp_path / "job", b"RIFF-one"), {}, None
    )
    assert artifacts.find(OWNER, KEY_A) == again


def test_sweep_keeps_held_artifacts(artifacts: FileArtifactStore, tmp_path: Path) -> None:
    held = artifacts.publish(
        OWNER, ArtifactKind.clip_mp4, KEY_A, staged(tmp_path / "job", b"clip-a"), {}, None
    )
    loose = artifacts.publish(
        OWNER, ArtifactKind.clip_mp4, KEY_B, staged(tmp_path / "job", b"clip-b"), {}, None
    )
    artifacts.hold([held.id], f"rev:{VIDEO_ID}:3")
    artifacts.hold([held.id], f"undo:{VIDEO_ID}")

    assert artifacts.sweep() == 1
    assert artifacts.find(OWNER, KEY_A) == held
    assert artifacts.find(OWNER, KEY_B) is None
    assert not (tmp_path / "cache" / loose.path).exists()

    artifacts.release(f"rev:{VIDEO_ID}:3")
    assert artifacts.sweep() == 0
    artifacts.release(f"undo:{VIDEO_ID}")
    assert artifacts.sweep() == 1
    assert artifacts.find(OWNER, KEY_A) is None


def test_hold_rejects_unknown_holder_or_artifact(
    artifacts: FileArtifactStore, tmp_path: Path
) -> None:
    artifact = artifacts.publish(
        OWNER, ArtifactKind.srt, KEY_A, staged(tmp_path / "job", b"1\n"), {}, None
    )
    with pytest.raises(ValueError):
        artifacts.hold([artifact.id], "anyone")
    with pytest.raises(AppError) as unknown:
        artifacts.hold([artifact.id, "a_01jg7w6q3z8k4m2v9x5b7c1d3e"], f"undo:{VIDEO_ID}")
    assert unknown.value.code == "not_found"
    assert artifacts.sweep() == 1


def test_restart_reuses_published_artifact(layout: Layout, tmp_path: Path) -> None:
    first = Database.open(layout.state_db)
    published = FileArtifactStore(first, layout).publish(
        OWNER, ArtifactKind.tts_wav, KEY_A, staged(tmp_path / "job", b"RIFF-kept"), {}, JOB_ID
    )
    # No close: the next open stands in for a start after a forced stop.
    second = Database.open(layout.state_db)
    try:
        assert FileArtifactStore(second, layout).find(OWNER, KEY_A) == published
    finally:
        second.close()
        first.close()


def test_download_path_copies_newest_held_final(
    artifacts: FileArtifactStore, layout: Layout, tmp_path: Path
) -> None:
    with pytest.raises(AppError) as missing:
        artifacts.download_path(OWNER, VIDEO_ID, "mp4")
    assert missing.value.code == "not_built"

    old = artifacts.publish(
        OWNER, ArtifactKind.final_mp4, KEY_A, staged(tmp_path / "job", b"mp4-old"), {}, None
    )
    new = artifacts.publish(
        OWNER, ArtifactKind.final_mp4, KEY_B, staged(tmp_path / "job", b"mp4-new"), {}, None
    )
    artifacts.hold([old.id], f"rev:{VIDEO_ID}:9")
    artifacts.hold([new.id], f"rev:{VIDEO_ID}:10")

    path = artifacts.download_path(OWNER, VIDEO_ID, "mp4")
    assert path == layout.output_file(VIDEO_ID, new.id, "mp4")
    assert path.read_bytes() == b"mp4-new"
    with pytest.raises(AppError) as hidden:
        artifacts.download_path(OTHER_OWNER, VIDEO_ID, "mp4")
    assert hidden.value.code == "not_built"


def test_job_dir_is_created_under_cache(artifacts: FileArtifactStore, layout: Layout) -> None:
    path = artifacts.job_dir(JOB_ID)
    assert path == layout.cache / "j" / JOB_ID
    assert path.is_dir()
    with pytest.raises(ValueError):
        artifacts.job_dir("../outside")
