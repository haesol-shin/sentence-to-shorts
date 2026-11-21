"""Project state: defaults, origin precedence, locks and semantic checks."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import _selected
from app.plugins.registry import Registry
from app.ports import AppError, Issue, TtsEngineInfo
from app.schemas.api import (
    ApiErrorCode,
    CaptionLayout,
    CreateProjectRequest,
    CreateVideoRequest,
    Problem,
    SemanticCode,
)
from app.schemas.change import ChangeSource, ReorderOp, SetOp, SetScriptOp
from app.schemas.common import Language, Origin
from app.schemas.scene import Element, ElementKind, Scene
from app.schemas.script import Line, Script
from app.schemas.settings import CaptionPosition, LockKey, LockState, Settings
from app.schemas.video import Video, VideoStage
from app.services.project import state
from app.services.project.service import ProjectService
from app.services.project.service import create as project_create
from app.storage.paths import Layout
from app.storage.projects import SqliteProjectStore
from app.storage.sqlite import Database
from tests.conftest import FIXTURES, load_json

ENGINE_ID = "qwen3-tts-0.6b"
"""The engine the dev and release profiles bind (`providers.adapters.tts`)."""

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "app" / "plugins"
CATALOG_ROOT = PLUGIN_ROOT.parent / "catalog"

DEFAULT_LOCKS = {key.value: value.value for key, value in state.DEFAULT_LOCKS.items()}


@pytest.fixture(scope="module")
def catalog() -> Registry:
    return Registry()


@pytest.fixture
def service(tmp_path: Path, catalog: Registry) -> Iterator[ProjectService]:
    layout = Layout(data=tmp_path / "data", cache=tmp_path / "cache")
    database = Database.open(layout.state_db)
    yield ProjectService(SqliteProjectStore(database, layout), catalog)
    database.close()


def new_video(service: ProjectService, language: Language = Language.ko) -> Video:
    project = service.create_project(CreateProjectRequest(title=None, language=language))
    return service.create_video(project.id, CreateVideoRequest(from_video_id=None, preset_id=None))


def set_op(path: str, value: Any, origin: Origin) -> SetOp:
    return SetOp(op="set", path=path, value=value, origin=origin)


def fixture_video() -> Video:
    return Video.model_validate(load_json("contracts/valid/video_ko_just_three.json"))


def current_bgm(video: Video, catalog: Registry) -> Video:
    """The contract fixtures pin an older revision of the builtin loop. Pin the
    registered one so each case shows only the issue it was written for."""
    bgm = video.settings.audio.bgm
    if bgm.entry is None:
        return video
    entry = catalog.pin("bgm", bgm.entry.id)
    audio = video.settings.audio.model_copy(
        update={"bgm": bgm.model_copy(update={"entry": entry})}
    )
    return video.model_copy(
        update={"settings": video.settings.model_copy(update={"audio": audio})}
    )


def test_4_defaults_make_a_valid_video_without_format_cards(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT / "story_structures", catalog_root / "story_structures")
    shutil.copytree(CATALOG_ROOT / "caption_languages", catalog_root / "caption_languages")
    without_cards = Registry(catalog_root=catalog_root)
    assert without_cards.list("format_card") == []

    for language in Language:
        settings = state.default_settings(language, without_cards)
        assert settings.format.card_id is None
        assert settings.language is language
        assert settings.origins["/language"] is Origin.user
        assert {
            origin for key, origin in settings.origins.items() if key != "/language"
        } == {Origin.default}
        video = fixture_video().model_copy(
            update={"settings": settings, "scenes": {}, "scene_order": [], "script": None}
        )
        assert state.validate(video, without_cards) == []


@pytest.mark.parametrize("profile", ["fixture", "dev", "release"])
@pytest.mark.parametrize("language", list(Language))
def test_4_default_voice_is_speakable_by_the_engine_each_profile_binds(
    app_settings: Any, catalog: Registry, profile: str, language: Language
) -> None:
    app_settings.profile = profile
    engine = _selected("tts", app_settings)
    assert engine in (ENGINE_ID, "fixed_wav")
    settings = state.default_settings(language, catalog, engine)
    voice = catalog.get("voice", settings.audio.voice.id)
    assert voice.engine_id == engine
    assert language.value in [value.value for value in voice.languages]


def test_4_service_defaults_follow_the_engine_of_the_tts_adapter(
    service: ProjectService, catalog: Registry
) -> None:
    deps = SimpleNamespace(
        project_store=service.projects,
        catalog=catalog,
        tts=SimpleNamespace(info=lambda: TtsEngineInfo(ENGINE_ID, "0" * 64, 24000, ("ko", "en"))),
    )
    bound = project_create(None, deps)  # type: ignore[arg-type]
    project = bound.create_project(CreateProjectRequest(title=None, language=Language.ko))
    assert project.defaults.audio.voice.id == "sohee_ko"


def test_4_new_video_copies_project_defaults(service: ProjectService) -> None:
    video = new_video(service, Language.en)
    project = service.projects.get_project(video.project_id)
    assert video.settings == project.defaults
    assert project.video_ids == [video.id]
    assert (video.revision, video.stage, video.topic, video.script) == (
        1,
        VideoStage.draft,
        "",
        None,
    )
    assert service.validate(video) == []


def test_5_card_change_keeps_user_value(service: ProjectService) -> None:
    video = new_video(service)
    edited = service.apply_ops(
        video, [set_op("/settings/format/humor", "light", Origin.user)], Origin.user
    )
    card = [
        set_op("/settings/format/story_structure", "single_analogy", Origin.card),
        set_op("/settings/format/humor", "none", Origin.card),
        set_op("/settings/format/card_id", "its_like", Origin.card),
    ]

    result = state.apply(edited, card, Origin.card)

    fmt = result.video.settings.format
    assert (fmt.story_structure, fmt.card_id, fmt.humor.value) == (
        "single_analogy",
        "its_like",
        "light",
    )
    assert result.overwrites_user_values == ["/settings/format/humor"]
    assert result.video.settings.origins["/format/humor"] is Origin.user
    assert result.video.settings.origins["/format/story_structure"] is Origin.card


def test_5_confirmed_overwrite_replaces_user_value(service: ProjectService) -> None:
    video = service.apply_ops(
        new_video(service), [set_op("/settings/format/humor", "light", Origin.user)], Origin.user
    )
    confirmed = state.Confirmed(overwrites=frozenset({"/settings/format/humor"}))

    result = state.apply(
        video, [set_op("/settings/format/humor", "none", Origin.card)], Origin.card, confirmed
    )

    assert result.video.settings.format.humor.value == "none"
    assert result.overwrites_user_values == []
    assert result.video.settings.origins["/format/humor"] is Origin.card


def test_5_whole_object_change_keeps_user_value_inside(service: ProjectService) -> None:
    video = service.apply_ops(
        new_video(service), [set_op("/settings/format/humor", "light", Origin.user)], Origin.user
    )
    fmt = video.settings.format.model_dump(mode="json", by_alias=True)
    replaced = {**fmt, "humor": "none", "register": "casual"}

    result = state.apply(video, [set_op("/settings/format", replaced, Origin.llm)], Origin.llm)

    assert result.video.settings.format.humor.value == "light"
    assert result.video.settings.format.register_value.value == "casual"
    assert result.overwrites_user_values == ["/settings/format/humor"]
    assert result.video.settings.origins["/format/humor"] is Origin.user


def test_5_object_op_stays_intact_and_applies_after_confirmation(
    service: ProjectService,
) -> None:
    video = service.apply_ops(
        new_video(service), [set_op("/settings/format/humor", "light", Origin.user)], Origin.user
    )
    fmt = video.settings.format.model_dump(mode="json", by_alias=True)
    op = set_op("/settings/format", {**fmt, "humor": "none"}, Origin.card)
    before = op.model_dump()

    previewed = state.apply(video, [op], Origin.card)
    assert previewed.overwrites_user_values == ["/settings/format/humor"]
    assert op.model_dump() == before

    confirmed = state.Confirmed(overwrites=frozenset(previewed.overwrites_user_values))
    applied = state.apply(video, [op], Origin.card, confirmed)
    assert applied.video.settings.format.humor.value == "none"



def test_8_locked_item_change_requires_confirmation(service: ProjectService) -> None:
    video = service.apply_ops(
        new_video(service),
        [set_op("/settings/locks", {**DEFAULT_LOCKS, "humor": "locked"}, Origin.user)],
        Origin.user,
    )
    change = [set_op("/settings/format/humor", "light", Origin.user)]

    kept = state.apply(video, change, Origin.user)
    assert kept.video.settings.format.humor.value == "none"
    assert kept.locked_keys == [LockKey.humor]

    allowed = state.apply(
        video, change, Origin.user, state.Confirmed(locks=frozenset({LockKey.humor}))
    )
    assert allowed.video.settings.format.humor.value == "light"
    assert allowed.locked_keys == []


def test_9a_chat_and_model_values_cannot_override_user_values_or_locks(
    service: ProjectService,
) -> None:
    video = service.apply_ops(
        new_video(service),
        [
            set_op("/settings/format/register", "casual", Origin.user),
            set_op("/settings/locks", {**DEFAULT_LOCKS, "humor": "locked"}, Origin.user),
        ],
        Origin.user,
    )
    model_ops = [
        set_op("/settings/format/register", "neutral", Origin.user),
        set_op("/settings/format/humor", "light", Origin.llm),
    ]

    from_model = state.apply(video, model_ops, Origin.llm)
    from_chat = state.apply(video, [model_ops[1]], state.SOURCE_ORIGIN[ChangeSource.chat])

    for result in (from_model, from_chat):
        assert result.video.settings.format.humor.value == "none"
        assert result.locked_keys == [LockKey.humor]
    assert from_model.video.settings.format.register_value.value == "casual"
    assert from_model.overwrites_user_values == ["/settings/format/register"]


def test_9a_only_user_changes_locks(service: ProjectService) -> None:
    video = new_video(service)
    with pytest.raises(AppError) as error:
        state.apply(video, [set_op("/settings/locks", {}, Origin.llm)], Origin.llm)
    assert error.value.code == "invalid_op"
    with pytest.raises(AppError):
        state.apply(video, [set_op("/settings/origins", {}, Origin.user)], Origin.user)


def test_26_apply_ops_leaves_the_input_video_unchanged(service: ProjectService) -> None:
    video = new_video(service)
    before = video.model_dump()
    changed = service.apply_ops(
        video, [set_op("/topic", "합성 주제", Origin.user)], Origin.user
    )
    assert changed.topic == "합성 주제"
    assert video.model_dump() == before
    assert service.projects.list_revisions(video.id)[-1].revision == 1


def test_26_script_rewrite_returns_to_the_concept_stage() -> None:
    video = fixture_video()
    assert video.stage is VideoStage.scenes_confirmed
    scene = next(iter(video.scenes.values()))
    rewrite = SetScriptOp(
        op="set_script",
        script=Script(source="llm", raw_text=None, title=None),
        scenes=[scene],
    )

    result = state.apply(video, [rewrite], Origin.llm)

    assert result.video.stage is VideoStage.concept_confirmed
    assert result.video.scene_order == [scene.id]


def test_26_reorder_must_keep_the_same_scenes() -> None:
    video = fixture_video()
    flipped = list(reversed(video.scene_order))
    reordered = state.apply(video, [ReorderOp(op="reorder", order=flipped)], Origin.user)
    assert reordered.video.scene_order == flipped
    with pytest.raises(AppError) as error:
        state.apply(video, [ReorderOp(op="reorder", order=flipped[1:])], Origin.user)
    assert error.value.code == "invalid_op"


def test_9a_clearing_a_parent_keeps_user_values_inside(service: ProjectService) -> None:
    video = service.apply_ops(
        new_video(service),
        [set_op("/settings/visual/character/slots/body", "body_hero", Origin.user)],
        Origin.user,
    )
    character = video.settings.visual.character

    result = state.apply(
        video, [set_op("/settings/visual/character", None, Origin.llm)], Origin.llm
    )

    assert result.video.settings.visual.character == character
    assert result.overwrites_user_values == ["/settings/visual/character/slots/body"]
    assert result.video.settings.origins["/visual/character/slots/body"] is Origin.user


def test_8_unlock_in_the_same_plan_requires_confirmation(service: ProjectService) -> None:
    video = service.apply_ops(
        new_video(service),
        [set_op("/settings/locks", {**DEFAULT_LOCKS, "humor": "locked"}, Origin.user)],
        Origin.user,
    )
    ops = [
        set_op("/settings/locks", DEFAULT_LOCKS, Origin.user),
        set_op("/settings/format/humor", "light", Origin.user),
    ]

    kept = state.apply(video, ops, state.SOURCE_ORIGIN[ChangeSource.chat])
    assert kept.video.settings.format.humor.value == "none"
    assert kept.video.settings.locks == video.settings.locks
    assert kept.locked_keys == [LockKey.humor]

    confirmed = state.Confirmed(locks=frozenset({LockKey.humor}))
    allowed = state.apply(video, ops, Origin.user, confirmed)
    assert allowed.video.settings.format.humor.value == "light"
    assert allowed.video.settings.locks == state.DEFAULT_LOCKS


def test_8_emptied_and_refilled_visual_keeps_a_locked_background() -> None:
    base = fixture_video()
    locks = {LockKey.background: LockState.locked}
    video = base.model_copy(
        update={"settings": base.settings.model_copy(update={"locks": locks})}
    )
    scene_id = video.scene_order[0]
    visual = video.scenes[scene_id].visual
    assert visual is not None and visual.background_id == "bg_village"
    other = visual.model_dump(mode="json") | {"background_id": "bg_stars"}
    ops = [
        set_op(f"/scenes/{scene_id}/visual", None, Origin.user),
        set_op(f"/scenes/{scene_id}/visual", other, Origin.user),
    ]

    result = state.apply(video, ops, Origin.user)

    kept = result.video.scenes[scene_id].visual
    assert kept is not None and kept.background_id == "bg_village"
    assert result.locked_keys == [LockKey.background]


def test_4_unknown_asset_element_is_rejected(catalog: Registry) -> None:
    base = current_bgm(fixture_video(), catalog)
    scene_id = base.scene_order[0]
    scene = base.scenes[scene_id]
    assert scene.visual is not None

    def with_asset(value: str) -> Video:
        element = Element(
            id="e_0wyybe1tnp8fktk2g80mbghwh9",
            kind=ElementKind.asset,
            value=value,
            anchor="top",
            reveal_line_id=None,
        )
        visual = scene.visual.model_copy(update={"elements": [element]})
        edited = scene.model_copy(update={"visual": visual})
        return base.model_copy(update={"scenes": {**base.scenes, scene_id: edited}})

    assert state.validate(with_asset("icon_arrow"), catalog) == []
    issues = state.validate(with_asset("missing_asset"), catalog)
    assert [(issue.pointer, issue.code) for issue in issues] == [
        (f"/scenes/{scene_id}/visual/elements/0/value", "unknown_catalog_id")
    ]



TWO_LINE_KO = (
    "커피를 고르는 기준은 세 가지뿐이다. "
    "좋은 원두와 물의 온도, 그리고 비율이 만든다."
)
TWO_LINE_EN = (
    "The only criteria for choosing coffee are freshness, roast date, and grind size."
)
SHORT_EN = "A short translation."


def extra_layer(
    catalog: Registry,
    *,
    font: str = "galmuri11",
    position: str = "top",
    mode: str = "sentence",
    language: str = "en",
) -> dict[str, Any]:
    return {
        "language": language,
        "mode": mode,
        "font_id": catalog.pin("font", font).model_dump(),
        "position": position,
    }


def with_extra(
    video: Video,
    catalog: Registry,
    *,
    layout: str = "fixed_stage",
    font: str = "galmuri11",
    position: str = "top",
    primary_position: str = "bottom",
    mode: str = "sentence",
    texts: bool = True,
    display: str | None = None,
    translated: str = SHORT_EN,
) -> Video:
    """The fixture video with one extra caption layer, optionally translated."""
    doc = video.model_dump(mode="json")
    doc["settings"]["format"]["layout"] = catalog.pin("template", layout).model_dump()
    doc["settings"]["caption"]["font_id"] = catalog.pin("font", font).model_dump()
    doc["settings"]["caption"]["position"] = primary_position
    doc["settings"]["caption"]["extra"] = [
        extra_layer(catalog, font=font, position=position, mode=mode)
    ]
    for scene in doc["scenes"].values():
        for line in scene["lines"]:
            if display is not None:
                line["display_text"] = display
                line["speech_text"] = display
            line["extra_texts"] = (
                [{"language": "en", "text": translated}] if texts else []
            )
    return Video.model_validate(doc)


def store_caption_video(
    client: TestClient, catalog: Registry, *, layout: str = "fixed_stage", extra: bool = True
) -> Video:
    app = client.app.state.runtime  # type: ignore[attr-defined]
    project = app.services.project.create_project(CreateProjectRequest(title=None, language="ko"))
    video = with_extra(current_bgm(fixture_video(), catalog), catalog, layout=layout)
    if not extra:
        video.settings.caption.extra = []
    return app.project_store.append_revision(
        video.model_copy(update={"project_id": project.id, "revision": 1})
    )


def test_29_caption_layout_matches_save_check_for_every_pair(
    client: TestClient, catalog: Registry
) -> None:
    video = store_caption_video(client, catalog)
    response = client.get(f"/api/v1/videos/{video.id}/caption-layout")
    assert response.status_code == 200, response.text
    result = CaptionLayout.model_validate(response.json())
    assert len(result.pairs) == len(CaptionPosition) ** 2
    assert {(pair.primary, pair.extra) for pair in result.pairs} == {
        (primary, extra) for primary in CaptionPosition for extra in CaptionPosition
    }
    assert {pair.fits for pair in result.pairs} == {False, True}
    for pair in result.pairs:
        candidate = video.model_copy(deep=True)
        candidate.settings.caption.position = pair.primary
        candidate.settings.caption.extra[0].position = pair.extra
        codes = {issue.code for issue in state.validate(candidate, catalog)}
        assert pair.fits == ("caption_overlap" not in codes), pair


def test_29_caption_layout_overrides_change_pairs_without_saving(
    client: TestClient, catalog: Registry
) -> None:
    video = store_caption_video(client, catalog, extra=False)
    path = f"/api/v1/videos/{video.id}/caption-layout"
    font = catalog.pin("font", "galmuri14").model_dump_json()
    for params, sizes in (
        ({"extra_language": "en"}, (22, 22)),
        ({"extra_language": "en", "extra_font_id": font}, (22, 28)),
        ({"extra_language": "en", "font_id": font}, (28, 28)),
    ):
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        result = CaptionLayout.model_validate(response.json())
        assert (result.primary_px, result.extra_px) == sizes
        upper_lower = next(
            pair for pair in result.pairs
            if pair.primary == CaptionPosition.upper and pair.extra == CaptionPosition.lower
        )
        assert upper_lower.fits == (sizes == (22, 22))
    saved = client.get(f"/api/v1/videos/{video.id}")
    assert saved.status_code == 200, saved.text
    assert Video.model_validate(saved.json()["video"]) == video


def test_29_caption_layout_dialog_rejects_all_pairs(client: TestClient, catalog: Registry) -> None:
    video = store_caption_video(client, catalog, layout="dialog_stage")
    response = client.get(f"/api/v1/videos/{video.id}/caption-layout")
    assert response.status_code == 200, response.text
    result = CaptionLayout.model_validate(response.json())
    assert len(result.pairs) == 25
    assert not any(pair.fits for pair in result.pairs)


def test_29_caption_layout_single_layer_lists_five_positions(
    client: TestClient, catalog: Registry
) -> None:
    video = store_caption_video(client, catalog, extra=False)
    response = client.get(f"/api/v1/videos/{video.id}/caption-layout")
    assert response.status_code == 200, response.text
    result = CaptionLayout.model_validate(response.json())
    assert result.extra_px is None
    assert [(pair.primary, pair.extra, pair.fits) for pair in result.pairs] == [
        (position, position, True) for position in CaptionPosition
    ]


def test_29_two_layers_with_translations_have_no_issue(catalog: Registry) -> None:
    video = with_extra(current_bgm(fixture_video(), catalog), catalog)
    assert state.validate(video, catalog) == []


def test_29_missing_translation_is_reported_per_line(catalog: Registry) -> None:
    video = with_extra(current_bgm(fixture_video(), catalog), catalog, texts=False)
    issues = state.validate(video, catalog)
    assert {issue.code for issue in issues} == {"caption_text_missing"}
    assert len(issues) == sum(len(scene.lines) for scene in video.scenes.values())
    assert issues[0].pointer.endswith("/extra_texts")


def test_29_extra_layer_mode_must_be_sentence(catalog: Registry) -> None:
    video = with_extra(
        current_bgm(fixture_video(), catalog), catalog, mode="phrase"
    )
    assert [(issue.pointer, issue.code) for issue in state.validate(video, catalog)] == [
        ("/settings/caption/extra/0/mode", "caption_mode_language")
    ]


def test_29_extra_layer_needs_a_moving_plate_template(catalog: Registry) -> None:
    video = with_extra(
        current_bgm(fixture_video(), catalog), catalog, layout="dialog_stage"
    )
    assert [(issue.pointer, issue.code) for issue in state.validate(video, catalog)] == [
        ("/settings/caption/extra/0", "caption_layer_unsupported")
    ]


def test_29_two_line_layers_that_collide_are_reported(catalog: Registry) -> None:
    video = with_extra(
        current_bgm(fixture_video(), catalog),
        catalog,
        font="galmuri14",
        position="lower",
        primary_position="upper",
        display=TWO_LINE_KO,
        translated=TWO_LINE_EN,
    )
    issues = state.validate(video, catalog)
    assert {issue.code for issue in issues} == {"caption_overlap"}
    assert len(issues) == sum(len(scene.lines) for scene in video.scenes.values())


def test_29_middle_position_collides_at_the_smallest_sizes(catalog: Registry) -> None:
    video = with_extra(
        current_bgm(fixture_video(), catalog),
        catalog,
        position="bottom",
        primary_position="middle",
        display=TWO_LINE_KO,
        translated=TWO_LINE_EN,
    )
    issues = state.validate(video, catalog)
    assert {issue.code for issue in issues} == {"caption_overlap"}
    assert len(issues) == sum(len(scene.lines) for scene in video.scenes.values())


def test_29_layer_and_texts_are_added_as_one_change(catalog: Registry) -> None:
    before = current_bgm(fixture_video(), catalog)
    after = with_extra(before, catalog)
    assert state.new_issues(before, after, catalog) == []

    layer_only = with_extra(before, catalog, texts=False)
    assert {issue.code for issue in state.new_issues(before, layer_only, catalog)} == {
        "caption_text_missing"
    }


def _embed(name: str, data: dict[str, Any]) -> Video:
    """Place a semantic fixture inside the valid Korean video it was cut from."""
    base = fixture_video()
    first = base.scene_order[0]
    if name == "highlight_out_of_range":
        scene = base.scenes[first]
        lines = [Line.model_validate(data), *scene.lines[1:]]
        edited = scene.model_copy(update={"lines": lines})
        return base.model_copy(update={"scenes": {**base.scenes, first: edited}})
    if name in {"unknown_asset_id", "duplicate_line_id", "reveal_line_unknown", "typing_cue"}:
        scene = Scene.model_validate(data)
        return base.model_copy(update={"scenes": {**base.scenes, scene.id: scene}})
    if "scene_order" in data:
        return Video.model_validate(data)
    return base.model_copy(update={"settings": Settings.model_validate(data)})


SEMANTIC = sorted(
    name.removesuffix(".json")
    for name, expect in load_json("contracts/invalid/expect.json")["files"].items()
    if expect["level"] == "semantic" and name != "stale_base_revision_request.json"
)


@pytest.mark.parametrize("name", SEMANTIC)
def test_4_semantic_fixture_returns_expected_code(name: str, catalog: Registry) -> None:
    expected = load_json("contracts/invalid/expect.json")["files"][f"{name}.json"]["code"]
    video = current_bgm(_embed(name, load_json(f"contracts/invalid/{name}.json")), catalog)

    codes = {issue.code for issue in state.validate(video, catalog)}

    assert codes == {expected}


@pytest.mark.parametrize(
    "name", sorted(path.stem for path in (FIXTURES / "contracts" / "valid").glob("video_*.json"))
)
def test_4_valid_videos_have_no_semantic_issue(name: str, catalog: Registry) -> None:
    video = Video.model_validate(load_json(f"contracts/valid/{name}.json"))
    assert state.validate(current_bgm(video, catalog), catalog) == []


def test_4_leaving_typewriter_requires_clearing_the_typing_sound(
    catalog: Registry,
) -> None:
    video = current_bgm(
        Video.model_validate(load_json("contracts/valid/video_ko_typewriter_typing.json")),
        catalog,
    )
    assert state.validate(video, catalog) == []
    mode = SetOp(
        op="set", path="/settings/caption/mode", value="sentence", origin=Origin.user
    )
    kept = state.apply(video, [mode], Origin.user).video
    assert [(issue.pointer, issue.code) for issue in state.validate(kept, catalog)] == [
        ("/settings/caption/typing_sound", "typing_sound_mode")
    ]
    cleared = state.apply(
        video,
        [
            mode,
            SetOp(
                op="set",
                path="/settings/caption/typing_sound",
                value=None,
                origin=Origin.user,
            ),
        ],
        Origin.user,
    ).video
    assert cleared.settings.caption.typing_sound is None
    assert state.validate(cleared, catalog) == []


def extra_op(catalog: Registry, **layer: Any) -> dict[str, Any]:
    """Replace the extra caption layers with one layer built from ``layer``."""
    return set_op(
        "/settings/caption/extra",
        [extra_layer(catalog, **layer)],
        Origin.user,
    ).model_dump(mode="json")


def post_caption_change(
    client: TestClient, video: Video, ops: list[dict[str, Any]]
) -> Any:
    plan = client.post(
        f"/api/v1/videos/{video.id}/changes",
        json={
            "base_revision": video.revision,
            "source": "direct",
            "target": {"scene_id": None, "pointer": None},
            "ops": ops,
        },
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    if body["status"] != "proposed":
        return plan
    return client.post(
        f"/api/v1/changes/{body['id']}/apply", json={"base_revision": video.revision}
    )


def test_30_overlapping_caption_layers_list_the_failing_lines(
    client: TestClient, catalog: Registry
) -> None:
    video = store_caption_video(client, catalog)
    response = post_caption_change(
        client,
        video,
        [
            set_op("/settings/caption/position", "top", Origin.user).model_dump(mode="json"),
            set_op(
                "/settings/caption/font_id",
                catalog.pin("font", "galmuri14").model_dump(),
                Origin.user,
            ).model_dump(mode="json"),
        ],
    )
    assert response.status_code == 422, response.text
    body = Problem.model_validate(response.json())
    assert body.code is ApiErrorCode.invalid_combination
    assert {item.code for item in body.errors} == {SemanticCode.caption_overlap}
    assert {item.pointer for item in body.errors} == {
        f"/scenes/{scene_id}/lines/{index}"
        for scene_id, scene in video.scenes.items()
        for index in range(len(scene.lines))
    }


def test_30_second_layer_mode_other_than_sentence_is_listed(
    client: TestClient, catalog: Registry
) -> None:
    video = store_caption_video(client, catalog)
    response = post_caption_change(
        client,
        video,
        [extra_op(catalog, mode="phrase")],
    )
    assert response.status_code == 422, response.text
    body = Problem.model_validate(response.json())
    assert [(item.pointer, item.code) for item in body.errors] == [
        ("/settings/caption/extra/0/mode", SemanticCode.caption_mode_language)
    ]


def test_30_unknown_catalog_id_is_listed(client: TestClient, catalog: Registry) -> None:
    video = store_caption_video(client, catalog)
    response = post_caption_change(
        client, video, [extra_op(catalog, language="no_such_language")]
    )
    assert response.status_code in (404, 422), response.text
    body = Problem.model_validate(response.json())
    assert (
        "/settings/caption/extra/0/language",
        SemanticCode.unknown_catalog_id,
    ) in [(item.pointer, item.code) for item in body.errors]


def test_30_problem_errors_are_capped_at_the_schema_limit(client: TestClient) -> None:
    issues = [Issue(f"/scenes/s/lines/{index}", "caption_overlap") for index in range(150)]
    runtime = client.app.state.runtime  # type: ignore[attr-defined]

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AppError("invalid_combination", errors=issues)

    runtime.services.project.create_project = fail
    response = client.post("/api/v1/projects", json={"title": None, "language": "ko"})
    assert response.status_code == 422, response.text
    body = Problem.model_validate(response.json())
    assert [item.pointer for item in body.errors] == [issue.pointer for issue in issues[:100]]
