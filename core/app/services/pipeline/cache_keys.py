"""Artifact cache keys and the key graph of one video revision.

Every cache key in the application is computed here. Keys are SHA-256 over
canonical JSON, so a value that changes an artifact changes exactly the keys
that depend on it: screen text never enters a TTS key, scene order never enters
a clip key, and sound effects enter only the mix.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import app.services.render as render_package
from app import caption_layout
from app.ports import AppError, UnknownCatalogId, canonical_json
from app.schemas.artifact import ArtifactKind
from app.schemas.common import PinnedRef
from app.schemas.font_manifest import FontManifest
from app.schemas.scene import Scene
from app.schemas.settings import CharacterSpec
from app.schemas.style_manifest import StyleManifest, Theme
from app.schemas.template_manifest import TemplateManifest
from app.schemas.text import voiced_clusters
from app.schemas.video import Video
from app.schemas.voice_manifest import VoiceManifest

if TYPE_CHECKING:
    from app.services.pipeline.types import Services

API_VERSION = 2
"""Builtin layers stopped drawing the caption box at version 2, so layer_png is redrawn."""
TIMING_API_VERSION = 2
"""Typewriter lines carry display spans from version 2, so old timing_json is not reused."""
STILL_API_VERSION = 3
"""Stills stopped drawing captions at version 3, so still_png cached earlier is not reused."""

SPEED_DECIMALS = 2

PART_SEED = 0
"""Seed handed to both part building and layer drawing.

The contracts expose no per-video seed. Builtin builders and drawers ignore it,
so one fixed value keeps keys deterministic without inventing variety input.
"""

LAYER_CANVAS = (1080, 1920)
"""Canvas a layer is drawn on, the same output frame the still uses."""

STILL_OUTPUT = (1080, 1920)
STILL_PREVIEW = (540, 960)
CLIP_FPS = 30

MIX_SAMPLE_RATE = 44100
MIX_LOUDNESS_LUFS_X10 = -160
MIX_TRUE_PEAK_DBTP_X10 = -10
MIX_DUCKING_DB_X10 = -120
SFX_GAIN_DB_X10 = -60
"""Mix values shared with the media mix contract."""

_TEXT_KIND = "text"
"""Synthetic key kind for a scene's own text, used only for change effects."""


def speed_key(speed: float) -> str:
    """TTS cache key form of a speed ratio: two decimals, for example "1.00"."""
    if round(speed, SPEED_DECIMALS) != speed:
        raise ValueError("speed is a ratio with at most two decimals")
    return f"{speed:.{SPEED_DECIMALS}f}"


def cache_key(kind: str, inputs: Mapping[str, Any], *, api_version: int = API_VERSION) -> str:
    payload = {"api_version": api_version, "inputs": inputs, "kind": kind}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _ref(ref: PinnedRef | None) -> dict[str, str] | None:
    return None if ref is None else {"id": ref.id, "revision": ref.revision}


def _model(value: Any) -> Any:
    return value.model_dump(mode="json", by_alias=True)


def _visual(scene: Scene) -> dict[str, Any]:
    """Visual inputs of a scene. SFX cues belong to the mix, not to a render key."""
    assert scene.visual is not None
    return scene.visual.model_dump(mode="json", exclude={"sfx"})


def _implementation_digest(value: object) -> str:
    """Stable identity of an object's implementation, used when a port has no runtime id."""
    owner = type(value)
    module_name = getattr(owner, "__module__", "")
    qualname = getattr(owner, "__qualname__", owner.__name__)
    module = sys.modules.get(module_name)
    source = getattr(module, "__file__", None)
    source_digest = "missing"
    if source is not None:
        try:
            source_digest = digest_file(Path(source))
        except OSError:
            source_digest = "unreadable"
    return digest_bytes(f"{module_name}.{qualname}|{source_digest}".encode())


@lru_cache(maxsize=1)
def _caption_layout_digest() -> str:
    """Digest of the caption geometry module, which decides where plates go."""
    return digest_file(Path(caption_layout.__file__).resolve())


@lru_cache(maxsize=1)
def _renderer_revision() -> str:
    """Digest of the installed renderer implementation, its cache revision."""
    root = Path(render_package.__file__).resolve().parent
    revision = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        revision.update(path.name.encode())
        revision.update(b"\0")
        revision.update(digest_file(path).encode())
        revision.update(b"\0")
    revision.update(b"caption_layout\0")
    revision.update(_caption_layout_digest().encode())
    revision.update(b"\0")
    return revision.hexdigest()


@dataclass(frozen=True)
class SceneKeys:
    tts: dict[str, str]
    parts: dict[str, str]
    layer: str | None
    still: str | None
    timing: str
    clip: str | None


class Graph:
    """All cache keys of one video revision.

    Dependencies use the digest of a published artifact when the store has it
    and the dependency key itself otherwise. A caller that publishes an
    artifact rebuilds the graph before asking for a dependent key. In symbolic
    mode every dependency is its key, so a change preview never needs the store.
    """

    def __init__(self, video: Video, services: Services, symbolic: bool = False) -> None:
        self.video = video
        self.services = services
        self.symbolic = symbolic
        self._runtime = services.key_runtime
        self._dependencies: dict[str, str] = {}
        self._style_manifest: StyleManifest | None = None
        self._theme: Theme | None = None
        self._template_manifest: TemplateManifest | None = None
        self._font_manifest: FontManifest | None = None
        self._voice_manifest: VoiceManifest | None = None
        self._tts_runtime: str | None = None
        self._aligner_runtime: str | None = None
        self._sandbox_runtime: str | None = None
        self._renderer: str | None = None
        self._encoder: str | None = None

        scenes: dict[str, SceneKeys] = {}
        for scene_id in video.scene_order:
            scene = video.scenes.get(scene_id)
            if scene is None:
                raise AppError("scene_not_found", detail={"scene_id": scene_id})
            scenes[scene_id] = self._scene_keys(scene)
        self.scenes = scenes
        self.text = {
            scene_id: self._text_key(video.scenes[scene_id])
            for scene_id in video.scene_order
        }
        self.mix = self._mix_key()
        self.final = self._final_key()
        self.srt = self._srt_key()

    # ---------------------------------------------------------- dependencies

    def _dependency(self, key: str | None) -> str | None:
        if key is None:
            return None
        if self.symbolic:
            return key
        if key in self._dependencies:
            return self._dependencies[key]
        artifact = self.services.artifact_store.find(self.video.owner_id, key)
        value = key if artifact is None else artifact.digest
        self._dependencies[key] = value
        return value

    # --------------------------------------------------------------- runtime

    def _runtime_value(self, name: str) -> str | None:
        value = getattr(self._runtime, name, None)
        return value if isinstance(value, str) and value else None

    def _tts_engine(self) -> str:
        if self._tts_runtime is None:
            explicit = self._runtime_value("tts_digest")
            if explicit is not None:
                self._tts_runtime = explicit
            else:
                engine = self.services.voice.tts.info()
                digest = engine.runtime_digest
                if not isinstance(digest, str) or not digest:
                    raise AppError("tts_not_ready", detail={"reason": "runtime_digest"})
                self._tts_runtime = digest
        return self._tts_runtime

    def _aligner(self) -> str:
        if self._aligner_runtime is None:
            explicit = self._runtime_value("aligner_digest")
            if explicit is not None:
                self._aligner_runtime = explicit
            else:
                aligner = self.services.voice.aligner
                digest = getattr(aligner, "runtime_digest", None)
                if callable(digest):
                    try:
                        digest = digest()
                    except NotImplementedError:
                        digest = None
                if isinstance(digest, str) and digest:
                    self._aligner_runtime = digest
                else:
                    self._aligner_runtime = _implementation_digest(aligner)
        return self._aligner_runtime

    def _sandbox(self) -> str:
        if self._sandbox_runtime is None:
            explicit = self._runtime_value("sandbox_digest")
            if explicit is not None:
                self._sandbox_runtime = explicit
            else:
                sandbox = self.services.templates.sandbox
                digest = getattr(sandbox, "runtime_digest", None)
                if not callable(digest):
                    raise AppError("sandbox_unavailable", detail={"reason": "runtime_digest"})
                try:
                    value = digest()
                except NotImplementedError as error:
                    raise AppError(
                        "sandbox_unavailable", detail={"reason": "runtime_digest"}
                    ) from error
                if not isinstance(value, str) or not value:
                    raise AppError("sandbox_unavailable", detail={"reason": "runtime_digest"})
                self._sandbox_runtime = value
        return self._sandbox_runtime

    def _renderer_revision(self) -> str:
        if self._renderer is None:
            explicit = self._runtime_value("renderer_revision")
            self._renderer = explicit if explicit is not None else _renderer_revision()
        return self._renderer

    def _encoder_revision(self) -> str:
        if self._encoder is None:
            explicit = self._runtime_value("encoder_digest")
            if explicit is not None:
                self._encoder = explicit
            else:
                self._encoder = _implementation_digest(self.services.assemble.media)
        return self._encoder

    # ----------------------------------------------------------------- catalog

    def _manifest(self, kind: str, ref: PinnedRef, expected: type[Any]) -> Any:
        try:
            value = self.services.catalog_port.get(kind, ref.id, ref.revision)
        except UnknownCatalogId as error:
            raise AppError(
                "unknown_catalog_id", detail={"kind": kind, "id": ref.id}
            ) from error
        if not isinstance(value, expected):
            raise AppError("unknown_catalog_id", detail={"kind": kind, "id": ref.id})
        return value

    def _style(self) -> StyleManifest:
        if self._style_manifest is None:
            self._style_manifest = self._manifest(
                "art_style", self.video.settings.visual.art_style, StyleManifest
            )
        return self._style_manifest

    def _theme_value(self) -> Theme:
        if self._theme is None:
            theme_id = self.video.settings.visual.theme_id
            theme = next(
                (item for item in self._style().themes if item.id == theme_id), None
            )
            if theme is None:
                raise AppError("unknown_catalog_id", detail={"kind": "theme", "id": theme_id})
            self._theme = theme
        return self._theme

    def _template(self) -> TemplateManifest:
        if self._template_manifest is None:
            self._template_manifest = self._manifest(
                "template", self.video.settings.format.layout, TemplateManifest
            )
        return self._template_manifest

    def _font(self) -> FontManifest:
        if self._font_manifest is None:
            self._font_manifest = self._manifest(
                "font", self.video.settings.caption.font_id, FontManifest
            )
        return self._font_manifest

    def _voice(self) -> VoiceManifest:
        if self._voice_manifest is None:
            self._voice_manifest = self._manifest(
                "voice", self.video.settings.audio.voice, VoiceManifest
            )
        return self._voice_manifest

    # ------------------------------------------------------------------- keys

    def tts_digest(self) -> str:
        """The engine digest the next TTS key would use, after a device step-down."""
        self._tts_runtime = None
        return self._tts_engine()

    def tts_key(self, line: Any) -> str:
        """The current TTS key, re-reading the engine digest.

        A synthesis may step the engine down to another device, so the digest
        captured when this graph was built can be stale by the time the WAV is
        published. The lookup and the publish must name the device that ran.
        """
        self._tts_runtime = None
        return self._tts_key(line)

    def _tts_key(self, line: Any) -> str:
        voice = self._voice()
        inputs = {
            "engine": self._tts_engine(),
            "language": self.video.settings.language.value,
            "seed": voice.settings.seed,
            "speech_text": line.speech_text,
            "speed": speed_key(voice.settings.speed),
            "voice": _ref(self.video.settings.audio.voice),
        }
        return cache_key(ArtifactKind.tts_wav.value, inputs)

    def _timing_key(self, scene: Scene, tts: Mapping[str, str]) -> str:
        inputs = {
            "aligner": self._aligner(),
            "caption_mode": self.video.settings.caption.mode.value,
            "language": self.video.settings.language.value,
            "lines": [
                {
                    "display_text": line.display_text,
                    "id": line.id,
                    "speech_text": line.speech_text,
                    "tts": self._dependency(tts[line.id]),
                }
                for line in scene.lines
            ],
            "scene_id": scene.id,
            "voice": _ref(self.video.settings.audio.voice),
        }
        return cache_key(
            ArtifactKind.timing_json.value, inputs, api_version=TIMING_API_VERSION
        )

    def _part_keys(self, scene: Scene, character: CharacterSpec | None) -> dict[str, str]:
        """Keys of every PNG the renderer or layer drawer consumes.

        Character slots come from the active spec. ``pose``, ``expression`` and
        ``skin`` are built by the same builders and consumed by the renderer or
        the layer drawer, so they need their own keys as well. A scene without
        a visual draws no parts.
        """
        assert scene.visual is not None
        style = self._style()
        theme = self._theme_value()
        style_ref = _ref(self.video.settings.visual.art_style)
        skin = next(
            (asset for asset in style.assets if asset.id == theme.skin_id), None
        )
        sandbox = self._sandbox() if style.renderer.kind == "sandbox" else None
        skin_inputs: dict[str, Any] = {
            "asset": theme.skin_id,
            "sha256": None if skin is None else skin.sha256,
            "slot": "skin",
            "style": style_ref,
            "theme": theme.id,
        }
        if sandbox is not None:
            skin_inputs["sandbox"] = sandbox
        keys: dict[str, str] = {
            "skin": cache_key(ArtifactKind.part_png.value, skin_inputs)
        }
        if character is None or not scene.visual.characters:
            return keys
        placement = scene.visual.characters[0]
        character_dump = _model(character)
        canvas = _model(style.canvas)
        slots = [
            (slot, asset_id)
            for slot, asset_id in _model(character.slots).items()
            if asset_id is not None
        ]
        slots.extend(
            [
                ("pose", placement.pose_id),
                ("expression", placement.expression_id),
            ]
        )
        for slot, asset_id in slots:
            inputs = {
                "asset": asset_id,
                "canvas": canvas,
                "character": character_dump,
                "expression": placement.expression_id,
                "pose": placement.pose_id,
                "seed": PART_SEED,
                "slot": slot,
                "style": style_ref,
            }
            if sandbox is not None:
                inputs["sandbox"] = sandbox
            keys[slot] = cache_key(ArtifactKind.part_png.value, inputs)
        return keys

    def _part_dependencies(self, parts: Mapping[str, str]) -> dict[str, str | None]:
        return {slot: self._dependency(key) for slot, key in parts.items()}

    def _layer_key(self, scene: Scene, parts: Mapping[str, str]) -> str:
        assert scene.visual is not None
        template = self._template()
        theme = self._theme_value()
        inputs: dict[str, Any] = {
            "canvas": list(LAYER_CANVAS),
            "dialog_box": template.dialog_box,
            "lines": [
                {"display_text": line.display_text, "id": line.id} for line in scene.lines
            ],
            "parts": self._part_dependencies(parts),
            "regions": _model(template.regions),
            "seed": PART_SEED,
            "style": _ref(self.video.settings.visual.art_style),
            "template": _ref(self.video.settings.format.layout),
            "theme": {"id": theme.id, "skin_id": theme.skin_id},
            "visual": _visual(scene),
        }
        if template.renderer.kind == "sandbox":
            inputs["sandbox"] = self._sandbox()
        return cache_key(ArtifactKind.layer_png.value, inputs)

    def _still_inputs(
        self, scene: Scene, parts: Mapping[str, str], layer: str | None
    ) -> dict[str, Any]:
        assert scene.visual is not None
        template = self._template()
        font = self._font()
        caption = self.video.settings.caption
        caption_inputs = caption.model_dump(
            mode="json", by_alias=True, exclude={"extra", "typing_sound"}
        )
        if caption_inputs.get("place") is None:
            caption_inputs.pop("place", None)
        highlight = bool(caption.highlight)
        lines = [
            {
                "display_text": line.display_text,
                "highlight": [_model(span) for span in line.highlight] if highlight else [],
            }
            for line in scene.lines
        ]
        title = None
        if template.regions.title is not None and self.video.script is not None:
            title = self.video.script.title
        return {
            "caption": caption_inputs,
            "font": {
                "pixel_size": font.pixel_size,
                "ref": _ref(caption.font_id),
                "sha256": font.sha256,
            },
            "geometry": _caption_layout_digest(),
            "layer": self._dependency(layer),
            "layout": {
                "dialog_box": template.dialog_box,
                "ref": _ref(self.video.settings.format.layout),
                "regions": _model(template.regions),
            },
            "lines": lines,
            "parts": self._part_dependencies(parts),
            "progress": {
                "mode": self.video.settings.format.progress_mode.value,
                "text": scene.beat_label,
            },
            "resolution": {"output": list(STILL_OUTPUT), "preview": list(STILL_PREVIEW)},
            "style": _ref(self.video.settings.visual.art_style),
            "theme": _model(self._theme_value()),
            "title": title,
            "visual": _visual(scene),
        }

    def _published_digest(self, key: str) -> str | None:
        """Digest of a verified artifact; ``None`` while it is not published."""
        if self.symbolic:
            return None
        published = self._dependency(key)
        return None if published == key else published

    def _still_key(self, inputs: Mapping[str, Any], timing: str) -> str:
        """A still drawn before speech exists records an estimated timing; once the
        timing artifact is published, the still reads it, so its key moves with it."""
        return cache_key(
            ArtifactKind.still_png.value,
            {**inputs, "timing": self._published_digest(timing)},
            api_version=STILL_API_VERSION,
        )

    def _clip_key(
        self, still_inputs: Mapping[str, Any], timing: str
    ) -> str:
        inputs = {
            "fps": CLIP_FPS,
            "motion": _model(self.video.settings.motion),
            "renderer": self._renderer_revision(),
            "still": still_inputs,
            "timing": self._dependency(timing),
        }
        return cache_key(ArtifactKind.clip_mp4.value, inputs)

    def _scene_keys(self, scene: Scene) -> SceneKeys:
        tts = {line.id: self._tts_key(line) for line in scene.lines}
        timing = self._timing_key(scene, tts)
        parts: dict[str, str] = {}
        layer: str | None = None
        still: str | None = None
        clip: str | None = None
        if scene.visual is not None:
            parts = self._part_keys(
                scene, self.video.settings.visual.character
            )
            layer = self._layer_key(scene, parts)
            still_inputs = self._still_inputs(scene, parts, layer)
            still = self._still_key(still_inputs, timing)
            clip = self._clip_key(still_inputs, timing)
        return SceneKeys(
            tts=tts,
            parts=parts,
            layer=layer,
            still=still,
            timing=timing,
            clip=clip,
        )

    def _text_key(self, scene: Scene) -> str:
        elements: list[dict[str, Any]] = []
        if scene.visual is not None:
            elements = [
                {
                    "id": element.id,
                    "kind": element.kind.value,
                    "reveal_line_id": element.reveal_line_id,
                    "value": element.value,
                }
                for element in scene.visual.elements
            ]
        inputs = {
            "beat_id": scene.beat_id,
            "beat_label": scene.beat_label,
            "elements": elements,
            "lines": [
                {
                    "display_text": line.display_text,
                    "highlight": [_model(span) for span in line.highlight],
                    "id": line.id,
                    "speech_text": line.speech_text,
                }
                for line in scene.lines
            ],
            "scene_id": scene.id,
        }
        return cache_key(_TEXT_KIND, inputs)

    def _mix_key(self) -> str:
        audio = self.video.settings.audio
        ordered: list[dict[str, Any]] = []
        for scene_id in self.video.scene_order:
            scene = self.video.scenes[scene_id]
            keys = self.scenes[scene_id]
            cues = []
            if audio.sfx_enabled and scene.visual is not None:
                cues = [
                    {
                        "at": cue.at.value,
                        "line_id": cue.line_id,
                        "offset_ms": cue.offset_ms,
                        "sfx": _ref(cue.sfx_id),
                    }
                    for cue in scene.visual.sfx
                ]
            ordered.append(
                {
                    "scene_id": scene_id,
                    "sfx": cues,
                    "timing": self._dependency(keys.timing),
                    "tts": [
                        self._dependency(keys.tts[line.id])
                        for line in scene.lines
                    ],
                    "typing": self._typing_input(scene),
                }
            )
        bgm = audio.bgm
        if bgm.enabled:
            bgm_input: dict[str, Any] = {
                "ducking_db_x10": MIX_DUCKING_DB_X10 if bgm.ducking else 0,
                "enabled": True,
                "entry": _ref(bgm.entry),
                "gain_db_x10": bgm.gain_db_x10,
            }
        else:
            bgm_input = {"ducking_db_x10": 0, "enabled": False}
        inputs = {
            "bgm": bgm_input,
            "loudness_lufs_x10": MIX_LOUDNESS_LUFS_X10,
            "sample_rate": MIX_SAMPLE_RATE,
            "scenes": ordered,
            "sfx_enabled": audio.sfx_enabled,
            "sfx_gain_db_x10": SFX_GAIN_DB_X10,
            "true_peak_dbtp_x10": MIX_TRUE_PEAK_DBTP_X10,
        }
        return cache_key(ArtifactKind.mix_wav.value, inputs)

    def _typing_input(self, scene: Scene) -> dict[str, Any]:
        """Typing sound ref and the spans that make a sound, per scene.

        A silent cluster change does not alter the typewriter character count but
        does alter which spans sound, so the mix key moves with it.
        """
        caption = self.video.settings.caption
        if (
            not self.video.settings.audio.sfx_enabled
            or caption.mode.value != "typewriter"
            or caption.typing_sound is None
        ):
            return {"sound": None, "spans": []}
        return {
            "sound": _ref(caption.typing_sound),
            "spans": [
                {"line_id": line.id, "start_char": start}
                for line in scene.lines
                for start, _ in voiced_clusters(line.display_text)
            ],
        }

    def _final_key(self) -> str:
        clips = [
            self._dependency(self.scenes[scene_id].clip)
            for scene_id in self.video.scene_order
        ]
        inputs = {
            "clips": clips,
            "encoder": {
                "fps": CLIP_FPS,
                "height": STILL_OUTPUT[1],
                "revision": self._encoder_revision(),
                "width": STILL_OUTPUT[0],
            },
            "mix": self._dependency(self.mix),
        }
        return cache_key(ArtifactKind.final_mp4.value, inputs)

    def _srt_key(self) -> str:
        ordered = [
            {
                "lines": [
                    {"display_text": line.display_text, "id": line.id}
                    for line in self.video.scenes[scene_id].lines
                ],
                "scene_id": scene_id,
                "timing": self._dependency(self.scenes[scene_id].timing),
            }
            for scene_id in self.video.scene_order
        ]
        return cache_key(ArtifactKind.srt.value, {"scenes": ordered})


__all__ = [
    "API_VERSION",
    "CLIP_FPS",
    "Graph",
    "LAYER_CANVAS",
    "PART_SEED",
    "SPEED_DECIMALS",
    "STILL_API_VERSION",
    "TIMING_API_VERSION",
    "SceneKeys",
    "cache_key",
    "canonical_json",
    "digest_bytes",
    "digest_file",
    "speed_key",
]
