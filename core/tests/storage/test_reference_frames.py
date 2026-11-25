"""Kept reference frames: project-tree placement, replacement and removal."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.paths import Layout
from app.storage.reference import FileReferenceFrames

PROJECT_ID = "p_06pxfteaw88hs93kkckw5j51ng"
VIDEO_ID = "v_0hzb7bexv28termtt2ypc6trzt"
REFERENCE_ID = "rf_01h2xcejqtf2nbrexx3vqjhp41"


def _store(layout: Layout) -> FileReferenceFrames:
    return FileReferenceFrames(layout)


def test_20_put_keeps_the_frames_next_to_the_video(layout: Layout) -> None:
    store = _store(layout)
    names = store.put(PROJECT_ID, VIDEO_ID, REFERENCE_ID, [b"first", b"second"])

    assert names == ["frame_0.png", "frame_1.png"]
    folder = layout.data / "p" / PROJECT_ID / "v" / VIDEO_ID / "ref" / REFERENCE_ID
    assert sorted(path.name for path in folder.iterdir()) == names
    assert store.get(PROJECT_ID, VIDEO_ID, REFERENCE_ID, names) == [b"first", b"second"]


def test_20_put_replaces_what_the_reference_held(layout: Layout) -> None:
    store = _store(layout)
    store.put(PROJECT_ID, VIDEO_ID, REFERENCE_ID, [b"first", b"second", b"third"])

    names = store.put(PROJECT_ID, VIDEO_ID, REFERENCE_ID, [b"only"])

    assert names == ["frame_0.png"]
    assert store.get(PROJECT_ID, VIDEO_ID, REFERENCE_ID, ["frame_0.png", "frame_1.png"]) == [
        b"only"
    ]
    folder = layout.data / "p" / PROJECT_ID / "v" / VIDEO_ID / "ref" / REFERENCE_ID
    assert [path.name for path in folder.iterdir()] == ["frame_0.png"]


def test_20_prune_keeps_only_the_named_reference(layout: Layout) -> None:
    store = _store(layout)
    other = "rf_01h2xcejqtf2nbrexx3vqjhp42"
    names = store.put(PROJECT_ID, VIDEO_ID, REFERENCE_ID, [b"first"])
    store.put(PROJECT_ID, VIDEO_ID, other, [b"other"])

    store.prune(PROJECT_ID, VIDEO_ID, REFERENCE_ID)

    assert store.get(PROJECT_ID, VIDEO_ID, REFERENCE_ID, names) == [b"first"]
    assert store.get(PROJECT_ID, VIDEO_ID, other, ["frame_0.png"]) == []
    root = layout.reference_root(PROJECT_ID, VIDEO_ID)
    assert [path.name for path in root.iterdir()] == [REFERENCE_ID]


def test_20_prune_without_a_keep_clears_the_video(layout: Layout) -> None:
    store = _store(layout)
    other = "rf_01h2xcejqtf2nbrexx3vqjhp42"
    store.put(PROJECT_ID, VIDEO_ID, REFERENCE_ID, [b"first"])
    store.put(PROJECT_ID, VIDEO_ID, other, [b"other"])

    store.prune(PROJECT_ID, VIDEO_ID, None)

    assert store.get(PROJECT_ID, VIDEO_ID, REFERENCE_ID, ["frame_0.png"]) == []
    assert store.get(PROJECT_ID, VIDEO_ID, other, ["frame_0.png"]) == []
    store.prune(PROJECT_ID, VIDEO_ID, None)


def test_20_get_skips_missing_and_unknown_names(layout: Layout) -> None:
    store = _store(layout)
    store.put(PROJECT_ID, VIDEO_ID, REFERENCE_ID, [b"first", b"second"])

    assert store.get(
        PROJECT_ID, VIDEO_ID, REFERENCE_ID, ["frame_1.png", "frame_9.png", "../project.json"]
    ) == [b"second"]


def test_20_put_refuses_more_than_four_frames(layout: Layout) -> None:
    store = _store(layout)

    with pytest.raises(ValueError):
        store.put(PROJECT_ID, VIDEO_ID, REFERENCE_ID, [b"x"] * 5)


def test_20_paths_use_only_validated_ids(layout: Layout) -> None:
    store = _store(layout)

    with pytest.raises(ValueError):
        store.put(PROJECT_ID, "../escape", REFERENCE_ID, [b"first"])


def test_20_default_layout_puts_frames_under_the_project(tmp_path: Path) -> None:
    layout = Layout(data=tmp_path / "data", cache=tmp_path / "cache")

    assert layout.reference_dir(PROJECT_ID, VIDEO_ID, REFERENCE_ID) == (
        tmp_path / "data" / "p" / PROJECT_ID / "v" / VIDEO_ID / "ref" / REFERENCE_ID
    )
