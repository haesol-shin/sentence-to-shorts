"""Reference analysis: ops with origin reference, user values kept, no leftovers."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.plugins.registry import Registry
from app.ports import AppError, Cancelled, Segment
from app.schemas.change import ChangePlan, SetOp
from app.schemas.common import Origin
from app.schemas.video import ReferenceHost, ReferenceKind, Video, VideoStage
from app.services.project import state
from app.services.reference.service import ReferenceReport, ReferenceService
from app.services.reference.vision import ROUTE
from app.storage.paths import Layout
from app.storage.projects import new_typeid
from app.storage.reference import FileReferenceFrames
from tests.fixtures.media import tone_wav
from tests.media import ffmpeg
from tests.reference.support import (
    Context,
    ScriptedLlm,
    draft_video,
    make_reference,
)

pytestmark = ffmpeg.requires_ffmpeg

ANSWER: dict[str, Any] = {
    "story_structure": "hypothetical",
    "layout": "dialog_stage",
    "character_role": "subject",
    "register": "casual",
    "humor": "light",
    "progress_mode": "phases",
    "caption_mode": "typewriter",
    "bgm_mood": "tense",
    "palette": ["#FF0000", "#0000ff"],
}
LIMIT_BYTES = 314_572_800
LIMIT_MS = 180_000
JOB = "j_04tv9gfj5z81zagexeemmgpvxn"


class Store:
    def __init__(self) -> None:
        self.changes: dict[str, ChangePlan] = {}

    def new_id(self, prefix: str) -> str:
        return new_typeid(prefix)

    def put_change(self, plan: ChangePlan) -> None:
        self.changes[plan.id] = plan


class Transcriber:
    def __init__(
        self, segments: list[Segment] | None = None, error: AppError | None = None
    ) -> None:
        self.segments = segments if segments is not None else [Segment(0, 3000, "hello there")]
        self.error = error
        self.calls: list[tuple[Path, str | None]] = []

    def transcribe(self, wav: Path, language: str | None, *, cancel: Any) -> list[Segment]:
        self.calls.append((wav, language))
        assert wav.is_file()
        if self.error is not None:
            raise self.error
        return self.segments


class Downloader:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.urls: list[str] = []

    def fetch(self, url: str, *, out_dir: Path, max_bytes: int, max_ms: int, cancel: Any) -> Path:
        self.urls.append(url)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "ref_downloaded.mp4"
        shutil.copy(self.source, target)
        return target


@pytest.fixture(scope="module")
def registry() -> Registry:
    loaded = Registry()
    loaded.load()
    return loaded


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_reference(tmp_path_factory.mktemp("clips") / "synthetic.mp4")


def _service(
    registry: Registry,
    tmp_path: Path,
    llm: ScriptedLlm,
    *,
    transcriber: Transcriber | None = None,
    downloader: Any = None,
    store: Store | None = None,
    link_enabled: bool = True,
    max_bytes: int = LIMIT_BYTES,
    max_ms: int = LIMIT_MS,
) -> ReferenceService:
    return ReferenceService(
        downloader or Downloader(tmp_path / "missing.mp4"),
        ffmpeg.adapter(),
        transcriber or Transcriber(),
        llm,
        catalog=registry,
        project_store=store or Store(),
        frames=FileReferenceFrames(
            Layout(data=tmp_path / "data", cache=tmp_path / "cache")
        ),
        cache_dir=tmp_path / "cache",
        max_upload_bytes=max_bytes,
        max_upload_ms=max_ms,
        link_enabled=link_enabled,
    )


def _context(tmp_path: Path, **input: Any) -> Context:
    return Context(job_dir=tmp_path / "cache" / "j" / JOB, input=input)


def _stage_upload(tmp_path: Path, clip: Path) -> Path:
    staged = tmp_path / "staged" / "upload.bin"
    staged.parent.mkdir(parents=True)
    shutil.copy(clip, staged)
    return staged


def _work(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "r" / JOB


def _frames(tmp_path: Path, video: Video, reference_id: str) -> Path:
    return (
        tmp_path / "data" / "p" / video.project_id / "v" / video.id / "ref" / reference_id
    )


def _run(
    service: ReferenceService, ctx: Context, video: Video, clip_path: Path
) -> tuple[Any, Path]:
    source = service.ingest(clip_path, None, ctx=ctx)
    return service.analyze(source, video, ctx=ctx), source


def _plan(store: Store, change_id: str) -> ChangePlan:
    return store.changes[change_id]


def test_20_analysis_builds_ops_with_origin_reference(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    store = Store()
    llm = ScriptedLlm(ANSWER)
    service = _service(registry, tmp_path, llm, store=store)
    video = draft_video()
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    outcome, _ = _run(service, ctx, video, staged)

    plan = _plan(store, outcome.change_id)
    assert plan.source.value == "reference" and plan.status.value == "proposed"
    assert plan.base_revision == video.revision and plan.video_id == video.id
    ops = {op.path: op for op in plan.ops}
    assert all(isinstance(op, SetOp) and op.origin is Origin.reference for op in plan.ops)
    assert ops["/settings/format/story_structure"].value == "hypothetical"
    assert ops["/settings/format/layout"].value["id"] == "dialog_stage"
    assert ops["/settings/format/register"].value == "casual"
    assert ops["/settings/format/humor"].value == "light"
    assert ops["/settings/format/progress_mode"].value == "phases"
    assert ops["/settings/caption/mode"].value == "typewriter"
    assert ops["/settings/audio/bgm/mood"].value == "tense"
    assert ops["/settings/format/character_role"].value == "subject"
    assert ops["/settings/format/scene_count"].value == 3
    applied = state.apply(video, plan.ops, Origin.reference)
    assert applied.overwrites_user_values == [] and applied.locked_keys == []
    origins = applied.video.settings.origins
    assert origins["/format/register"] is Origin.reference
    assert origins["/caption/mode"] is Origin.reference
    assert state.new_issues(video, applied.video, registry) == []


def test_20_analysis_measures_the_file_and_keeps_the_summary_with_frames(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    video = draft_video()
    service = _service(registry, tmp_path, ScriptedLlm(ANSWER))
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    outcome, source = _run(service, ctx, video, staged)

    report = outcome.reference
    assert isinstance(report, ReferenceReport)
    summary = report.summary
    assert summary.kind is ReferenceKind.file and summary.host is None
    assert summary.status.value == "analyzed" and summary.source_deleted
    look = summary.style
    assert look is not None and look.palette == ["#ff0000", "#0000ff"]
    assert 1 <= len(look.frames) <= 4
    folder = _frames(tmp_path, video, summary.id)
    assert sorted(path.name for path in folder.iterdir()) == sorted(look.frames)
    measured = summary.measured
    assert measured is not None
    assert abs(measured.duration_ms - 3000) <= 150
    assert measured.scene_count == 3
    assert measured.silence_ratio < 0.1
    assert not measured.has_bgm
    assert report.style_hints.palette == ["#ff0000", "#0000ff"]
    assert not source.exists()


def test_20_analysis_keeps_four_subject_frames_and_deletes_the_rest(
    registry: Registry, tmp_path: Path
) -> None:
    long_clip = make_reference(
        tmp_path / "long.mp4", seconds=6, with_audio=False, size="1440x2560"
    )
    llm = ScriptedLlm({**ANSWER, "subject_frames": [1, 8]})
    service = _service(registry, tmp_path, llm)
    video = draft_video()
    staged = _stage_upload(tmp_path, long_clip)
    ctx = _context(tmp_path, upload_path=str(staged))
    ctx.input["upload_path"] = str(staged)

    outcome, _ = _run(service, ctx, video, staged)

    sent = [part.png for part in llm.requests[0].parts if part.kind == "png"]
    look = outcome.reference.summary.style
    assert look is not None and len(look.frames) == 4
    folder = _frames(tmp_path, video, outcome.reference.summary.id)
    stored = [(folder / name).read_bytes() for name in look.frames]
    assert all(frame in sent for frame in stored)
    assert stored[0] == sent[0] and stored[-1] == sent[-1]
    assert len(list(folder.iterdir())) == 4
    for frame in sent:
        with Image.open(io.BytesIO(frame)) as image:
            assert max(image.size) == 1280
    for frame in stored:
        with Image.open(io.BytesIO(frame)) as image:
            assert max(image.size) == 1280
    assert not _work(tmp_path).exists()


def test_20_analysis_sends_frames_and_the_transcript_only(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    llm = ScriptedLlm(ANSWER)
    service = _service(registry, tmp_path, llm)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    _run(service, ctx, draft_video(), staged)

    (request,) = llm.requests
    assert request.route == ROUTE and request.task.value == "reference_vision"
    kinds = [part.kind for part in request.parts]
    assert kinds.count("png") == 6 and kinds[-1] == "text" and kinds.count("text") == 1
    assert all(part.png is not None and part.png[:8] == b"\x89PNG\r\n\x1a\n"
               for part in request.parts if part.kind == "png")
    data = json.loads(request.parts[-1].text or "")
    assert set(data) == {"transcript", "allowed"}
    assert data["transcript"] == "hello there"
    assert set(data["allowed"]) == {"story_structures", "layouts"}
    sent = request.system + (request.parts[-1].text or "")
    for secret in (str(tmp_path), "synthetic.mp4", "upload.bin", JOB):
        assert secret not in sent
    assert ctx.stages[-1].value == "ref_llm" and len(ctx.usages) == 1


def test_20_analysis_never_sends_more_than_eight_frames(
    registry: Registry, tmp_path: Path
) -> None:
    long_clip = make_reference(tmp_path / "long.mp4", seconds=6, with_audio=False)
    llm = ScriptedLlm({})
    service = _service(registry, tmp_path, llm)
    ctx = _context(tmp_path, upload_path=str(long_clip))
    staged = _stage_upload(tmp_path, long_clip)
    ctx.input["upload_path"] = str(staged)

    outcome, _ = _run(service, ctx, draft_video(), staged)

    assert sum(part.kind == "png" for part in llm.requests[0].parts) == 8
    assert outcome.reference.summary.measured.scene_count == 6
    assert outcome.reference.summary.measured.silence_ratio == 1.0
    assert not outcome.reference.summary.measured.has_bgm


def test_20_analysis_reads_music_when_sound_carries_no_speech(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    transcriber = Transcriber(segments=[])
    service = _service(registry, tmp_path, ScriptedLlm({}), transcriber=transcriber)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    outcome, _ = _run(service, ctx, draft_video(), staged)

    assert outcome.reference.summary.measured.has_bgm
    assert transcriber.calls and transcriber.calls[0][1] is None


def test_20_analysis_keeps_values_the_user_owns(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    video = draft_video()
    raw = video.model_dump(mode="json", by_alias=True)
    raw["settings"]["origins"]["/format/register"] = "user"
    raw["settings"]["origins"]["/format/humor"] = "user"
    video = Video.model_validate(raw)
    store = Store()
    service = _service(registry, tmp_path, ScriptedLlm(ANSWER), store=store)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    outcome, _ = _run(service, ctx, video, staged)

    paths = {op.path for op in _plan(store, outcome.change_id).ops}
    assert "/settings/format/register" not in paths
    assert "/settings/format/humor" not in paths
    assert "/settings/format/progress_mode" in paths
    assert outcome.reference.kept_user_values == [
        "/settings/format/register",
        "/settings/format/humor",
    ]
    applied = state.apply(video, _plan(store, outcome.change_id).ops, Origin.reference)
    assert applied.overwrites_user_values == []
    assert applied.video.settings.format.register_value == video.settings.format.register_value
    assert applied.video.settings.format.humor == video.settings.format.humor


def test_20_analysis_leaves_locked_values_and_the_confirmed_concept(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    raw = draft_video().model_dump(mode="json", by_alias=True)
    raw["stage"] = "concept_confirmed"
    raw["settings"]["locks"] = {"bgm": "locked", "layout": "locked"}
    video = Video.model_validate(raw)
    assert video.stage is VideoStage.concept_confirmed
    store = Store()
    service = _service(registry, tmp_path, ScriptedLlm(ANSWER), store=store)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    outcome, _ = _run(service, ctx, video, staged)

    paths = {op.path for op in _plan(store, outcome.change_id).ops}
    assert "/settings/format/story_structure" not in paths
    assert "/settings/audio/bgm/mood" not in paths
    assert "/settings/format/layout" not in paths
    assert "/settings/format/register" in paths
    applied = state.apply(video, _plan(store, outcome.change_id).ops, Origin.reference)
    assert applied.locked_keys == [] and applied.concept_changes == []


def test_20_analysis_skips_combinations_the_checks_would_refuse(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    answer = {
        "layout": "full_stage",
        "caption_mode": "typewriter",
        "character_role": "none",
        "story_structure": "no_such_structure",
    }
    store = Store()
    service = _service(registry, tmp_path, ScriptedLlm(answer), store=store)
    video = draft_video()
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    outcome, _ = _run(service, ctx, video, staged)

    ops = {op.path: op for op in _plan(store, outcome.change_id).ops}
    assert "/settings/format/story_structure" not in ops
    assert "/settings/format/character_role" not in ops
    applied = state.apply(video, list(ops.values()), Origin.reference)
    assert state.new_issues(video, applied.video, registry) == []


def test_20_analysis_without_a_value_to_set_stores_no_plan(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    raw = draft_video().model_dump(mode="json", by_alias=True)
    raw["settings"]["format"]["scene_count"] = 3
    store = Store()
    service = _service(registry, tmp_path, ScriptedLlm({}), store=store)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    outcome, _ = _run(service, ctx, Video.model_validate(raw), staged)

    assert outcome.change_id is None and store.changes == {}
    assert outcome.reference.summary.status.value == "analyzed"


def test_27_reference_progress_ends_at_total(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    service = _service(registry, tmp_path, ScriptedLlm(ANSWER), store=Store())
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    _run(service, ctx, draft_video(), staged)

    assert ctx.progress_calls[-1] == (5, 5)
    steps = [done for done, _ in ctx.progress_calls]
    assert steps == sorted(steps)


def test_20_analysis_repairs_one_invalid_answer_then_fails(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    llm = ScriptedLlm({"humor": "hilarious"}, {"palette": ["red"]})
    service = _service(registry, tmp_path, llm)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))
    source = service.ingest(staged, None, ctx=ctx)

    with pytest.raises(AppError) as caught:
        service.analyze(source, draft_video(), ctx=ctx)

    assert caught.value.code == "llm_invalid_output"
    assert len(llm.requests) == 2
    first, repair = llm.requests
    assert (first.system, first.output_schema) == (repair.system, repair.output_schema)
    assert first.parts == repair.parts[:-1]
    assert "Return corrected JSON" in (repair.parts[-1].text or "")
    assert "validation_error" in (repair.parts[-1].text or "")
    assert not _work(tmp_path).exists()


def test_20_link_analysis_keeps_the_platform_and_no_address(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    url = "https://www.youtube.com/watch?v=secretvideo99"
    downloader = Downloader(clip)
    store = Store()
    service = _service(registry, tmp_path, ScriptedLlm(ANSWER), downloader=downloader, store=store)
    ctx = _context(tmp_path, url=url)

    source = service.ingest(None, url, ctx=ctx)
    outcome = service.analyze(source, draft_video(), ctx=ctx)

    assert downloader.urls == [url]
    summary = outcome.reference.summary
    assert summary.kind is ReferenceKind.link and summary.host is ReferenceHost.youtube
    stored = outcome.reference.model_dump_json() + _plan(store, outcome.change_id).model_dump_json()
    assert "secretvideo99" not in stored and "youtube.com" not in stored
    assert not _work(tmp_path).exists()


def test_20_link_is_refused_in_a_hosted_deployment(
    registry: Registry, tmp_path: Path
) -> None:
    downloader = Downloader(tmp_path / "unused.mp4")
    service = _service(
        registry, tmp_path, ScriptedLlm(), downloader=downloader, link_enabled=False
    )
    ctx = _context(tmp_path, url="https://www.youtube.com/watch?v=abc")

    with pytest.raises(AppError) as caught:
        service.ingest(None, "https://www.youtube.com/watch?v=abc", ctx=ctx)

    assert caught.value.code == "link_disabled"
    assert downloader.urls == [] and not _work(tmp_path).exists()


def test_20_link_outside_the_platforms_is_refused_before_a_download(
    registry: Registry, tmp_path: Path
) -> None:
    downloader = Downloader(tmp_path / "unused.mp4")
    service = _service(registry, tmp_path, ScriptedLlm(), downloader=downloader)
    ctx = _context(tmp_path, url="https://example.com/v.mp4")

    with pytest.raises(AppError) as caught:
        service.ingest(None, "https://example.com/v.mp4", ctx=ctx)

    assert caught.value.code == "url_not_allowed"
    assert downloader.urls == [] and not _work(tmp_path).exists()


def test_20_upload_over_the_size_limit_is_refused_and_removed(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    service = _service(registry, tmp_path, ScriptedLlm(), max_bytes=1000)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))

    with pytest.raises(AppError) as caught:
        service.ingest(staged, None, ctx=ctx)

    assert caught.value.code == "upload_invalid"
    assert caught.value.detail["reason"] == "too_large"
    assert not _work(tmp_path).exists()


def test_20_upload_over_the_length_limit_is_refused_and_removed(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    service = _service(registry, tmp_path, ScriptedLlm(), max_ms=1000)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))
    source = service.ingest(staged, None, ctx=ctx)

    with pytest.raises(AppError) as caught:
        service.analyze(source, draft_video(), ctx=ctx)

    assert caught.value.code == "upload_invalid"
    assert caught.value.detail["reason"] == "too_long"
    assert not _work(tmp_path).exists() and not source.exists()


@pytest.mark.parametrize("kind", ["audio_only", "garbage", "empty"])
def test_20_upload_that_is_not_a_video_is_refused_and_removed(
    registry: Registry, tmp_path: Path, kind: str
) -> None:
    staged = tmp_path / "staged" / "upload.bin"
    staged.parent.mkdir()
    if kind == "audio_only":
        tone_wav(staged, duration_ms=800)
    elif kind == "garbage":
        staged.write_bytes(b"not a video at all" * 100)
    else:
        staged.write_bytes(b"")
    service = _service(registry, tmp_path, ScriptedLlm())
    ctx = _context(tmp_path, upload_path=str(staged))

    with pytest.raises(AppError) as caught:
        source = service.ingest(staged, None, ctx=ctx)
        service.analyze(source, draft_video(), ctx=ctx)

    assert caught.value.code == "upload_invalid"
    assert not _work(tmp_path).exists()


def test_20_analysis_leaves_no_work_folder(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    service = _service(registry, tmp_path, ScriptedLlm(ANSWER))
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))
    source = service.ingest(staged, None, ctx=ctx)
    assert source.parent == _work(tmp_path) and staged.exists()

    service.analyze(source, draft_video(), ctx=ctx)

    assert not _work(tmp_path).exists()
    assert staged.exists()
    assert not any((tmp_path / "cache" / "r").iterdir())


def test_20_failed_analysis_leaves_no_work_folder(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    transcriber = Transcriber(error=AppError("model_missing"))
    service = _service(registry, tmp_path, ScriptedLlm(), transcriber=transcriber)
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))
    source = service.ingest(staged, None, ctx=ctx)

    with pytest.raises(AppError) as caught:
        service.analyze(source, draft_video(), ctx=ctx)

    assert caught.value.code == "model_missing"
    assert not _work(tmp_path).exists()


def test_20_cancelled_analysis_leaves_no_work_folder(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    service = _service(registry, tmp_path, ScriptedLlm())
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))
    source = service.ingest(staged, None, ctx=ctx)
    ctx.cancel.event.set()

    with pytest.raises(Cancelled):
        service.analyze(source, draft_video(), ctx=ctx)

    assert not _work(tmp_path).exists()


def test_20_cancelled_ingest_leaves_no_work_folder(
    registry: Registry, clip: Path, tmp_path: Path
) -> None:
    service = _service(registry, tmp_path, ScriptedLlm())
    staged = _stage_upload(tmp_path, clip)
    ctx = _context(tmp_path, upload_path=str(staged))
    ctx.cancel.event.set()

    with pytest.raises(Cancelled):
        service.ingest(staged, None, ctx=ctx)

    assert not _work(tmp_path).exists()
