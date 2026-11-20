"""Uploaded and code BGM are served from the BGM routes, to their owner only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.schemas.common import PinnedRef
from tests.conftest import load_json
from tests.fixtures.media import tone_wav

PROJECT_ID = "p_06pxfteaw88hs93kkckw5j51ng"
OTHER_PROJECT_ID = "p_0cvg4rwzzp8zp90cpp9shhp80x"


def _register(
    client: TestClient, tmp_path: Path, fixture: str, item_id: str, **fields: Any
) -> PinnedRef:
    raw = load_json(f"contracts/valid/{fixture}.json")
    if raw["source"] == "upload":
        raw["file"] = f"{item_id}.wav"
    staged = tmp_path / "staging" / item_id
    staged.mkdir(parents=True)
    wav = tone_wav(staged / raw["file"], duration_ms=1000).read_bytes()
    raw.update(id=item_id, duration_ms=1000, sha256=hashlib.sha256(wav).hexdigest(), **fields)
    if raw["source"] == "code":
        program = b"def render_loop(params, seed):\n    return b''\n"
        (staged / raw["program"]).write_bytes(program)
        raw["program_digest"] = hashlib.sha256(program).hexdigest()
    else:
        raw.update(channels=1, upload_id=item_id, accepted_at="2026-11-14T12:00:00Z")
    (staged / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    return client.app.state.runtime.catalog.register_generated("bgm", staged)


@pytest.mark.parametrize(
    ("fixture", "item_id", "fields"),
    [
        ("bgm_upload", "u_0cvg4rwzzp8zp90cpp9shhp80x", {"project_id": PROJECT_ID}),
        ("bgm_code", "code_synthetic", {}),
    ],
)
def test_bgm_audio_serves_uploaded_and_code_tracks_as_wav(
    client: TestClient, tmp_path: Path, fixture: str, item_id: str, fields: dict[str, Any]
) -> None:
    _register(client, tmp_path, fixture, item_id, **fields)
    response = client.get(f"/api/v1/bgm/{item_id}/audio")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert client.get(f"/api/v1/catalog/bgm/{item_id}").status_code == 200
    name = "loop.wav" if fixture == "bgm_code" else f"{item_id}.wav"
    media = client.get(f"/api/v1/catalog/bgm/{item_id}/media/{name}")
    assert media.status_code == 200
    assert media.content == response.content


def test_bgm_audio_hides_another_owners_upload(client: TestClient, tmp_path: Path) -> None:
    item_id = "u_0cvg4rwzzp8zp90cpp9shhp80x"
    _register(
        client, tmp_path, "bgm_upload", item_id, project_id=PROJECT_ID, owner_id="someone_else"
    )
    assert client.get(f"/api/v1/bgm/{item_id}/audio").status_code == 404
    assert client.get(f"/api/v1/catalog/bgm/{item_id}").status_code == 404
    assert client.get(f"/api/v1/catalog/bgm/{item_id}/media/{item_id}.wav").status_code == 404
    listed = client.get("/api/v1/catalog/bgm?limit=50").json()["items"]
    assert item_id not in {item["id"] for item in listed}


def test_bgm_list_shows_an_upload_to_its_own_project_only(
    client: TestClient, tmp_path: Path
) -> None:
    project = client.post("/api/v1/projects", json={"title": "Synthetic BGM", "language": "en"})
    assert project.status_code == 201
    video = client.post(
        f"/api/v1/projects/{project.json()['id']}/videos",
        json={"from_video_id": None, "preset_id": None},
    )
    assert video.status_code == 201
    mine = "u_0cvg4rwzzp8zp90cpp9shhp80x"
    theirs = "u_0cvg4rwzzp8zp90cpp9shhp80y"
    _register(client, tmp_path, "bgm_upload", mine, project_id=project.json()["id"])
    _register(client, tmp_path, "bgm_upload", theirs, project_id=OTHER_PROJECT_ID)
    everything = client.get("/api/v1/catalog/bgm?limit=50").json()["items"]
    assert {mine, theirs} <= {item["id"] for item in everything}
    scoped = client.get(f"/api/v1/catalog/bgm?limit=50&video_id={video.json()['id']}")
    ids = {item["id"] for item in scoped.json()["items"]}
    assert mine in ids and theirs not in ids
