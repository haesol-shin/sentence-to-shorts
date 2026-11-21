"""Jobs that need models stay queued until the models are ready; downloads use their own slot."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.bootstrap import held_for_models, refuse_failed_models
from app.jobs import HEAVY, LIGHT, PREPARE, LocalJobContext
from app.ports import AppError
from app.runtime import fsutil
from app.runtime.models import prepare_models
from app.runtime.setup import RuntimeSetup
from app.schemas.job import Job, JobErrorCode, JobKind, JobState, WaitingOn
from app.storage.projects import new_typeid
from tests.jobs.support import Env, new_job, open_env, wait_until
from tests.runtime.support import FakeTransport, Flag, make_settings, model_item, noise, served

BLOBS = {
    "model-tts-qwen3-0.6b": {"tts.bin": noise(2_000, "tts")},
    "model-align-ko": {"ko.bin": noise(1_000, "ko")},
    "model-nltk-punkt-tab": {"punkt.bin": noise(300, "punkt")},
    "model-asr-small": {"asr.bin": noise(900, "asr")},
    "model-align-en": {"en.bin": noise(700, "en")},
}
TARGET = ("linux", "x86_64")


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


class Gate(FakeTransport):
    """A transport whose downloads wait until the test lets them go."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        super().__init__(blobs)
        self.release = threading.Event()

    def open(self, url: str, *, start: int, timeout: float) -> Any:
        assert self.release.wait(20), "the download was never released"
        return super().open(url, start=start, timeout=timeout)


class Rig:
    """The real queue runner over a prepare service and a pipeline that needs the models."""

    def __init__(self, tmp_path: Path, env: Env, *, languages: dict[str, str] | None = None):
        self.env = env
        self.items = [
            model_item(name, name, files, base=f"https://download.invalid/{name}")
            for name, files in BLOBS.items()
        ]
        blobs: dict[str, bytes] = {}
        for item in self.items:
            blobs.update(served(item, BLOBS[item["id"]]))
        self.transport = Gate(blobs)
        self.settings = make_settings(tmp_path, self.items)
        self.languages = languages or {}
        self.setup = RuntimeSetup(
            self.settings,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            env.jobs,
            inputs=env.inputs,
            transport=self.transport,
            language_of=lambda job: self.languages.get(job.video_id or ""),
        )
        self.ran: list[JobKind] = []
        self.blocked_calls = 0
        check = held_for_models(self.setup)

        def counting(job: Job) -> bool:
            self.blocked_calls += 1
            return check(job)

        self.runner = env.runner(self.run_job, blocked=counting, poll_s=0.05)

    def run_job(self, job: Job, ctx: LocalJobContext) -> dict[str, Any]:
        if job.kind is JobKind.runtime_prepare:
            return self.setup.run_job(job, ctx)
        refuse_failed_models(self.setup, job)
        # The real pipeline fails with `tts_not_ready` when the files are not there.
        if job.kind is JobKind.generate and not self.setup.groups_ready(["voice"]):
            raise AppError("tts_not_ready")
        self.ran.append(job.kind)
        return {"done": True}

    def prepare_now(self, *names: str) -> None:
        """Make some items ready without the runner, as an earlier run would have."""
        self.transport.release.set()
        chosen = [item for item in self.items if item["id"] in names]
        prepare_models(
            self.settings.model_dir,  # type: ignore[attr-defined]
            chosen,
            cancel=Flag(),
            transport=self.transport,
            target=TARGET,
        )

    def submit(self, kind: JobKind, video_id: str | None = None) -> Job:
        job = new_job(kind, video_id=video_id)
        return self.env.jobs.create(job)

    def state(self, job: Job) -> JobState:
        return self.env.jobs.get(job.id).state

    def __enter__(self) -> Rig:
        self.runner.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.transport.release.set()
        self.runner.stop()


def test_21_a_generate_waits_for_its_group_and_then_runs_without_tts_not_ready(
    tmp_path: Path, env: Env
) -> None:
    rig = Rig(tmp_path, env)
    with rig:
        generate = rig.submit(JobKind.generate)
        style = rig.submit(JobKind.style)
        assert wait_until(lambda: rig.state(style) is JobState.succeeded)
        held = env.jobs.get(generate.id)
        assert held.state is JobState.queued and held.deadline_at is None
        assert held.started_at is None and held.progress.waiting_on is WaitingOn.queue
        # The held job has its prepare job although nobody asked for one.
        assert [job.kind for job in env.jobs.unfinished() if job.id != generate.id] == [
            JobKind.runtime_prepare
        ]
        assert rig.ran == [JobKind.style]

        rig.transport.release.set()
        assert wait_until(lambda: rig.state(generate) is JobState.succeeded, timeout_s=20)
    done = env.jobs.get(generate.id)
    assert done.error is None and done.deadline_at is not None
    assert rig.ran == [JobKind.style, JobKind.generate]


def test_21_a_reference_waits_for_the_transcriber_alone(tmp_path: Path, env: Env) -> None:
    rig = Rig(tmp_path, env)
    rig.prepare_now("model-tts-qwen3-0.6b", "model-align-ko", "model-nltk-punkt-tab")
    rig.transport.release.clear()
    with rig:
        reference = rig.submit(JobKind.reference)
        generate = rig.submit(JobKind.generate)
        assert wait_until(lambda: rig.state(generate) is JobState.succeeded)
        assert rig.state(reference) is JobState.queued
        rig.transport.release.set()
        assert wait_until(lambda: rig.state(reference) is JobState.succeeded, timeout_s=20)


def test_21_an_english_video_waits_for_the_english_aligner_too(tmp_path: Path, env: Env) -> None:
    english, korean = new_typeid("v"), new_typeid("v")
    rig = Rig(tmp_path, env, languages={english: "en", korean: "ko"})
    rig.prepare_now("model-tts-qwen3-0.6b", "model-align-ko", "model-nltk-punkt-tab")
    rig.transport.release.clear()
    with rig:
        in_english = rig.submit(JobKind.generate, english)
        in_korean = rig.submit(JobKind.generate, korean)
        assert wait_until(lambda: rig.state(in_korean) is JobState.succeeded)
        assert rig.state(in_english) is JobState.queued
        rig.transport.release.set()
        assert wait_until(lambda: rig.state(in_english) is JobState.succeeded, timeout_s=20)


def test_21_a_queue_of_held_jobs_only_polls(tmp_path: Path, env: Env) -> None:
    rig = Rig(tmp_path, env)
    with rig:
        rig.submit(JobKind.generate)
        time.sleep(0.5)
        calls = rig.blocked_calls
        time.sleep(0.5)
    # Two polls of a job per 50 ms at most: a busy loop would be thousands.
    assert 0 < rig.blocked_calls - calls <= 40


def test_21_a_stopped_group_fails_the_held_job_with_the_same_code(
    tmp_path: Path, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, env)
    monkeypatch.setattr(fsutil, "disk_free", lambda path: 10)
    with rig:
        generate = rig.submit(JobKind.generate)
        rig.transport.release.set()
        assert wait_until(lambda: rig.state(generate) is JobState.failed, timeout_s=20)
    failed = env.jobs.get(generate.id)
    assert failed.error is not None and failed.error.code is JobErrorCode.disk_full
    assert failed.error.detail == {"group": "voice"}
    assert rig.ran == []


def test_21_a_download_does_not_take_the_heavy_slot(tmp_path: Path, env: Env) -> None:
    rig = Rig(tmp_path, env)
    rig.prepare_now("model-tts-qwen3-0.6b", "model-align-ko", "model-nltk-punkt-tab")
    rig.transport.release.clear()
    heavy_started, heavy_release = threading.Event(), threading.Event()
    original = rig.run_job

    def run_job(job: Job, ctx: LocalJobContext) -> dict[str, Any]:
        if job.kind is JobKind.style:
            heavy_started.set()
            assert heavy_release.wait(20)
        return original(job, ctx)

    rig.runner = env.runner(run_job, blocked=held_for_models(rig.setup), poll_s=0.05)
    with rig:
        style = rig.submit(JobKind.style)
        assert heavy_started.wait(10)
        reference = rig.submit(JobKind.reference)
        # What `LocalJobs.submit` does for a job that needs a group.
        rig.setup.ensure(rig.setup.needs(reference))
        rig.transport.release.set()
        assert wait_until(
            lambda: rig.setup.groups_ready(["transcribe"]), timeout_s=20
        ), "the download waited for the heavy job"
        assert rig.state(style) is JobState.running
        heavy_release.set()
        assert wait_until(lambda: rig.state(style) is JobState.succeeded)


def test_21_cancelling_a_held_job_ends_it_in_the_queue(tmp_path: Path, env: Env) -> None:
    rig = Rig(tmp_path, env)
    with rig:
        generate = rig.submit(JobKind.generate)
        assert wait_until(lambda: any(
            job.kind is JobKind.runtime_prepare for job in env.jobs.unfinished()
        ))
        cancelled = env.jobs.request_cancel(generate.id)
        assert cancelled.state is JobState.cancelled
    assert rig.ran == []


def test_21_claim_with_only_skips_jobs_the_caller_did_not_check(env: Env) -> None:
    older = env.jobs.create(new_job(JobKind.generate))
    newer = env.jobs.create(new_job(JobKind.style))
    assert env.jobs.claim(HEAVY, frozenset()) is None
    claimed = env.jobs.claim(HEAVY, frozenset({newer.id}))
    assert claimed is not None and claimed.id == newer.id
    assert env.jobs.get(older.id).state is JobState.queued


def test_21_prepare_jobs_have_their_own_queue_slot(env: Env) -> None:
    heavy = env.jobs.create(new_job(JobKind.generate))
    prepare = env.jobs.create(new_job(JobKind.runtime_prepare))
    assert env.jobs.claim(HEAVY) is not None
    assert env.jobs.queued(HEAVY) == []
    assert [job.id for job in env.jobs.queued(PREPARE)] == [prepare.id]
    claimed = env.jobs.claim(PREPARE)
    assert claimed is not None and claimed.id == prepare.id
    assert env.jobs.claim(PREPARE) is None
    assert env.jobs.get(heavy.id).state is JobState.running
    with pytest.raises(ValueError):
        env.jobs.claim("elsewhere")
    assert env.jobs.queued(LIGHT) == []


def test_21_a_prepare_job_the_last_run_left_running_is_queued_again_on_its_own_queue(
    env: Env,
) -> None:
    prepare = env.jobs.create(new_job(JobKind.runtime_prepare))
    assert env.jobs.claim(PREPARE) is not None
    env.jobs.recover()
    again = env.jobs.get(prepare.id)
    assert again.state is JobState.queued and again.attempt == 2
    assert [job.id for job in env.jobs.queued(PREPARE)] == [prepare.id]
    assert env.jobs.queued(HEAVY) == []
