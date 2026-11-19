"""Cache key graph invariants: scoped changes, identities and dependencies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.plugins.registry import Registry
from app.schemas.video import Video
from app.services.pipeline.cache_keys import Graph, cache_key, canonical_json, speed_key
from app.services.pipeline.types import KeyRuntime

VALID = Path(__file__).resolve().parents[3] / "fixtures" / "contracts" / "valid"
RUNTIME = KeyRuntime(
    tts_digest="1" * 64,
    sandbox_digest="2" * 64,
    aligner_digest="3" * 64,
    renderer_revision="4" * 64,
    encoder_digest="5" * 64,
)


class MemoryStore:
    """Only the lookup the graph uses: a cache key maps to a verified digest."""

    def __init__(self) -> None:
        self.entries: dict[str, SimpleNamespace] = {}

    def find(self, owner_id: str, key: str) -> SimpleNamespace | None:
        return self.entries.get(key)

    def publish(self, key: str, digest: str) -> None:
        self.entries[key] = SimpleNamespace(digest=digest)


def _load_video() -> Video:
    return Video.model_validate(
        json.loads((VALID / "video_ko_just_three.json").read_text(encoding="utf-8"))
    )


def _services(registry: Registry, store: object) -> SimpleNamespace:
    return SimpleNamespace(
        artifact_store=store,
        catalog_port=registry,
        key_runtime=RUNTIME,
    )


def _changed(video: Video, mutate) -> Video:  # type: ignore[no-untyped-def]
    data = video.model_dump(mode="json")
    mutate(data)
    return Video.model_validate(data)


def _new_id(value: str, used: set[str]) -> str:
    prefix, _, body = value.partition("_")
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
    for character in alphabet:
        candidate = f"{prefix}_{body[:-1]}{character}"
        if candidate not in used:
            return candidate
    raise AssertionError("no free id")


def _keys(graph: Graph):  # type: ignore[no-untyped-def]
    for scene in graph.scenes.values():
        yield from scene.tts.values()
        yield from scene.parts.values()
        for key in (scene.layer, scene.still, scene.timing, scene.clip):
            if key is not None:
                yield key
    yield from graph.text.values()
    yield graph.mix
    yield graph.final
    yield graph.srt


@pytest.fixture(scope="session")
def registry() -> Registry:
    loaded = Registry()
    loaded.load()
    return loaded


@pytest.fixture
def video() -> Video:
    return _load_video()


def test_11_screen_text_change_keeps_tts_keys(registry: Registry, video: Video) -> None:
    def mutate(data):  # type: ignore[no-untyped-def]
        scene = data["scenes"][data["scene_order"][0]]
        scene["lines"][0]["display_text"] = "새 화면 글"

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)
    scene_id = video.scene_order[0]

    for candidate in video.scene_order:
        assert before.scenes[candidate].tts == after.scenes[candidate].tts
    assert before.text[scene_id] != after.text[scene_id]
    assert before.scenes[scene_id].parts == after.scenes[scene_id].parts
    assert before.scenes[scene_id].still != after.scenes[scene_id].still


def test_11_speech_change_touches_only_that_line_tts(registry: Registry, video: Video) -> None:
    scene_id = video.scene_order[0]
    line_id = video.scenes[scene_id].lines[0].id

    def mutate(data):  # type: ignore[no-untyped-def]
        data["scenes"][scene_id]["lines"][0]["speech_text"] = "다른 말"

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)

    for candidate in video.scene_order:
        for line in video.scenes[candidate].lines:
            same = before.scenes[candidate].tts[line.id] == after.scenes[candidate].tts[line.id]
            if candidate == scene_id and line.id == line_id:
                assert not same
            else:
                assert same
    assert before.text[scene_id] != after.text[scene_id]
    assert before.scenes[scene_id].parts == after.scenes[scene_id].parts
    assert before.scenes[scene_id].layer == after.scenes[scene_id].layer
    assert before.scenes[scene_id].still == after.scenes[scene_id].still
    assert before.scenes[scene_id].timing != after.scenes[scene_id].timing
    assert before.scenes[scene_id].clip != after.scenes[scene_id].clip
    assert before.mix != after.mix
    assert before.final != after.final
    assert before.srt != after.srt


def test_12_reorder_keeps_scene_keys_and_changes_ordered_audio(
    registry: Registry, video: Video
) -> None:
    def mutate(data):  # type: ignore[no-untyped-def]
        data["scene_order"] = list(reversed(data["scene_order"]))

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)

    for scene_id in video.scene_order:
        assert before.scenes[scene_id] == after.scenes[scene_id]
        assert before.scenes[scene_id].clip == after.scenes[scene_id].clip
    assert before.text == after.text
    assert before.mix != after.mix
    assert before.final != after.final
    assert before.srt != after.srt


def test_14_bgm_change_changes_mix_and_final_only(registry: Registry, video: Video) -> None:
    entry = registry.pin("bgm", "calm_snowfall").model_dump(mode="json")

    def mutate(data):  # type: ignore[no-untyped-def]
        data["settings"]["audio"]["bgm"]["entry"] = entry

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)

    assert before.scenes == after.scenes
    assert before.text == after.text
    assert before.srt == after.srt
    assert before.mix != after.mix
    assert before.final != after.final


def test_14_sfx_change_changes_mix_not_visual_keys(registry: Registry, video: Video) -> None:
    sfx = registry.pin("sfx", "pop").model_dump(mode="json")

    def mutate(data):  # type: ignore[no-untyped-def]
        scene = data["scenes"][data["scene_order"][0]]
        scene["visual"]["sfx"] = [
            {
                "sfx_id": sfx,
                "line_id": scene["lines"][0]["id"],
                "at": "start",
                "offset_ms": 0,
            }
        ]

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)

    assert before.scenes == after.scenes
    assert before.text == after.text
    assert before.srt == after.srt
    assert before.mix != after.mix
    assert before.final != after.final


def test_08_parts_cover_every_consumed_png(registry: Registry, video: Video) -> None:
    services = _services(registry, MemoryStore())
    scene_id = video.scene_order[0]
    graph = Graph(video, services, symbolic=True)
    parts = graph.scenes[scene_id].parts
    assert {"body", "face", "skin", "pose", "expression"} <= set(parts)
    assert not {"hair", "hat", "outfit", "prop"} & set(parts)

    def no_character(data):  # type: ignore[no-untyped-def]
        data["scenes"][scene_id]["visual"]["characters"] = []

    stripped = Graph(_changed(video, no_character), services, symbolic=True)
    assert set(stripped.scenes[scene_id].parts) == {"skin"}

    def no_visual(data):  # type: ignore[no-untyped-def]
        data["scenes"][scene_id]["visual"] = None

    empty = Graph(_changed(video, no_visual), services, symbolic=True)
    assert empty.scenes[scene_id].parts == {}
    assert empty.scenes[scene_id].layer is None
    assert empty.scenes[scene_id].still is None
    assert empty.scenes[scene_id].clip is None


def test_08_timing_key_includes_scene_and_line_identity(
    registry: Registry, video: Video
) -> None:
    data = video.model_dump(mode="json")
    original_id = data["scene_order"][0]
    duplicate = json.loads(json.dumps(data["scenes"][original_id]))
    used_scenes = set(data["scenes"])
    duplicate["id"] = _new_id(original_id, used_scenes)
    used_lines = {
        line["id"] for scene in data["scenes"].values() for line in scene["lines"]
    }
    for line in duplicate["lines"]:
        line["id"] = _new_id(line["id"], used_lines)
        used_lines.add(line["id"])
    data["scenes"][duplicate["id"]] = duplicate
    data["scene_order"] = [original_id, duplicate["id"]]
    twin = Video.model_validate(data)

    graph = Graph(twin, _services(registry, MemoryStore()), symbolic=True)
    assert list(graph.scenes[original_id].tts.values()) == list(
        graph.scenes[duplicate["id"]].tts.values()
    )
    assert graph.scenes[original_id].timing != graph.scenes[duplicate["id"]].timing
    assert graph.text[original_id] != graph.text[duplicate["id"]]


def test_08_artifact_digest_is_used_for_dependent_keys(
    registry: Registry, video: Video
) -> None:
    store = MemoryStore()
    services = _services(registry, store)
    missing = Graph(video, services)
    symbolic = Graph(video, services, symbolic=True)
    assert missing.scenes == symbolic.scenes
    assert missing.mix == symbolic.mix
    assert missing.final == symbolic.final
    assert missing.srt == symbolic.srt

    scene_id = video.scene_order[0]
    for key in missing.scenes[scene_id].parts.values():
        store.publish(key, hashlib.sha256(key.encode()).hexdigest())
    published = Graph(video, services)

    assert published.scenes[scene_id].parts == missing.scenes[scene_id].parts
    assert published.scenes[scene_id].layer != missing.scenes[scene_id].layer
    assert published.scenes[scene_id].still != missing.scenes[scene_id].still
    assert published.scenes[scene_id].clip != missing.scenes[scene_id].clip
    assert published.mix == missing.mix
    still_symbolic = Graph(video, services, symbolic=True)
    assert still_symbolic.scenes == symbolic.scenes
    assert still_symbolic.mix == symbolic.mix
    assert still_symbolic.final == symbolic.final
    assert still_symbolic.srt == symbolic.srt


def test_08_published_tts_digest_changes_timing_and_mix(
    registry: Registry, video: Video
) -> None:
    store = MemoryStore()
    services = _services(registry, store)
    before = Graph(video, services)
    scene_id = video.scene_order[0]
    line_id = video.scenes[scene_id].lines[0].id
    key = before.scenes[scene_id].tts[line_id]
    store.publish(key, hashlib.sha256(key.encode()).hexdigest())

    after = Graph(video, services)
    assert after.scenes[scene_id].tts[line_id] == key
    assert after.scenes[scene_id].timing != before.scenes[scene_id].timing
    assert after.mix != before.mix
    assert after.srt != before.srt


def test_08_cache_key_rejects_float_and_formats_speed(registry: Registry, video: Video) -> None:
    with pytest.raises(TypeError):
        cache_key("tts_wav", {"speed": 1.0})
    with pytest.raises(TypeError):
        canonical_json({"gain_db": -3.5})
    assert speed_key(1.0) == "1.00"
    assert speed_key(0.8) == "0.80"
    with pytest.raises(ValueError):
        speed_key(1.005)

    graph = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    for key in _keys(graph):
        assert len(key) == 64
        assert all(character in "0123456789abcdef" for character in key)


def test_08_renderer_revision_digests_the_render_package(
    registry: Registry, video: Video
) -> None:
    render_root = Path(__file__).resolve().parents[2] / "app" / "services" / "render"
    expected = hashlib.sha256()
    for path in sorted(render_root.glob("*.py")):
        expected.update(path.name.encode())
        expected.update(b"\0")
        expected.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
        expected.update(b"\0")
    revision = expected.hexdigest()

    def graph(renderer_revision: str | None) -> Graph:
        services = _services(registry, MemoryStore())
        services.key_runtime = replace(RUNTIME, renderer_revision=renderer_revision)
        return Graph(video, services, symbolic=True)

    installed = graph(None)
    assert installed.scenes == graph(revision).scenes
    assert installed.scenes != graph("0" * 64).scenes


def _typing_video() -> Video:
    return Video.model_validate(
        json.loads(
            (VALID / "video_ko_typewriter_typing.json").read_text(encoding="utf-8")
        )
    )


def test_14_typing_sound_change_moves_mix_but_not_timing_or_still(
    registry: Registry,
) -> None:
    video = _typing_video()

    def mutate(data):  # type: ignore[no-untyped-def]
        data["settings"]["caption"]["typing_sound"] = registry.pin(
            "sfx", "typing_fast"
        ).model_dump()

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)
    scene_id = video.scene_order[0]
    assert before.scenes[scene_id].timing == after.scenes[scene_id].timing
    assert before.scenes[scene_id].still == after.scenes[scene_id].still
    assert before.scenes[scene_id].clip == after.scenes[scene_id].clip
    assert before.mix != after.mix


def test_14_silent_character_change_moves_the_mix_key(registry: Registry) -> None:
    video = _typing_video()
    scene_id = video.scene_order[0]

    def mutate(data):  # type: ignore[no-untyped-def]
        data["scenes"][scene_id]["lines"][0]["display_text"] = "타자."

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)
    assert before.scenes[scene_id].tts == after.scenes[scene_id].tts
    assert before.mix != after.mix


def test_14_sfx_switch_moves_the_typing_mix_key(registry: Registry) -> None:
    video = _typing_video()

    def mutate(data):  # type: ignore[no-untyped-def]
        data["settings"]["audio"]["sfx_enabled"] = False

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)
    assert before.mix != after.mix


def _with_extra_layer(
    video: Video,
    registry: Registry,
    *,
    font: str = "galmuri11",
    text: str = "A short translation.",
) -> Video:
    data = video.model_dump(mode="json")
    font_ref = registry.pin("font", font).model_dump()
    data["settings"]["caption"]["font_id"] = font_ref
    data["settings"]["caption"]["extra"] = [
        {
            "language": "en",
            "mode": "sentence",
            "font_id": font_ref,
            "position": "top",
        }
    ]
    for scene in data["scenes"].values():
        for line in scene["lines"]:
            line["extra_texts"] = [{"language": "en", "text": text}]
    return Video.model_validate(data)


def test_29_extra_text_moves_the_still_but_not_speech_or_srt(
    registry: Registry,
) -> None:
    video = _with_extra_layer(_load_video(), registry)
    scene_id = video.scene_order[0]

    def mutate(data):  # type: ignore[no-untyped-def]
        data["scenes"][scene_id]["lines"][0]["extra_texts"][0]["text"] = "Another one."

    changed = _changed(video, mutate)
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)
    after = Graph(changed, _services(registry, MemoryStore()), symbolic=True)

    assert before.scenes[scene_id].still != after.scenes[scene_id].still
    assert before.scenes[scene_id].clip != after.scenes[scene_id].clip
    for candidate in video.scene_order:
        assert before.scenes[candidate].tts == after.scenes[candidate].tts
        assert before.scenes[candidate].timing == after.scenes[candidate].timing
    assert before.srt == after.srt
    assert before.mix == after.mix


def test_29_extra_font_and_language_move_the_still(registry: Registry) -> None:
    video = _with_extra_layer(_load_video(), registry, font="galmuri14")
    scene_id = video.scene_order[0]
    before = Graph(video, _services(registry, MemoryStore()), symbolic=True)

    def change_font(data):  # type: ignore[no-untyped-def]
        data["settings"]["caption"]["extra"][0]["font_id"] = registry.pin(
            "font", "galmuri11"
        ).model_dump()

    def change_language(data):  # type: ignore[no-untyped-def]
        data["settings"]["caption"]["extra"][0]["language"] = "ko"

    for mutate in (change_font, change_language):
        after = Graph(
            _changed(video, mutate), _services(registry, MemoryStore()), symbolic=True
        )
        assert before.scenes[scene_id].still != after.scenes[scene_id].still
        assert before.scenes[scene_id].timing == after.scenes[scene_id].timing
        assert before.srt == after.srt
