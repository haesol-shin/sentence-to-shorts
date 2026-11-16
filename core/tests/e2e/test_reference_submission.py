"""Reference requests must reach the queued job boundary, not a 501 stub."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_20_reference_link_is_accepted_as_a_background_job(client: TestClient) -> None:
    project_response = client.post(
        "/api/v1/projects", json={"title": "Synthetic reference", "language": "en"}
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    video_response = client.post(
        f"/api/v1/projects/{project_id}/videos",
        json={"from_video_id": None, "preset_id": None},
    )
    assert video_response.status_code == 201
    video = video_response.json()
    response = client.post(
        f"/api/v1/videos/{video['id']}/references/link",
        json={
            "base_revision": video["revision"],
            "url": "https://www.youtube.com/watch?v=synthetic-reference",
        },
    )
    assert response.status_code == 202, response.text
    job = response.json()
    persisted = client.get(f"/api/v1/jobs/{job['id']}")
    assert persisted.status_code == 200
    assert persisted.json()["kind"] == "reference"
    assert persisted.json()["video_id"] == video["id"]
    assert "url" not in persisted.json()
