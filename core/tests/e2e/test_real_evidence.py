"""Private evidence must omit content and retain completed work after failure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.schemas.job import Stage
from tests.e2e.real_support import Evidence, numeric_detail


def _job() -> dict[str, Any]:
    return {
        "id": "synthetic-job", "kind": "draft", "state": "failed", "attempt": 1,
        "started_at": "2026-01-01T00:00:00Z", "ended_at": "2026-01-01T00:00:01Z",
        "input": {"url": "https://private.invalid/synthetic-input", "text": "private-source-text"},
        "result": {"transcript": "private-transcript"},
        "error": {"code": "llm_quota", "detail": {"token": "private-key-value"}},
        "stages": [{"stage": Stage.llm_draft.value, "state": "failed", "started_ms": 10,
                    "ended_ms": 20, "cache_hits": 0, "rebuilt_scene_ids": []}],
        "usage": [{"stage": Stage.llm_draft.value, "provider": "openai_compat",
                   "model": "synthetic-model", "effort": "low", "input_tokens": None,
                   "output_tokens": None,
                   "cache_read_tokens": None, "cache_write_tokens": None,
                   "wall_ms": 10, "retries": 0}],
    }


def test_10_evidence_records_usage_and_timings_without_private_content(tmp_path: Path) -> None:
    evidence = Evidence(tmp_path / "evidence")
    evidence.job(_job())
    events = [
        json.loads(line) for line in (evidence.root / "events.jsonl").read_text().splitlines()
    ]
    record = events[-1]
    assert record["usage"][0]["provider"] == "openai_compat"
    assert record["usage"][0]["model"] == "synthetic-model"
    assert record["usage"][0]["cache_write_tokens"] is None
    assert "cost_usd" not in record["usage"][0]
    assert record["stages"][0]["ended_ms"] - record["stages"][0]["started_ms"] == 10
    rendered = "".join(path.read_text() for path in evidence.root.iterdir())
    for private in (
        "private.invalid", "private-source-text", "private-transcript", "private-key-value"
    ):
        assert private not in rendered
    assert "llm_quota" in rendered


def test_1_later_failure_preserves_completed_artifact_and_digest(tmp_path: Path) -> None:
    evidence = Evidence(tmp_path / "evidence")
    content = b"synthetic-video-bytes"
    path, digest = evidence.artifact("synthetic.mp4", content)
    with pytest.raises(AssertionError, match="quota failure"):
        with evidence.case("second-video"):
            evidence.job(_job())
            raise AssertionError("quota failure")
    assert path.read_bytes() == content
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    summary = (evidence.root / "summary.md").read_text()
    assert digest in summary and "llm_quota" in summary
    events = [
        json.loads(line) for line in (evidence.root / "events.jsonl").read_text().splitlines()
    ]
    assert events[-1] == {"kind": "case", "name": "second-video", "state": "failed"}


def test_numeric_detail_keeps_measured_numbers_only() -> None:
    detail = {
        "reason": "color_only", "head_iou_x1000": 912, "flag": True,
        "message": "Traceback with private text", "threshold_iou_x1000": 800,
    }
    assert numeric_detail(detail) == {"head_iou_x1000": 912, "threshold_iou_x1000": 800}
