"""Validated job input survives a restart in server-only storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.job_inputs import LocalJobInputStore

JOB_ID = "j_01jg7w6q3z8k4m2v9x5b7c1d3e"


def test_job_input_survives_a_restart(tmp_path: Path) -> None:
    root = tmp_path / "j"
    payload = {
        "message": "합성 주제: 고양이가 컵을 쏟는 이유",
        "base_revision": 3,
        "scene_ids": ["s_01jg7w6q3z8k4m2v9x5b7c1d3e"],
    }
    LocalJobInputStore(root).save(JOB_ID, payload)
    restarted = LocalJobInputStore(root)
    assert restarted.load(JOB_ID) == payload


def test_missing_job_input_is_reported_as_none(tmp_path: Path) -> None:
    assert LocalJobInputStore(tmp_path / "j").load(JOB_ID) is None


def test_job_id_cannot_escape_the_root(tmp_path: Path) -> None:
    store = LocalJobInputStore(tmp_path / "j")
    with pytest.raises(ValueError):
        store.save("../../outside", {})
    with pytest.raises(ValueError):
        store.load("../../outside")
