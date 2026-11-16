"""Harness shared by the access tests: isolated app plus exact problem/header checks."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.job import Job, JobKind
from app.storage.projects import new_typeid
from tests.conftest import LOOPBACK_CLIENT, browser_client
from tests.jobs.support import new_job

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@dataclass
class AccessEnv:
    settings: Any
    app: FastAPI
    client: TestClient


@contextmanager
def access_env(
    settings: Any,
    *,
    host: str = "127.0.0.1",
    client: tuple[str, int] = LOOPBACK_CLIENT,
) -> Iterator[AccessEnv]:
    """A real app with a browser-shaped client that has not paired yet."""
    from app.bootstrap import build_runtime
    from app.main import create_app

    runtime = build_runtime(settings)
    app = create_app(runtime, pairing_display=lambda _url: None)
    with browser_client(app, settings.port, host=host, client=client) as test_client:
        yield AccessEnv(settings=settings, app=app, client=test_client)


def assert_security_headers(response: Any) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def assert_problem(response: Any, status: int, code: str, *, instance: str | None = None) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == f"https://app.invalid/problems/{code}"
    assert body["title"]
    assert body["status"] == status
    assert body["detail"]
    assert body["instance"] == (instance or response.request.url.path)
    assert body["code"] == code
    assert body["message_key"] == f"error.{code}"
    assert isinstance(body["retryable"], bool)
    assert body["errors"] == []
    assert_security_headers(response)
    return body


def install_draft_submit(monkeypatch: Any, app: FastAPI) -> tuple[Job, list[Any]]:
    """Make POST /videos/{vid}/draft succeed with a synthetic Job."""
    job = new_job(JobKind.draft, video_id=new_typeid("v"))
    calls: list[Any] = []

    def submit(*args: Any, **kwargs: Any) -> Job:
        calls.append((args, kwargs))
        return job

    monkeypatch.setattr(app.state.runtime.submitter, "submit", submit)
    return job, calls


def create_upload_video(client: TestClient) -> dict[str, Any]:
    """A project and its first video at revision 1, created the way the SPA does."""
    project = client.post(
        "/api/v1/projects", json={"title": "Synthetic upload", "language": "en"}
    )
    assert project.status_code == 201, project.text
    video = client.post(
        f"/api/v1/projects/{project.json()['id']}/videos",
        json={"from_video_id": None, "preset_id": None},
    )
    assert video.status_code == 201, video.text
    return video.json()


def install_reference_submit(monkeypatch: Any, app: FastAPI) -> list[Any]:
    """Answer the reference upload route without the jobs lane, recording calls."""
    runtime = app.state.runtime
    calls: list[Any] = []

    def submit(*args: Any, **kwargs: Any) -> Job:
        calls.append((args, kwargs))
        job = new_job(JobKind.reference, video_id=kwargs["video_id"])
        runtime.job_inputs.save(job.id, kwargs["input"])
        return job

    monkeypatch.setattr(runtime.submitter, "submit", submit)
    return calls


def multipart_body(
    fields: Sequence[tuple[str, str]],
    file_data: bytes,
    *,
    boundary: str,
    filename: str = "clip.mp4",
    closing: bool = True,
    content_type: str = "video/mp4",
    file_first: bool = False,
) -> bytes:
    """A multipart/form-data body with the named text fields and one `file` part."""
    text = bytearray()
    for name, value in fields:
        text += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n'
            "\r\n"
            f"{value}\r\n"
        ).encode()
    file = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n"
        "\r\n"
    ).encode()
    body = bytearray()
    if file_first:
        body += file + file_data + b"\r\n" + text
    else:
        body += text + file + file_data + b"\r\n"
    if closing:
        body += f"--{boundary}--\r\n".encode()
    return bytes(body)


def chunked(data: bytes, size: int = 4096) -> Iterator[bytes]:
    for offset in range(0, len(data), size):
        yield data[offset : offset + size]


def multipart_content_type(boundary: str) -> str:
    return f"multipart/form-data; boundary={boundary}"
