"""The reference caption_box description: read once, retried once, never erasing the rest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.ports import AppError
from app.services.reference.vision import ask
from tests.reference.support import Context, ScriptedLlm

BASE: dict[str, Any] = {"story_structure": "hypothetical", "humor": "light"}
BOX = {"shape": "rounded_plate", "fill": "#112233", "opacity": 0.8, "radius": 24}
OPEN_LIST_BOX = {"shape": "torn_paper", "fill": "#112233", "opacity": 0.8, "radius": 24}


def _ask(llm: ScriptedLlm, tmp_path: Path):  # type: ignore[no-untyped-def]
    return ask(
        llm,
        frames=[b"png"],
        transcript="hello",
        allowed={},
        ctx=Context(job_dir=tmp_path),  # type: ignore[arg-type]
    )


def test_caption_box_is_read_with_the_other_values(tmp_path: Path) -> None:
    llm = ScriptedLlm({**BASE, "caption_box": BOX})
    values = _ask(llm, tmp_path)
    assert values.caption_box is not None
    assert values.caption_box.model_dump() == BOX
    assert values.humor == "light"
    assert len(llm.requests) == 1


def test_missing_caption_box_is_none(tmp_path: Path) -> None:
    assert _ask(ScriptedLlm(BASE), tmp_path).caption_box is None


def test_request_schema_does_not_close_the_shape_list(tmp_path: Path) -> None:
    llm = ScriptedLlm({**BASE, "caption_box": BOX})
    _ask(llm, tmp_path)
    schema = llm.requests[0].output_schema
    assert "enum" not in schema["$defs"]["CaptionBoxDescription"]["properties"]["shape"]


def test_open_list_shape_is_retried_once_and_the_retry_is_used(tmp_path: Path) -> None:
    llm = ScriptedLlm({**BASE, "caption_box": OPEN_LIST_BOX}, {**BASE, "caption_box": BOX})
    values = _ask(llm, tmp_path)
    assert len(llm.requests) == 2
    assert "validation_error" in (llm.requests[1].parts[-1].text or "")
    assert values.caption_box is not None and values.caption_box.shape == "rounded_plate"


def test_box_that_stays_invalid_keeps_the_valid_values(tmp_path: Path) -> None:
    llm = ScriptedLlm(
        {**BASE, "caption_box": OPEN_LIST_BOX}, {**BASE, "caption_box": OPEN_LIST_BOX}
    )
    values = _ask(llm, tmp_path)
    assert len(llm.requests) == 2
    assert values.caption_box is None
    assert values.humor == "light"


def test_invalid_analysis_fields_still_fail_after_one_retry(tmp_path: Path) -> None:
    llm = ScriptedLlm({"humor": "hilarious"}, {"humor": "hilarious"})
    with pytest.raises(AppError) as caught:
        _ask(llm, tmp_path)
    assert caught.value.code == "llm_invalid_output"
    assert len(llm.requests) == 2
