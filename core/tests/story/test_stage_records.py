"""The real story services leave stage and progress records on the job."""

from __future__ import annotations

import time
from pathlib import Path

from test_draft import ANALOGY_SCRIPT, ANALOGY_SPLIT, DRAFT, MESSAGE
from test_interpret import CHAT_MULTI, WHOLE
from test_patch import NotCancelled, RecordingLlm, StubCatalog, make_video
from test_script import RAW_USER_SCRIPT, USER_SPLIT

from app.jobs import LocalJobContext
from app.schemas.job import Stage, WaitingOn
from app.services.story.draft import draft
from app.services.story.interpret import interpret
from app.services.story.script import write_script


class Recorded:
    """A real job context whose callbacks keep what the job store would save."""

    def __init__(self) -> None:
        self.stages: list[tuple[Stage, str]] = []
        self.progress: list[tuple[Stage | None, int, int, WaitingOn | None]] = []
        self.current: Stage | None = None
        self.ctx = LocalJobContext(
            cancel_token=NotCancelled(),  # type: ignore[arg-type]
            deadline=time.monotonic() + 60,
            job_dir=Path("."),
            on_stage=self._stage,
            on_progress=self._progress,
        )

    def _stage(self, stage: Stage, state: str) -> None:
        self.current = stage
        self.stages.append((stage, state))

    def _progress(self, done: int, total: int, waiting_on: WaitingOn | None) -> None:
        self.progress.append((self.current, done, total, waiting_on))


def test_27_draft_records_its_three_llm_stages_and_finishes_at_total() -> None:
    recorded = Recorded()
    video = make_video(script=None, origins={})
    llm = RecordingLlm(DRAFT, ANALOGY_SCRIPT, ANALOGY_SCRIPT, ANALOGY_SPLIT)
    draft(video, MESSAGE, None, llm=llm, catalog=StubCatalog(), ctx=recorded.ctx)

    assert recorded.stages == [
        (Stage.llm_draft, "running"),
        (Stage.llm_draft, "done"),
        (Stage.llm_script, "running"),
        (Stage.llm_script, "done"),
        (Stage.llm_split, "running"),
        (Stage.llm_split, "done"),
    ]
    assert recorded.progress == [
        (Stage.llm_draft, 0, 3, WaitingOn.llm),
        (Stage.llm_draft, 1, 3, None),
        (Stage.llm_script, 1, 3, WaitingOn.llm),
        (Stage.llm_script, 2, 3, None),
        (Stage.llm_split, 2, 3, WaitingOn.llm),
        (Stage.llm_split, 3, 3, None),
    ]


def test_27_draft_with_a_script_is_one_step() -> None:
    recorded = Recorded()
    video = make_video(
        script={"source": "llm", "raw_text": "기존 대본", "title": "기존"}, origins={}
    )
    draft(
        video, MESSAGE, None, llm=RecordingLlm(DRAFT), catalog=StubCatalog(), ctx=recorded.ctx
    )
    assert [stage for stage, _ in recorded.stages] == [Stage.llm_draft] * 2
    assert recorded.progress[-1] == (Stage.llm_draft, 1, 1, None)


def test_27_script_records_script_and_split_stages() -> None:
    recorded = Recorded()
    llm = RecordingLlm(ANALOGY_SCRIPT, ANALOGY_SPLIT)
    write_script(
        make_video(script=None, story_structure="single_analogy", scene_count=4),
        llm=llm,
        catalog=StubCatalog(),
        ctx=recorded.ctx,
    )
    assert [stage for stage, state in recorded.stages if state == "done"] == [
        Stage.llm_script,
        Stage.llm_split,
    ]
    assert recorded.progress[-1] == (Stage.llm_split, 2, 2, None)


def test_27_split_of_a_user_script_is_one_step() -> None:
    recorded = Recorded()
    script = {"source": "user", "raw_text": RAW_USER_SCRIPT, "title": "합성 대본"}
    llm = RecordingLlm(USER_SPLIT)
    video = make_video(script=script, scene_count=3)
    write_script(video, llm=llm, catalog=StubCatalog(), ctx=recorded.ctx)
    assert [stage for stage, _ in recorded.stages] == [Stage.llm_split] * 2
    assert recorded.progress == [
        (Stage.llm_split, 0, 1, WaitingOn.llm),
        (Stage.llm_split, 1, 1, None),
    ]


def test_27_chat_records_the_chat_stage() -> None:
    recorded = Recorded()
    interpret(
        make_video(origins={}),
        "반말로 바꿔 줘",
        WHOLE,
        llm=RecordingLlm(CHAT_MULTI),
        catalog=StubCatalog(),
        ctx=recorded.ctx,
    )
    assert recorded.stages == [(Stage.llm_chat, "running"), (Stage.llm_chat, "done")]
    assert recorded.progress == [
        (Stage.llm_chat, 0, 1, WaitingOn.llm),
        (Stage.llm_chat, 1, 1, None),
    ]
