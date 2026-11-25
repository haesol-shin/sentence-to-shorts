"""Reference proposals and project application share pointer-aware precedence."""

from __future__ import annotations

import pytest

from app.plugins.registry import Registry
from app.schemas.change import SetOp
from app.schemas.common import Origin
from app.schemas.settings import higher_origin_pointers
from app.schemas.video import Video
from app.services.project import state
from app.services.reference.values import build
from app.services.reference.vision import ReferenceValues
from tests.reference.support import draft_video


@pytest.fixture(scope="module")
def catalog() -> Registry:
    registry = Registry()
    registry.load()
    return registry


def _video(pointer: str, origin: Origin) -> Video:
    raw = draft_video().model_dump(mode="json", by_alias=True)
    raw["settings"]["origins"] = {pointer: origin.value}
    return Video.model_validate(raw)


@pytest.mark.parametrize(
    "pointer", ["/format", "/format/layout", "/format/layout/id", "/format/layout/revision"]
)
def test_20_reference_keeps_user_layout_at_every_pointer_depth(
    catalog: Registry, pointer: str
) -> None:
    video = _video(pointer, Origin.user)
    answer = ReferenceValues(layout="dialog_stage")

    result = build(video, answer, video.settings.format.scene_count, catalog)

    assert result.ops == []
    assert result.kept_user_values == ["/settings/format/layout"]
    applied = state.apply(video, result.ops, Origin.reference)
    assert applied.video.settings.format.layout == video.settings.format.layout
    assert applied.overwrites_user_values == []

    attempted = SetOp(
        op="set",
        path="/settings/format/layout",
        value=catalog.pin("template", "dialog_stage").model_dump(mode="json"),
        origin=Origin.reference,
    )
    guarded = state.apply(video, [attempted], Origin.reference)
    assert guarded.overwrites_user_values == ["/settings" + pointer]
    if pointer.endswith("/id"):
        assert guarded.video.settings.format.layout.id == video.settings.format.layout.id
    elif pointer.endswith("/revision"):
        assert (
            guarded.video.settings.format.layout.revision
            == video.settings.format.layout.revision
        )
    else:
        assert guarded.video.settings.format.layout == video.settings.format.layout


@pytest.mark.parametrize(
    "pointer", ["/format/story_structure", "/format/layout_id", "/format/layout_extra/id"]
)
def test_20_unrelated_user_pointer_does_not_block_reference_layout(
    catalog: Registry, pointer: str
) -> None:
    video = _video(pointer, Origin.user)

    result = build(
        video, ReferenceValues(layout="dialog_stage"), video.settings.format.scene_count, catalog
    )

    assert result.kept_user_values == []
    assert len(result.ops) == 1
    assert result.ops[0].path == "/settings/format/layout"
    applied = state.apply(video, result.ops, Origin.reference)
    assert applied.overwrites_user_values == []
    assert applied.video.settings.format.layout.id == "dialog_stage"


@pytest.mark.parametrize("origin", [Origin.default, Origin.llm, Origin.card, Origin.preset,
                                    Origin.reference, Origin.derived])
def test_20_equal_or_lower_layout_origin_allows_reference_update(
    catalog: Registry, origin: Origin
) -> None:
    video = _video("/format/layout/id", origin)

    result = build(
        video, ReferenceValues(layout="dialog_stage"), video.settings.format.scene_count, catalog
    )

    assert result.kept_user_values == []
    applied = state.apply(video, result.ops, Origin.reference)
    assert applied.overwrites_user_values == []
    assert applied.video.settings.format.layout.id == "dialog_stage"


def test_20_reference_caption_place_becomes_one_op(catalog: Registry) -> None:
    video = draft_video()
    answer = ReferenceValues(
        caption_place={
            "y_top": 0.3,
            "y_bottom": 0.45,
            "x_left": 0.2,
            "x_right": 0.7,
            "align": "left",
        }
    )

    result = build(video, answer, video.settings.format.scene_count, catalog)

    assert [(op.path, op.value) for op in result.ops] == [
        (
            "/settings/caption/place",
            {"y": 572, "x": 216, "w": 540, "align": "left"},
        )
    ]
    applied = state.apply(video, result.ops, Origin.reference)
    assert applied.video.settings.caption.place is not None
    assert (applied.video.settings.caption.place.x, applied.video.settings.caption.place.w) == (
        216,
        540,
    )


@pytest.mark.parametrize(
    "ratios",
    [
        {"y_top": 1.2, "y_bottom": 0.45, "x_left": 0.2, "x_right": 0.7},
        {"y_top": 0.3, "y_bottom": 0.45, "x_left": -0.1, "x_right": 0.7},
        {"y_top": 0.3, "y_bottom": 0.45, "x_left": 0.7, "x_right": 0.2},
        {"y_top": 0.45, "y_bottom": 0.3, "x_left": 0.2, "x_right": 0.7},
    ],
)
def test_20_reference_discards_a_place_it_cannot_read(
    catalog: Registry, ratios: dict[str, float]
) -> None:
    video = draft_video()

    result = build(
        video,
        ReferenceValues(caption_place=ratios),
        video.settings.format.scene_count,
        catalog,
    )

    assert [op for op in result.ops if op.path == "/settings/caption/place"] == []


def test_20_reference_place_does_not_override_a_user_value(catalog: Registry) -> None:
    video = _video("/caption/place", Origin.user)
    answer = ReferenceValues(
        caption_place={
            "y_top": 0.3,
            "y_bottom": 0.45,
            "x_left": 0.2,
            "x_right": 0.7,
        }
    )

    result = build(video, answer, video.settings.format.scene_count, catalog)

    assert [op for op in result.ops if op.path == "/settings/caption/place"] == []
    assert result.kept_user_values == ["/settings/caption/place"]


def test_20_shared_rule_returns_only_higher_related_origins_in_restoration_order() -> None:
    origins = {
        "/format/layout/revision": "user",
        "/format/layout/id": Origin.user,
        "/format": Origin.card,
        "/format/layout_extra": Origin.user,
        "/format/layout": Origin.reference,
        "/audio": Origin.user,
    }

    assert higher_origin_pointers(origins, "/format/layout", Origin.reference) == [
        "/format/layout/id", "/format/layout/revision"
    ]
    assert higher_origin_pointers(origins, "/format/layout/id", Origin.llm) == [
        "/format", "/format/layout", "/format/layout/id"
    ]
    assert higher_origin_pointers(origins, "/format/layout", Origin.user) == []
