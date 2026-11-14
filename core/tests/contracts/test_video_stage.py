"""The concept stage survives a script rewrite; only forward gates move."""

from __future__ import annotations

from app.schemas.video import VideoStage, stage_after_script_rewrite


def test_concept_confirmation_survives_a_script_rewrite() -> None:
    assert (
        stage_after_script_rewrite(VideoStage.concept_confirmed)
        is VideoStage.concept_confirmed
    )
    assert (
        stage_after_script_rewrite(VideoStage.script_confirmed)
        is VideoStage.concept_confirmed
    )
    assert (
        stage_after_script_rewrite(VideoStage.scenes_confirmed)
        is VideoStage.concept_confirmed
    )


def test_script_rewrite_before_concept_leaves_draft() -> None:
    assert stage_after_script_rewrite(VideoStage.draft) is VideoStage.draft
