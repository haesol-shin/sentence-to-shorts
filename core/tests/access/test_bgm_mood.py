"""BGM metadata validation and replay normalization before upload submission."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient
from python_multipart.multipart import MultipartParser

from app.access.idempotency import _MultipartDigest
from app.schemas.job import Job
from tests.access.support import multipart_body
from tests.conftest import load_json

PROJECT_ID = "p_06pxfteaw88hs93kkckw5j51ng"
FILE_BYTES = b"synthetic audio bytes"


@pytest.fixture
def submissions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Isolate the existing submission gap from the real router and middleware."""
    calls: list[bytes] = []
    job = Job.model_validate({**load_json("contracts/valid/job_queued.json"), "kind": "bgm_upload"})

    def submit(project_id: str, upload: Any, key: str | None) -> Job:
        calls.append(upload.stream.read())
        return job

    monkeypatch.setattr(client.app.state.runtime.services.sound, "submit_upload", submit)
    return calls


def _upload(client: TestClient, mood: str | None, key: str = "mood-key-0001") -> Any:
    fields = {"project_id": PROJECT_ID}
    if mood is not None:
        fields["mood"] = mood
    return client.post(
        "/api/v1/bgm/uploads", data=fields,
        files={"file": ("synthetic.wav", FILE_BYTES, "audio/wav")},
        headers={"Idempotency-Key": key},
    )


@pytest.mark.parametrize("mood", [None, "calm", "curious"])
def test_36_upload_accepts_optional_mood_and_replays_the_same_request(
    client: TestClient, submissions: list[bytes], mood: str | None,
) -> None:
    first = _upload(client, mood)
    replay = _upload(client, mood)
    assert first.status_code == replay.status_code == 202
    assert replay.json() == first.json()
    assert submissions == [FILE_BYTES]


@pytest.mark.parametrize("first_mood", [None, "calm"])
def test_36_omitted_mood_and_explicit_calm_share_a_digest(
    client: TestClient, submissions: list[bytes], first_mood: str | None,
) -> None:
    first = _upload(client, first_mood)
    replay = _upload(client, "calm" if first_mood is None else None)
    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert submissions == [FILE_BYTES]


def test_36_same_key_with_another_mood_is_a_conflict(
    client: TestClient, submissions: list[bytes],
) -> None:
    assert _upload(client, None).status_code == 202
    conflict = _upload(client, "curious")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_mismatch"
    assert submissions == [FILE_BYTES]


@pytest.mark.parametrize("mood", ["unknown", "Calm", "null", ""])
def test_36_unknown_mood_is_validation_failed_before_submission(
    client: TestClient, submissions: list[bytes], mood: str,
) -> None:
    response = _upload(client, mood)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert submissions == []


@pytest.mark.parametrize("bgm_upload", [False, True])
def test_36_multipart_default_is_only_part_of_the_bgm_digest(bgm_upload: bool) -> None:
    state = _MultipartDigest(1024)
    parser = MultipartParser(b"synthetic", state.callbacks())
    parser.write(multipart_body([("project_id", PROJECT_ID)], FILE_BYTES, boundary="synthetic"))
    parser.finalize()
    fields = (
        f'{{"mood":"calm","project_id":"{PROJECT_ID}"}}'
        if bgm_upload else f'{{"project_id":"{PROJECT_ID}"}}'
    )
    expected = hashlib.sha256(
        (hashlib.sha256(FILE_BYTES).hexdigest() + fields).encode()
    ).hexdigest()
    assert state.digest(bgm_upload=bgm_upload) == expected


def test_36_upload_route_keeps_the_existing_submission_limit(client: TestClient) -> None:
    response = _upload(client, "curious")
    assert response.status_code == 501
