"""Incremental, content-free evidence for explicitly selected live acceptance runs."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.e2e.support import TERMINAL, Api


class Evidence:
    """Use a new private directory per run; preserve completed work on any later failure."""

    def __init__(self, root: Path) -> None:
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.root = root
        self.events: list[dict[str, Any]] = []
        self.record({"kind": "run", "state": "started"})

    def record(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        rows = ["# Real-provider acceptance", "", "Private evidence; do not publish outputs.", ""]
        for item in self.events:
            if item["kind"] == "job":
                rows.append(
                    f"- Job {item['id']} ({item['job_kind']}): {item['state']}; "
                    f"error={item['error_code']}; usage={json.dumps(item['usage'])}"
                )
            elif item["kind"] == "artifact":
                rows.append(f"- {item['name']}: sha256={item['digest']}; bytes={item['bytes']}")
            else:
                rows.append(f"- {json.dumps(item, ensure_ascii=False)}")
        (self.root / "summary.md").write_text("\n".join(rows) + "\n", encoding="utf-8")

    @contextmanager
    def case(self, name: str) -> Iterator[None]:
        self.record({"kind": "case", "name": name, "state": "running"})
        try:
            yield
        except BaseException:
            self.record({"kind": "case", "name": name, "state": "failed"})
            raise
        else:
            self.record({"kind": "case", "name": name, "state": "passed"})

    def job(self, job: dict[str, Any]) -> None:
        # Never retain input, result, error detail, reference URL, frames or transcript.
        self.record({
            "kind": "job", "id": job["id"], "job_kind": job["kind"],
            "state": job["state"], "attempt": job["attempt"],
            "started_at": job["started_at"], "ended_at": job["ended_at"],
            "error_code": (job["error"] or {}).get("code"),
            "stages": [{key: stage[key] for key in (
                "stage", "state", "started_ms", "ended_ms", "cache_hits", "rebuilt_scene_ids"
            )} for stage in job["stages"]],
            "usage": [{key: usage[key] for key in (
                "stage", "provider", "model", "effort", "input_tokens", "output_tokens",
                "cache_read_tokens", "cache_write_tokens", "wall_ms", "retries"
            )} for usage in job["usage"]],
        })

    def artifact(self, name: str, content: bytes) -> tuple[Path, str]:
        path = self.root / name
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        self.record({"kind": "artifact", "name": name, "digest": digest, "bytes": len(content)})
        return path, digest


class LiveApi(Api):
    def __init__(self, client: TestClient, evidence: Evidence, deadlines: dict[str, int]) -> None:
        self.http = client
        self.evidence = evidence
        self.deadlines = deadlines

    def wait_terminal(self, job: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + self.deadlines[job["kind"]] + 30
        current = job
        try:
            while current["state"] not in TERMINAL:
                assert time.monotonic() < deadline, "acceptance job exceeded its deadline"
                time.sleep(0.5)
                current = self.get(f"/jobs/{job['id']}")
            return current
        finally:
            self.evidence.job(current)

    def wait_job(self, job: dict[str, Any]) -> dict[str, Any]:
        current = self.wait_terminal(job)
        assert current["state"] == "succeeded", (
            current["kind"], current["state"], (current["error"] or {}).get("code")
        )
        return current


def numeric_detail(detail: dict[str, Any]) -> dict[str, int]:
    """Only the measured numbers of an error detail; text from a provider or program is dropped."""
    return {
        key: value for key, value in detail.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
