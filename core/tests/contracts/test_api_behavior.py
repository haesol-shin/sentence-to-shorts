"""Public endpoints work in the fixture profile; the rest answer with a problem body."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.ports import AppError
from app.schemas.api import CsrfResponse
from app.schemas.job import Job
from tests.conftest import browser_client, load_json, pair


def test_health_is_real(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "0.1.0"
    assert body["profile"] == "fixture"
    assert body["deployment"] == "local"


def test_runtime_reports_brand_and_items(client: TestClient) -> None:
    response = client.get("/api/v1/runtime")
    assert response.status_code == 200
    body = response.json()
    assert body["brand"]["display_name_en"]
    assert body["llm_auth"] == {"adapter": "fixture", "state": "ok"}
    assert {item["id"] for item in body["items"]} == {
        "deno",
        "ffmpeg",
        "pyodide-core",
        "pyodide-pillow",
        "package-qwen-tts",
        "model-tts-qwen3-0.6b",
        "model-align-ko",
        "model-align-en",
        "model-asr-small",
    }


def test_catalog_lists_three_format_cards(client: TestClient) -> None:
    response = client.get("/api/v1/catalog/format_card")
    assert response.status_code == 200
    body = response.json()
    assert {item["id"] for item in body["items"]} == {"just_three", "its_like", "what_if"}
    assert body["next_cursor"] is None


def test_runtime_items_need_their_own_files(client: TestClient) -> None:
    settings = client.app.state.runtime.settings  # type: ignore[attr-defined]
    base = settings.runtime_dir
    base.mkdir(parents=True, exist_ok=True)
    journal = {
        item.id: {
            "install_path": item.install_path,
            "file": item.files[0].file,
            "sha256": item.files[0].sha256,
        }
        for item in settings.runtime.items
    }
    (base / "installed.json").write_text(json.dumps(journal), encoding="utf-8")
    (base / "deno").mkdir()
    (base / "pyodide").mkdir()
    states = {
        item["id"]: item["state"]
        for item in client.get("/api/v1/runtime").json()["items"]
    }
    assert set(states.values()) == {"missing"}

    (base / "pyodide" / "pyodide.asm.wasm").write_bytes(b"")
    (base / "pyodide" / "python_stdlib.zip").write_bytes(b"")
    wheel = journal["pyodide-pillow"]["file"]
    (base / "pyodide" / wheel).mkdir()
    states = {
        item["id"]: item["state"]
        for item in client.get("/api/v1/runtime").json()["items"]
    }
    assert states["pyodide-core"] == "ready"
    assert states["pyodide-pillow"] == "missing"
    assert states["deno"] == "missing"

    wheel_path = base / "pyodide" / wheel
    wheel_path.rmdir()
    wheel_path.write_bytes(b"")
    states = {
        item["id"]: item["state"]
        for item in client.get("/api/v1/runtime").json()["items"]
    }
    assert states["pyodide-pillow"] == "ready"


def test_catalog_serves_the_first_typing_key_as_the_sample(client: TestClient) -> None:
    manifest = client.get("/api/v1/catalog/sfx/typing_keys")
    assert manifest.status_code == 200
    keys = manifest.json()["keys"]
    first = keys[0]["file"]
    response = client.get(f"/api/v1/catalog/sfx/typing_keys/media/{first}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    missing = client.get(f"/api/v1/catalog/sfx/typing_keys/media/{keys[1]['file']}")
    assert missing.status_code == 404


def test_catalog_returns_a_real_manifest(client: TestClient) -> None:
    response = client.get("/api/v1/catalog/template/fixed_stage")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "fixed_stage"
    assert body["regions"]["caption"]["y"] == 1040


def test_unknown_catalog_id_returns_problem_404(client: TestClient) -> None:
    response = client.get("/api/v1/catalog/template/missing_template")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"


def test_unknown_path_returns_problem_404(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 404


def test_invalid_request_returns_problem_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/projects",
        json={"title": "x"},
        headers={"Idempotency-Key": "req-0123456789"},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "validation_failed"


def test_unknown_job_and_video_return_problem_404(client: TestClient) -> None:
    for path in ("/api/v1/jobs/j_missing", "/api/v1/videos/v_missing/metrics"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


def test_unhandled_error_returns_problem_500(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    store = client.app.state.runtime.project_store  # type: ignore[attr-defined]

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(store, "list_projects", boom)
    settings = client.app.state.runtime.settings  # type: ignore[attr-defined]
    raw = browser_client(client.app, settings.port, raise_server_exceptions=False)
    pair(raw)
    response = raw.get("/api/v1/projects")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "internal"
    assert "synthetic failure" not in body["detail"]


def test_submit_receives_the_validated_body(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    seen: dict = {}

    def capture(kind, **kwargs):  # type: ignore[no-untyped-def]
        seen["kind"] = kind
        seen.update(kwargs)
        return Job.model_validate(load_json("contracts/valid/job_queued.json"))

    monkeypatch.setattr(runtime.submitter, "submit", capture)
    body = {"base_revision": 1, "message": "합성 주제", "card_id": None}
    response = client.post(
        "/api/v1/videos/v_0par6gpzwz995r49419ne1gwxd/draft",
        json=body,
        headers={"Idempotency-Key": "req-0123456789"},
    )
    assert response.status_code == 202
    assert seen["input"] == body
    assert "input" not in response.json()


def test_csrf_reissue_matches_a_valid_session(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    token = "a" * 32
    monkeypatch.setattr(runtime.access, "csrf", lambda headers: CsrfResponse(csrf_token=token))
    response = client.get("/api/v1/session/csrf")
    assert response.status_code == 200
    assert response.json() == {"csrf_token": token}


def test_csrf_reissue_without_a_session_is_401(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runtime = client.app.state.runtime  # type: ignore[attr-defined]

    def reject(headers):  # type: ignore[no-untyped-def]
        raise AppError("unauthenticated")

    monkeypatch.setattr(runtime.access, "csrf", reject)
    response = client.get("/api/v1/session/csrf")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert response.headers["content-type"].startswith("application/problem+json")


def test_uploads_pass_file_streams_to_services(
    client: TestClient, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    # Park execution so each staged upload stays readable for the assertion.
    runtime.runner.stop()
    staged_seen: list[Path] = []
    sound_seen: list[bytes] = []

    def capture_sound(project_id, upload, key):  # type: ignore[no-untyped-def]
        sound_seen.append(upload.stream.read())
        raise NotImplementedError

    monkeypatch.setattr(runtime.services.sound, "submit_upload", capture_sound)

    project = client.post(
        "/api/v1/projects", json={"title": "Synthetic upload", "language": "en"}
    )
    assert project.status_code == 201
    for content in (b"first-bytes", b"second-bytes"):
        video = client.post(
            f"/api/v1/projects/{project.json()['id']}/videos",
            json={"from_video_id": None, "preset_id": None},
        )
        assert video.status_code == 201
        response = client.post(
            f"/api/v1/videos/{video.json()['id']}/references",
            data={"base_revision": "1"},
            files={"file": ("same.mp4", content, "video/mp4")},
        )
        assert response.status_code == 202, response.text
        saved = runtime.job_inputs.load(response.json()["id"])
        assert saved is not None
        staged_seen.append(Path(saved["upload_path"]))
        response = client.post(
            "/api/v1/bgm/uploads",
            data={"project_id": "p_synthetic"},
            files={"file": ("same.wav", content, "audio/wav")},
        )
        assert response.status_code == 501
    assert len(set(staged_seen)) == 2
    assert [path.read_bytes() for path in staged_seen] == [
        b"first-bytes",
        b"second-bytes",
    ]
    assert sound_seen == [b"first-bytes", b"second-bytes"]
