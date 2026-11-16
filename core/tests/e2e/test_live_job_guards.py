"""Unknown authentication permits a first job; known missing credentials do not."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ports import AppError


@pytest.mark.parametrize("state", ["unknown", "ok", "missing", "expired"])
def test_10_authentication_state_controls_submission(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    monkeypatch.setattr(runtime.llm, "auth_state", lambda: state)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AppError("llm_auth")

    monkeypatch.setattr(runtime.llm, "complete", refuse)
    project = client.post("/api/v1/projects", json={"title": "Synthetic auth", "language": "en"})
    assert project.status_code == 201
    response = client.post(f"/api/v1/projects/{project.json()['id']}/videos",
                           json={"from_video_id": None, "preset_id": None})
    assert response.status_code == 201
    video = response.json()
    submitted = client.post(f"/api/v1/videos/{video['id']}/draft", json={
        "base_revision": video["revision"], "message": "Explain a greenhouse.", "card_id": None,
    })
    if state in {"missing", "expired"}:
        assert submitted.status_code == 503
        assert submitted.json()["code"] == "llm_auth_required"
        assert client.get("/api/v1/jobs", params={"video_id": video["id"]}).json()["items"] == []
        return
    assert submitted.status_code == 202, submitted.text
    job = submitted.json()
    deadline = time.monotonic() + 10
    while job["state"] not in {"succeeded", "failed", "cancelled"}:
        assert time.monotonic() < deadline, "authentication failure did not terminate the job"
        time.sleep(0.02)
        job = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert job["state"] == "failed" and job["error"]["code"] == "llm_auth"
    head = client.get(f"/api/v1/videos/{video['id']}").json()["video"]
    assert head["revision"] == video["revision"]
