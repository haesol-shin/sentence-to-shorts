"""`GET /runtime` reports the same states as the runtime status function."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.runtime import journal
from app.runtime.lock import host_platform, lock_items, select_file
from app.schemas.job import JobState, Stage
from tests.jobs.support import wait_until
from tests.runtime.support import FakeTransport, lock_item, noise, url_of


def test_runtime_api_reports_a_damaged_install_as_corrupt_like_the_status_function(
    client: TestClient,
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    settings = runtime.settings
    target = host_platform()
    records = {}
    for item in lock_items(settings):
        entry = select_file(item, target)
        if entry is None:
            continue
        relative = f"{item['install_path']}/{entry['file']}"
        path = settings.runtime_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        records[str(item["id"])] = {
            "install_path": item["install_path"],
            "file": entry["file"],
            "sha256": entry["sha256"],
            "files": {relative: 1},
        }
    journal.write(settings.runtime_dir, records)
    ready = client.get("/api/v1/runtime").json()["items"]
    assert {row["id"] for row in ready} == {item.id for item in settings.runtime.items}
    assert {row["state"] for row in ready if row["id"] in records} == {"ready"}

    first = next(iter(records.values()))
    (settings.runtime_dir / next(iter(first["files"]))).write_bytes(b"damaged")
    body = client.get("/api/v1/runtime").json()["items"]
    expected = [(row.id, row.state.value, row.bytes) for row in runtime.runtime_setup.status()]
    assert [(row["id"], row["state"], row["bytes"]) for row in body] == expected
    assert "corrupt" in {row["state"] for row in body}


@pytest.mark.parametrize("bad_hash", [False, True])
def test_runtime_api_prepares_files_through_the_application_worker(
    client: TestClient, bad_hash: bool,
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    target = host_platform()
    blob = noise(100_000, "runtime-api")
    item = lock_item(
        "tool", "tool", "tool.bin", blob,
        os_name=target[0], arch=target[1],
        sha256="0" * 64 if bad_hash else None,
    )
    runtime.settings.runtime = runtime.settings.runtime.model_validate(
        {"schema_version": 1, "items": [item]}
    )
    transport = FakeTransport({url_of(item): blob})
    runtime.runtime_setup.transport = transport

    response = client.post("/api/v1/runtime/prepare")
    assert response.status_code == 202
    job_id = response.json()["id"]
    terminal = {JobState.succeeded, JobState.failed, JobState.cancelled}
    assert wait_until(lambda: runtime.job_store.get(job_id).state in terminal)
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    installed = runtime.settings.runtime_dir / "tool" / "tool.bin"
    states = client.get("/api/v1/runtime").json()["items"]
    if bad_hash:
        assert job["state"] == "failed"
        assert job["error"]["code"] == "model_hash_mismatch"
        assert job["error"]["retryable"] is False
        assert not installed.exists()
        assert states[0]["state"] != "ready"
    else:
        assert job["state"] == "succeeded", job
        assert job["result"] == {"prepared": ["tool"]}
        assert installed.read_bytes() == blob
        assert {record["stage"] for record in job["stages"]} == {
            Stage.model_download.value, Stage.model_verify.value,
        }
        assert states == [{"id": "tool", "state": "ready", "bytes": len(blob)}]
        again = client.post("/api/v1/runtime/prepare")
        assert again.status_code == 202
        next_id = again.json()["id"]
        assert wait_until(lambda: runtime.job_store.get(next_id).state in terminal)
        assert runtime.job_store.get(next_id).state is JobState.succeeded
    assert transport.count == 1


class _Speech:
    def __init__(self, device: str, reason: str) -> None:
        self.device = device
        self.device_reason = reason

    def ready(self) -> list[str]:
        return []

    def device_status(self) -> tuple[str, str]:
        return self.device, self.device_reason

    def close(self) -> None:
        pass


def test_runtime_api_reports_the_device_each_speech_adapter_picked(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    monkeypatch.setattr(runtime, "tts", _Speech("cuda", "detected"))
    monkeypatch.setattr(runtime, "transcriber", _Speech("cpu", "load_failed"))
    body = client.get("/api/v1/runtime").json()
    assert body["speech"] == {
        "tts": {"device": "cuda", "reason": "detected"},
        "asr": {"device": "cpu", "reason": "load_failed"},
    }


class _SteppingSpeech:
    """A read that happens while the device steps down must not mix the two states."""

    device = "cuda"
    device_reason = "load_failed"

    def ready(self) -> list[str]:
        return []

    def device_status(self) -> tuple[str, str]:
        return "cpu", "load_failed"

    def close(self) -> None:
        pass


def test_runtime_api_reads_the_speech_status_as_one_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = client.app.state.runtime  # type: ignore[attr-defined]
    monkeypatch.setattr(runtime, "tts", _SteppingSpeech())
    body = client.get("/api/v1/runtime").json()
    assert body["speech"]["tts"] == {"device": "cpu", "reason": "load_failed"}


def test_21_runtime_status_adds_the_prepare_groups_and_keeps_the_old_fields(
    client: TestClient,
) -> None:
    body = client.get("/api/v1/runtime").json()
    assert {row["id"] for row in body["items"]} >= {"ffmpeg", "model-tts-qwen3-0.6b"}
    groups = body["prepare"]["groups"]
    assert [group["id"] for group in groups] == ["voice", "transcribe", "align_en"]
    assert sum(group["total"] for group in groups) == 4_633_348_419
    assert {group["state"] for group in groups} <= {
        "queued", "downloading", "retrying", "ready", "failed"
    }
    for group in groups:
        assert 0 <= group["done"] <= group["total"]
        assert (group["state"] == "retrying") == (group.get("retry_at") is not None)
