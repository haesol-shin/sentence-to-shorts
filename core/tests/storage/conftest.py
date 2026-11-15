"""Stores on a fresh state.db under the test's own roots."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.schemas.project import Project
from app.schemas.video import Video
from app.storage.artifacts import FileArtifactStore
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore
from app.storage.sqlite import Database
from tests.conftest import load_json


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return Layout(data=tmp_path / "data", cache=tmp_path / "cache")


@pytest.fixture
def db(layout: Layout) -> Iterator[Database]:
    database = Database.open(layout.state_db)
    yield database
    database.close()


@pytest.fixture
def projects(db: Database, layout: Layout) -> SqliteProjectStore:
    return SqliteProjectStore(db, layout)


@pytest.fixture
def artifacts(db: Database, layout: Layout) -> FileArtifactStore:
    return FileArtifactStore(db, layout)


@pytest.fixture
def project() -> Project:
    return Project.model_validate(load_json("contracts/valid/project_min.json"))


@pytest.fixture
def video() -> Video:
    return Video.model_validate(load_json("contracts/valid/video_ko_just_three.json"))


def next_revision(video: Video) -> Video:
    return video.model_copy(
        update={"revision": video.revision + 1, "parent_revision": video.revision}
    )


def staged(directory: Path, data: bytes, name: str = "out.bin") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    return path
