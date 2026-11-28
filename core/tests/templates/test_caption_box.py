"""Caption box code and place routes on the host launcher (no runtime needed)."""

from __future__ import annotations

import pytest

from app.ports import AppError
from app.schemas.caption_style_manifest import CaptionStyleManifest
from app.schemas.video import CaptionBoxDescription
from tests.templates.conftest import Harness, caption_box_answer, program

REFERENCE_BOX = CaptionBoxDescription(
    shape="bubble_tail", fill="#ffffff", opacity=1.0, radius=24
)


def _plate_source(harness: Harness) -> str:
    ref = harness.catalog.pin("caption_style", "plate")
    return (harness.catalog.package_dir("caption_style", ref) / "program.py").read_text(
        encoding="utf-8"
    )


def test_new_box_is_registered_as_a_generated_caption_style(harness: Harness) -> None:
    harness.llm.queue(caption_box_answer(program("caption_round")))
    ref = harness.service.generate_caption_box(
        "둥근 말풍선으로", harness.video(), ctx=harness.ctx()
    )
    manifest = harness.catalog.get("caption_style", ref.id, ref.revision)
    assert isinstance(manifest, CaptionStyleManifest)
    assert manifest.origin == "generated" and manifest.status == "ready"
    assert manifest.renderer.entry == "draw_caption_box"
    package = harness.catalog.package_dir("caption_style", ref)
    assert (package / "program.py").read_text(encoding="utf-8") == program("caption_round")
    data = harness.llm.data(0)
    assert data["instruction"] == "둥근 말풍선으로"
    assert data["reference_box"] is None
    assert data["previous_code"] == _plate_source(harness)
    assert len(data["test_plates"]) == 2


def test_word_edit_sends_the_pinned_program_as_previous_code(harness: Harness) -> None:
    harness.llm.queue(caption_box_answer(program("caption_round")))
    first = harness.service.generate_caption_box("둥글게", harness.video(), ctx=harness.ctx())
    video = harness.video()
    video.settings.caption.style = first
    harness.llm.queue(caption_box_answer(program("caption_round")))
    harness.service.generate_caption_box("조금 더 크게", video, ctx=harness.ctx())
    assert harness.llm.data(1)["previous_code"] == program("caption_round")


def test_reference_box_is_a_description_without_previous_code(harness: Harness) -> None:
    harness.llm.queue(caption_box_answer(program("caption_round")))
    harness.service.generate_caption_box(
        "", harness.video(), reference_box=REFERENCE_BOX, ctx=harness.ctx()
    )
    data = harness.llm.data(0)
    assert data["reference_box"] == REFERENCE_BOX.model_dump()
    assert data["previous_code"] is None


def test_failed_run_is_repaired_with_the_failure_and_previous_code(harness: Harness) -> None:
    bad = program("caption_tiny_text_area")
    harness.llm.queue(caption_box_answer(bad), caption_box_answer(program("caption_round")))
    harness.service.generate_caption_box("둥글게", harness.video(), ctx=harness.ctx())
    assert len(harness.llm.requests) == 2
    repair = harness.llm.data(1)
    assert repair["previous_code"] == bad
    assert repair["failure"]["code"] == "sandbox_output_invalid"


def test_invalid_answer_gets_a_bounded_repair(harness: Harness) -> None:
    harness.llm.queue({"label": {"ko": "상자"}}, caption_box_answer(program("caption_round")))
    harness.service.generate_caption_box("둥글게", harness.video(), ctx=harness.ctx())
    assert len(harness.llm.requests) == 2
    assert harness.llm.data(1)["failure"]["code"] == "llm_invalid_output"


def test_repairs_stop_after_two_and_register_nothing(harness: Harness) -> None:
    bad = caption_box_answer(program("caption_tiny_text_area"))
    harness.llm.queue(bad, bad, bad)
    with pytest.raises(AppError) as failure:
        harness.service.generate_caption_box("둥글게", harness.video(), ctx=harness.ctx())
    assert failure.value.code == "sandbox_output_invalid"
    assert len(harness.llm.requests) == 3
    assert [item.id for item in harness.catalog.list("caption_style")] == ["plate"]


def test_place_edit_is_clamped_into_the_place_area(harness: Harness) -> None:
    harness.llm.queue({"place": {"x": 0, "y": 5000, "w": 2000}, "align": "right"})
    place, moved = harness.service.edit_caption_place(
        "오른쪽 아래로", harness.video(), ctx=harness.ctx()
    )
    assert moved is True
    assert (place.x, place.w, place.align) == (48, 840, "right")
    assert 288 <= place.y <= 1248


def test_place_edit_inside_the_area_is_not_moved(harness: Harness) -> None:
    harness.llm.queue({"place": {"x": 100, "y": 600, "w": 500}, "align": "left"})
    place, moved = harness.service.edit_caption_place(
        "왼쪽으로", harness.video(), ctx=harness.ctx()
    )
    assert moved is False
    assert (place.x, place.y, place.w, place.align) == (100, 600, 500, "left")
    assert harness.llm.data(0)["safe_area"] == {"x": 48, "y": 288, "w": 840, "h": 960}
