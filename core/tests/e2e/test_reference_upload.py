"""HTTP upload durability and policy, with workers paused rather than fake analysis."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_runtime
from app.main import create_app
from app.ports import canonical_json
from tests.conftest import browser_client, pair


@pytest.fixture
def queued_client(app_settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app_settings.app.uploads.reference_max_bytes = 8
    runtime = build_runtime(app_settings)
    monkeypatch.setattr(runtime, "start", lambda: None)
    urls: list[str] = []
    app = create_app(runtime, pairing_display=urls.append)
    with browser_client(app, app_settings.port) as client:
        pair(client, urls[0].split("#pair=", 1)[1])
        yield client


@pytest.fixture
def upload_video(queued_client: TestClient) -> dict[str, Any]:
    project = queued_client.post("/api/v1/projects",
                                 json={"title": "Synthetic upload", "language": "en"})
    assert project.status_code == 201
    video = queued_client.post(f"/api/v1/projects/{project.json()['id']}/videos",
                               json={"from_video_id": None, "preset_id": None})
    assert video.status_code == 201
    return video.json()


@pytest.mark.parametrize("revision_text", ["1", "01"])
def test_20_reference_upload_survives_request_close_and_duplicate_submission(
    queued_client: TestClient, upload_video: dict[str, Any], revision_text: str,
) -> None:
    video = upload_video
    content = b"sample00"
    path = f"/api/v1/videos/{video['id']}/references"
    first = queued_client.post(path, data={"base_revision": revision_text},
                                files={"file": ("synthetic.mp4", content, "video/mp4")})
    assert first.status_code == 202, first.text
    job = first.json()
    runtime = queued_client.app.state.runtime  # type: ignore[attr-defined]
    saved = runtime.job_inputs.load(job["id"])
    source = Path(saved["upload_path"])
    assert source.read_bytes() == content
    text = hashlib.sha256(content).hexdigest().encode("ascii") + canonical_json(
        {"base_revision": revision_text}
    )
    assert job["request_digest"] == hashlib.sha256(text).hexdigest()
    second = queued_client.post(path, data={"base_revision": revision_text},
                                 files={"file": ("renamed.mp4", content, "video/mp4")})
    assert second.status_code == 200 and second.json()["id"] == job["id"]
    assert list(source.parent.iterdir()) == [source]
    assert source.read_bytes() == content
    assert "upload_path" not in queued_client.get(f"/api/v1/jobs/{job['id']}").text


@pytest.mark.parametrize(("content", "revision", "status"), [
    (b"", 1, 422), (b"123456789", 1, 413), (b"ok", 2, 409),
])
def test_20_invalid_upload_leaves_no_staged_source(
    queued_client: TestClient, upload_video: dict[str, Any],
    content: bytes, revision: int, status: int,
) -> None:
    response = queued_client.post(f"/api/v1/videos/{upload_video['id']}/references",
        data={"base_revision": str(revision)},
        files={"file": ("synthetic.mp4", content, "video/mp4")})
    assert response.status_code == status, response.text
    runtime = queued_client.app.state.runtime  # type: ignore[attr-defined]
    assert list((runtime.settings.cache_dir / "reference-uploads").glob("*")) == []
    assert runtime.job_store.unfinished() == []


def test_20_hosted_links_are_refused_before_a_job_is_created(
    queued_client: TestClient, upload_video: dict[str, Any]
) -> None:
    runtime = queued_client.app.state.runtime  # type: ignore[attr-defined]
    runtime.settings.deployment = "hosted"
    response = queued_client.post(f"/api/v1/videos/{upload_video['id']}/references/link", json={
        "base_revision": upload_video["revision"],
        "url": "https://www.youtube.com/watch?v=synthetic-reference",
    })
    assert response.status_code == 403 and response.json()["code"] == "link_disabled"
    assert runtime.job_store.unfinished() == []


def test_20_conflicting_upload_preserves_only_the_original_source(
    queued_client: TestClient, upload_video: dict[str, Any],
) -> None:
    path = f"/api/v1/videos/{upload_video['id']}/references"
    first = queued_client.post(path, data={"base_revision": "1"},
                               files={"file": ("synthetic.mp4", b"first", "video/mp4")})
    assert first.status_code == 202
    runtime = queued_client.app.state.runtime  # type: ignore[attr-defined]
    source = Path(runtime.job_inputs.load(first.json()["id"])["upload_path"])
    second = queued_client.post(path, data={"base_revision": "1"},
                                files={"file": ("synthetic.mp4", b"second", "video/mp4")})
    assert second.status_code == 409 and second.json()["code"] == "job_running"
    assert source.read_bytes() == b"first"
    assert list(source.parent.iterdir()) == [source]


def test_20_input_read_failure_after_submit_does_not_delete_the_source(
    queued_client: TestClient, upload_video: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = queued_client.app.state.runtime  # type: ignore[attr-defined]

    def unavailable(job_id: str) -> dict[str, Any]:
        raise OSError("synthetic input read failure")

    with monkeypatch.context() as patch:
        patch.setattr(runtime.job_inputs, "load", unavailable)
        with pytest.raises(OSError, match="synthetic input read failure"):
            queued_client.post(f"/api/v1/videos/{upload_video['id']}/references",
                data={"base_revision": "1"},
                files={"file": ("synthetic.mp4", b"sample00", "video/mp4")})
    jobs = runtime.job_store.unfinished()
    assert len(jobs) == 1
    source = Path(runtime.job_inputs.load(jobs[0].id)["upload_path"])
    assert source.read_bytes() == b"sample00" and source.suffix == ".src"
    assert list(source.parent.glob("*.part")) == []
