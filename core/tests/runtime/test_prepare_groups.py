"""Need groups: one prepare job per group, retries, failures and the second start."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.bootstrap import _prepares_models, build_runtime
from app.jobs import CancelFlag
from app.ports import AppError, Cancelled
from app.runtime import fsutil
from app.runtime.lock import host_platform
from app.runtime.models import GROUP_ORDER
from app.runtime.setup import RETRY_DELAYS_S, RuntimeSetup, pause
from app.schemas.api import PrepareErrorCode, PrepareGroupState
from app.schemas.common import PERSONAL_OWNER_ID
from app.schemas.job import Job, JobErrorCode, JobKind, JobState
from tests.jobs.support import Env, new_job, new_typeid, open_env, wait_until
from tests.runtime.support import (
    FakeTransport,
    lock_item,
    make_settings,
    model_item,
    noise,
    served,
)

BLOBS = {
    "model-tts-qwen3-0.6b": {"tts.bin": noise(3_000, "tts"), "tts.json": b"{}"},
    "model-align-ko": {"ko.bin": noise(2_000, "ko")},
    "model-nltk-punkt-tab": {"punkt.bin": noise(500, "punkt")},
    "model-asr-small": {"asr.bin": noise(1_500, "asr")},
    "model-align-en": {"en.bin": noise(1_000, "en")},
}
GROUP_BYTES = {
    "voice": 3_000 + 2 + 2_000 + 500,
    "transcribe": 1_500,
    "align_en": 1_000,
}


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    opened = open_env(tmp_path)
    yield opened
    opened.close()


def lock_items() -> list[dict[str, Any]]:
    items = []
    for identifier, files in BLOBS.items():
        item = model_item(
            identifier,
            identifier,
            files,
            base=f"https://download.invalid/{identifier}",
        )
        items.append(item)
    return items


def transport_for(items: list[dict[str, Any]], **options: Any) -> FakeTransport:
    blobs: dict[str, bytes] = {}
    for item in items:
        if item["id"] in BLOBS:
            blobs.update(served(item, BLOBS[item["id"]]))
    return FakeTransport(blobs, **options)


class Pauses:
    """A pause that records its length and returns, so retries cost no time."""

    def __init__(self, setup_of: Any = None) -> None:
        self.seconds: list[float] = []
        self.seen: list[Any] = []
        self.setup_of = setup_of

    def __call__(self, cancel: Any, seconds: float, wake: threading.Event) -> None:
        self.seconds.append(seconds)
        if self.setup_of is not None:
            self.seen.append(self.setup_of().groups())


def make_setup(
    tmp_path: Path, env: Env, items: list[dict[str, Any]] | None = None, **options: Any
) -> tuple[RuntimeSetup, FakeTransport]:
    items = items if items is not None else lock_items()
    transport = options.pop("transport", None) or transport_for(items)
    settings = make_settings(tmp_path, items)
    setup = RuntimeSetup(
        settings, object(), env.jobs, inputs=env.inputs, transport=transport, **options  # type: ignore[arg-type]
    )
    return setup, transport


def run_prepare_jobs(env: Env, setup: RuntimeSetup, *, until: Any = None) -> None:
    runner = env.runner(lambda job, ctx: setup.run_job(job, ctx))
    runner.start()
    try:
        assert wait_until(
            until or (lambda: not env.jobs.unfinished()), timeout_s=20
        ), env.jobs.unfinished()
    finally:
        runner.stop()


def prepare_jobs(env: Env) -> list[Job]:
    return [job for job in env.jobs.unfinished() if job.kind is JobKind.runtime_prepare]


def group_states(setup: RuntimeSetup) -> dict[str, PrepareGroupState]:
    return {group.id.value: group.state for group in setup.groups()}


# --- ensure ----------------------------------------------------------------------------


def test_21_ensure_queues_one_job_per_group_and_none_once_ready(
    tmp_path: Path, env: Env
) -> None:
    setup, transport = make_setup(tmp_path, env)
    first = setup.ensure(["voice"])
    assert len(first) == 1 and first[0].kind is JobKind.runtime_prepare
    assert env.inputs.load(first[0].id) == {"groups": ["voice"]}
    assert [job.id for job in setup.ensure(["voice"])] == [first[0].id]
    assert len(prepare_jobs(env)) == 1

    run_prepare_jobs(env, setup)
    assert group_states(setup)["voice"] is PrepareGroupState.ready
    assert setup.ensure(["voice"]) == []
    assert prepare_jobs(env) == []
    assert transport.count == 4


def test_21_a_running_prepare_job_covers_its_group(tmp_path: Path, env: Env) -> None:
    setup, _transport = make_setup(tmp_path, env)
    queued = setup.ensure(["voice", "align_en"])
    assert len({job.id for job in queued}) == 2
    claimed = env.jobs.claim("prepare")
    assert claimed is not None
    again = setup.ensure(["voice", "align_en"])
    assert {job.id for job in again} == {job.id for job in queued}
    assert len(prepare_jobs(env)) == 2


def test_21_two_threads_that_ensure_the_same_group_make_one_job(tmp_path: Path, env: Env) -> None:
    setup, _transport = make_setup(tmp_path, env)
    barrier = threading.Barrier(8)

    def go() -> None:
        barrier.wait()
        setup.ensure(["voice"])

    threads = [threading.Thread(target=go) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(prepare_jobs(env)) == 1


@pytest.mark.parametrize(
    ("deployment", "profile", "expected"),
    [
        ("local", "dev", True),
        ("local", "release", True),
        ("local", "fixture", False),
        ("hosted", "release", False),
        ("hosted", "fixture", False),
    ],
)
def test_21_only_a_local_app_with_real_adapters_prepares_models(
    deployment: str, profile: str, expected: bool
) -> None:
    class Settings:
        pass

    settings = Settings()
    settings.deployment, settings.profile = deployment, profile  # type: ignore[attr-defined]
    assert _prepares_models(settings) is expected  # type: ignore[arg-type]


def test_21_a_disabled_setup_queues_nothing_and_holds_nothing(tmp_path: Path, env: Env) -> None:
    setup, transport = make_setup(tmp_path, env, enabled=False)
    assert setup.ensure(GROUP_ORDER) == []
    assert setup.needs(new_job(JobKind.generate)) == []
    assert prepare_jobs(env) == [] and transport.count == 0


def test_21_the_fixture_profile_starts_without_a_prepare_job(app_settings: Any) -> None:
    runtime = build_runtime(app_settings)
    try:
        runtime.start()
        assert runtime.job_store.unfinished() == []
        assert runtime.runtime_setup.ensure_language("en") == []
    finally:
        runtime.close()


def test_21_an_app_that_prepares_models_queues_the_voice_group_at_start(
    app_settings: Any,
) -> None:
    runtime = build_runtime(app_settings)
    try:
        # The workers stay stopped, so nothing downloads: only the queueing is observed.
        runtime.runtime_setup.enabled = True
        runtime._prepare_at_start()
        jobs = runtime.job_store.unfinished()
        assert [job.kind for job in jobs] == [JobKind.runtime_prepare]
        assert runtime.job_inputs.load(jobs[0].id) == {"groups": ["voice"]}
        assert runtime.runtime_setup.ensure_language("ko") == []
        english = runtime.runtime_setup.ensure_language("en")
        assert [runtime.job_inputs.load(job.id) for job in english] == [{"groups": ["align_en"]}]
        runtime._prepare_at_start()
        assert len(runtime.job_store.unfinished()) == 2
    finally:
        runtime.close()


# --- what a job waits for --------------------------------------------------------------


def test_21_each_kind_waits_for_the_models_it_uses(tmp_path: Path, env: Env) -> None:
    korean_id, english_id = new_typeid("v"), new_typeid("v")
    languages = {korean_id: "ko", english_id: "en"}
    setup, _transport = make_setup(
        tmp_path, env, language_of=lambda job: languages.get(job.video_id or "")
    )
    korean = new_job(JobKind.generate, video_id=korean_id)
    english = new_job(JobKind.generate, video_id=english_id)
    assert setup.needs(korean) == ["voice"]
    assert setup.needs(english) == ["voice", "align_en"]
    assert setup.needs(new_job(JobKind.reference)) == ["transcribe"]
    for kind in (
        JobKind.preview,
        JobKind.draft,
        JobKind.script,
        JobKind.style,
        JobKind.bgm_code,
        JobKind.runtime_prepare,
    ):
        assert setup.needs(new_job(kind)) == [], kind


def test_21_a_video_that_is_gone_does_not_stop_the_check(tmp_path: Path, env: Env) -> None:
    def gone(job: Job) -> str | None:
        raise AppError("not_found")

    setup, _transport = make_setup(tmp_path, env, language_of=gone)
    assert setup.needs(new_job(JobKind.generate, video_id=new_typeid("v"))) == ["voice"]


# --- running a group job ---------------------------------------------------------------


def test_21_a_group_job_downloads_its_group_and_reports_progress(
    tmp_path: Path, env: Env
) -> None:
    setup, transport = make_setup(tmp_path, env)
    seen: list[tuple[PrepareGroupState, int]] = []
    original = setup._track

    def watch(group: str, track: Any) -> None:
        original(group, track)
        if group == "voice" and track is not None:
            seen.append((track.state, track.done))

    setup._track = watch  # type: ignore[method-assign]
    (job,) = setup.ensure(["voice"])
    run_prepare_jobs(env, setup)
    finished = env.jobs.get(job.id)
    assert finished.state is JobState.succeeded
    assert set(finished.result["prepared"]) >= {  # type: ignore[index]
        "model-tts-qwen3-0.6b",
        "model-align-ko",
        "model-nltk-punkt-tab",
    }
    assert any(state is PrepareGroupState.downloading and done for state, done in seen)
    voice = next(group for group in setup.groups() if group.id.value == "voice")
    assert (voice.state, voice.done, voice.total) == (
        PrepareGroupState.ready,
        GROUP_BYTES["voice"],
        GROUP_BYTES["voice"],
    )
    assert group_states(setup) == {
        "voice": PrepareGroupState.ready,
        "transcribe": PrepareGroupState.queued,
        "align_en": PrepareGroupState.queued,
    }
    assert transport.count == 4


def test_21_a_lost_connection_retries_in_the_job_after_5_15_45_then_120_seconds(
    tmp_path: Path, env: Env
) -> None:
    items = lock_items()
    transport = transport_for(items)
    real_open = transport.open
    refused = [0]

    def flaky(url: str, *, start: int, timeout: float) -> Any:
        if refused[0] < 5:
            refused[0] += 1
            raise AppError("download_failed", detail={"reason": "connect"})
        return real_open(url, start=start, timeout=timeout)

    transport.open = flaky  # type: ignore[method-assign]
    holder: list[RuntimeSetup] = []
    pauses = Pauses(lambda: holder[0])
    setup, _ = make_setup(tmp_path, env, items, transport=transport, pause_for=pauses)
    holder.append(setup)
    (job,) = setup.ensure(["align_en"])
    run_prepare_jobs(env, setup)
    assert env.jobs.get(job.id).state is JobState.succeeded
    assert pauses.seconds == [5.0, 15.0, 45.0, 120.0, 120.0]
    assert RETRY_DELAYS_S == (5.0, 15.0, 45.0, 120.0)
    for groups in pauses.seen:
        align = next(group for group in groups if group.id.value == "align_en")
        assert align.state is PrepareGroupState.retrying
        assert align.error_code is PrepareErrorCode.download_failed
        assert align.retry_at is not None and align.retry_at > datetime.now(UTC)
    assert group_states(setup)["align_en"] is PrepareGroupState.ready


def test_21_a_cancel_ends_the_retry_wait_at_once() -> None:
    flag = CancelFlag()
    started = time.monotonic()
    threading.Timer(0.2, flag.cancel).start()
    with pytest.raises(Cancelled):
        pause(flag, 120.0, threading.Event())
    assert time.monotonic() - started < 3


def test_21_a_new_request_ends_the_retry_wait_at_once() -> None:
    wake = threading.Event()
    started = time.monotonic()
    threading.Timer(0.2, wake.set).start()
    pause(CancelFlag(), 120.0, wake)
    assert time.monotonic() - started < 3 and not wake.is_set()


def test_21_a_cancelled_job_leaves_its_group_queued_and_the_next_start_resumes(
    tmp_path: Path, env: Env
) -> None:
    items = lock_items()
    transport = transport_for(items, fail_after=[500])

    def closed(cancel: Any, seconds: float, wake: threading.Event) -> None:
        raise Cancelled("the app was closed")

    setup, _ = make_setup(tmp_path, env, items, transport=transport, pause_for=closed)
    (job,) = setup.ensure(["transcribe"])
    claimed = env.jobs.claim("prepare")
    assert claimed is not None
    ctx = _context(env, claimed)
    with pytest.raises(Cancelled):
        setup.run_job(claimed, ctx)
    assert group_states(setup)["transcribe"] is PrepareGroupState.queued
    part = tmp_path / "models" / "model-asr-small" / "asr.bin.part"
    assert part.stat().st_size == 500

    second_start = transport_for(items)
    again, _ = make_setup(tmp_path, env, items, transport=second_start)
    again.run_job(claimed, ctx)
    assert second_start.opens[0][1] == 500
    assert group_states(again)["transcribe"] is PrepareGroupState.ready
    assert job.id == claimed.id


def _context(env: Env, job: Job) -> Any:
    from app.jobs import LocalJobContext

    return LocalJobContext(
        cancel_token=CancelFlag(),
        deadline=float("inf"),
        job_dir=env.layout.cache,
        owner_id=PERSONAL_OWNER_ID,
        job_id=job.id,
        attempt=job.attempt,
        price_version=None,
        input_payload=env.inputs.load(job.id) or {},
        on_progress=lambda done, total, waiting_on: None,
        on_stage=lambda stage, state: None,
        on_checkpoint=lambda record: None,
        on_usage=lambda usage: None,
        on_request=lambda event: None,
    )


@pytest.mark.parametrize("code", ["disk_full", "model_hash_mismatch"])
def test_21_a_permanent_error_fails_the_group_and_the_job_with_the_same_code(
    tmp_path: Path, env: Env, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    items = lock_items()
    if code == "disk_full":
        monkeypatch.setattr(fsutil, "disk_free", lambda path: 10)
        transport = transport_for(items)
    else:
        corrupt = noise(1_000, "corrupt")
        transport = FakeTransport({items[4]["files"][0]["url"]: corrupt})
    setup, _ = make_setup(tmp_path, env, items, transport=transport)
    (job,) = setup.ensure(["align_en"])
    run_prepare_jobs(env, setup)
    failed = env.jobs.get(job.id)
    assert failed.state is JobState.failed
    assert failed.error is not None and failed.error.code is JobErrorCode(code)
    assert setup.groups_failed(["align_en"]) == {"align_en": code}
    group = next(g for g in setup.groups() if g.id.value == "align_en")
    assert group.state is PrepareGroupState.failed and group.error_code.value == code  # type: ignore[union-attr]
    assert setup.groups_failed(["voice"]) == {}


def runtime_tool() -> tuple[dict[str, Any], bytes]:
    blob = noise(2_000, "tool")
    target = host_platform()
    item = lock_item("tool", "tool", "tool.bin", blob, os_name=target[0], arch=target[1])
    return item, blob


def test_21_a_runtime_file_that_cannot_be_fetched_fails_the_group_and_the_held_job(
    tmp_path: Path, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, _blob = runtime_tool()
    items = [*lock_items(), tool]
    monkeypatch.setattr(fsutil, "disk_free", lambda path: 10)
    setup, _ = make_setup(tmp_path, env, items)
    (job,) = setup.ensure(["align_en"])
    run_prepare_jobs(env, setup)
    failed = env.jobs.get(job.id)
    assert failed.state is JobState.failed
    assert failed.error is not None and failed.error.code is JobErrorCode.disk_full
    # The group carries the error, so the job held for it fails and no new job is made.
    assert setup.groups_failed(["align_en"]) == {"align_en": "disk_full"}
    assert setup.ensure(["align_en"]) == []
    assert prepare_jobs(env) == []


def test_21_a_lost_connection_on_a_runtime_file_waits_and_retries_like_a_model(
    tmp_path: Path, env: Env
) -> None:
    tool, blob = runtime_tool()
    items = [*lock_items(), tool]
    transport = transport_for(items)
    transport.blobs[tool["files"][0]["url"]] = blob
    real_open = transport.open
    refused = [0]

    def flaky(url: str, *, start: int, timeout: float) -> Any:
        if url == tool["files"][0]["url"] and refused[0] < 2:
            refused[0] += 1
            raise AppError("download_failed", detail={"reason": "connect"})
        return real_open(url, start=start, timeout=timeout)

    transport.open = flaky  # type: ignore[method-assign]
    holder: list[RuntimeSetup] = []
    pauses = Pauses(lambda: holder[0])
    setup, _ = make_setup(tmp_path, env, items, transport=transport, pause_for=pauses)
    holder.append(setup)
    (job,) = setup.ensure(["align_en"])
    run_prepare_jobs(env, setup)
    assert env.jobs.get(job.id).state is JobState.succeeded
    assert pauses.seconds == [5.0, 15.0]
    for groups in pauses.seen:
        align = next(group for group in groups if group.id.value == "align_en")
        assert align.state is PrepareGroupState.retrying
        assert align.error_code is PrepareErrorCode.download_failed
    assert group_states(setup)["align_en"] is PrepareGroupState.ready


def test_21_an_unreachable_hub_makes_the_group_retry_instead_of_fail(
    tmp_path: Path, env: Env
) -> None:
    from huggingface_hub import errors

    def hub(repo_id: str, filename: str, revision: str, local_dir: Path) -> str:
        raise errors.LocalEntryNotFoundError("cannot reach the hub")

    item = model_item(
        "model-align-ko",
        "model-align-ko",
        BLOBS["model-align-ko"],
        base="https://huggingface.co/owner/repo/resolve/" + "b" * 40,
    )
    pauses = Pauses()

    def stop_after_two(cancel: Any, seconds: float, wake: threading.Event) -> None:
        pauses(cancel, seconds, wake)
        if len(pauses.seconds) == 2:
            raise Cancelled("end the test after two waits")

    setup, _ = make_setup(tmp_path, env, [item], hf=hub, pause_for=stop_after_two)
    (job,) = setup.ensure(["voice"])
    claimed = env.jobs.claim("prepare")
    assert claimed is not None and claimed.id == job.id
    with pytest.raises(Cancelled):
        setup.run_job(claimed, _context(env, claimed))
    assert pauses.seconds == [5.0, 15.0]
    assert setup.groups_failed(["voice"]) == {}


def test_21_a_user_request_queues_a_failed_group_again(
    tmp_path: Path, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = lock_items()
    monkeypatch.setattr(fsutil, "disk_free", lambda path: 10)
    setup, _ = make_setup(tmp_path, env, items)
    setup.ensure(["align_en"])
    run_prepare_jobs(env, setup)
    assert setup.groups_failed(["align_en"])
    # A job that needs the group is not held for another try that would end the same way.
    assert setup.ensure(["align_en"]) == []
    monkeypatch.undo()

    job = setup.submit_prepare(idempotency_key=None)
    assert job.kind is JobKind.runtime_prepare and job.state is JobState.queued
    assert setup.groups_failed(["align_en"]) == {}
    assert len(prepare_jobs(env)) == 3
    run_prepare_jobs(env, setup)
    assert set(group_states(setup).values()) == {PrepareGroupState.ready}


def test_21_a_missing_wheel_fails_the_voice_group_with_model_missing(
    tmp_path: Path, env: Env
) -> None:
    items = lock_items()
    wheel = model_item(
        "package-qwen-tts", "python-wheels/qwen-tts", {"qwen_tts.whl": b"wheel"}
    )
    items.append(wheel)
    setup, _ = make_setup(tmp_path, env, items)
    (job,) = setup.ensure(["voice"])
    run_prepare_jobs(env, setup)
    failed = env.jobs.get(job.id)
    assert failed.error is not None and failed.error.code is JobErrorCode.model_missing
    assert failed.error.detail["item"] == "package-qwen-tts"
    assert setup.groups_failed(["voice"]) == {"voice": "model_missing"}


def test_21_a_second_start_makes_no_job_and_downloads_nothing(tmp_path: Path, env: Env) -> None:
    setup, transport = make_setup(tmp_path, env)
    setup.ensure(GROUP_ORDER)
    run_prepare_jobs(env, setup)
    downloaded = transport.count
    assert {state for state in group_states(setup).values()} == {PrepareGroupState.ready}

    next_start, silent = make_setup(tmp_path, env, transport=transport_for([]))
    assert next_start.ensure(GROUP_ORDER) == []
    assert next_start.groups_ready(GROUP_ORDER)
    assert prepare_jobs(env) == [] and silent.count == 0 and downloaded == 6
