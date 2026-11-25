"""Generated style, template and code BGM packages.

Each route asks the model for code, runs it only through the sandbox port,
checks the validated output, writes a package into a staging folder of the job
and registers it through the catalog. A failure removes the staging folder and
leaves every earlier package, including the previous BGM, as it was.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.caption_layout import safe_area
from app.ports import (
    AppError,
    AppSettings,
    CatalogPort,
    JobContext,
    LayerDrawer,
    LlmPort,
    LlmTask,
    PartsBuilder,
    SandboxPort,
    ServiceDeps,
    StyleFrames,
    UnknownCatalogId,
    ValidatedOutput,
    canonical_digest,
)
from app.schemas.api import BgmCodeRequest, StyleRequest, TemplateRequest
from app.schemas.bgm_entry import BgmParams, CodeBgm
from app.schemas.common import (
    TYPEID_PATTERN,
    LocalizedText,
    PackageOrigin,
    PackageStatus,
    PinnedRef,
    Provenance,
)
from app.schemas.job import Stage, Usage
from app.schemas.sandbox_io import SandboxKind
from app.schemas.scene import Scene
from app.schemas.settings import CharacterSlots, CharacterSpec
from app.schemas.style_manifest import AssetKind, SandboxRenderer, StyleAsset, StyleManifest
from app.schemas.template_manifest import (
    TemplateManifest,
    TemplateSandboxRenderer,
    TemplateTest,
)
from app.schemas.video import Video
from app.services.templates import shapes, sprites
from app.services.templates.builders import (
    GeneratedLayerDrawer,
    GeneratedPartsBuilder,
    chosen_layers,
    encode_png,
    read_program,
    sandbox_request,
    spec_assets,
    style_spec,
)
from app.services.templates.outputs import (
    FRAME,
    BgmCodeAnswer,
    StyleCodeAnswer,
    TemplateCodeAnswer,
)
from app.services.templates.prompting import CodeAnswer, complete_json, failure_text

PartsFactory = Callable[[CatalogPort], PartsBuilder]
LayerFactory = Callable[[CatalogPort], LayerDrawer]
AnswerT = TypeVar("AnswerT", bound=BaseModel)

MAX_REPAIRS = 2
REPAIRABLE = frozenset(
    {
        "sandbox_crashed",
        "sandbox_denied",
        "sandbox_output_invalid",
        "sandbox_timeout",
        "sandbox_memory",
    }
)
NAME = re.compile(r"^[a-z0-9_]{1,40}$")
TEST_SCENE = Path(__file__).resolve().parent / "test_scene.json"
VISUAL_CLEAR_X1000 = 500
TEMPLATE_MS_PER_SCENE = 20000
STYLE_TOKENS = 16000
TEMPLATE_TOKENS = 12000
BGM_TOKENS = 8000
PACKAGE_VERSION = "1.0.0"
SKIN_MIN_SIDE = 7
FREE_SIZE_KINDS = frozenset({AssetKind.skin, AssetKind.icon})
LOOP_TOLERANCE_MS = 50


class BuiltinNotConnected(AppError):
    """A builtin renderer module has no implementation in the tables from bootstrap."""

    def __init__(self, kind: str, module: str) -> None:
        super().__init__(
            "internal", detail={"reason": "builtin_not_connected", "kind": kind, "module": module}
        )
        self.kind = kind
        self.module = module


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _seed(digest: str) -> int:
    return int(digest[:8], 16) & 0x7FFFFFFF


def _job_id(ctx: JobContext) -> str:
    """The job folder is named by the job id (ArtifactStore.job_dir)."""
    name = ctx.job_dir.name
    if not re.fullmatch(TYPEID_PATTERN, name):
        raise AppError("internal", detail={"reason": "job folder is not named by a job id"})
    return name


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _label(answer: StyleCodeAnswer | TemplateCodeAnswer | BgmCodeAnswer) -> LocalizedText:
    return LocalizedText(ko=answer.label.ko, en=answer.label.en)


class TemplatesService:
    def __init__(
        self,
        llm: LlmPort,
        sandbox: SandboxPort,
        catalog: CatalogPort,
        *,
        builtin_parts: Mapping[str, PartsFactory] | None = None,
        builtin_layers: Mapping[str, LayerFactory] | None = None,
    ) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self.catalog = catalog
        self.builtin_parts = dict(builtin_parts or {})
        self.builtin_layers = dict(builtin_layers or {})

    # Builders -----------------------------------------------------------------

    def _style(self, ref: PinnedRef) -> StyleManifest:
        manifest = self.catalog.get("art_style", ref.id, ref.revision)
        if not isinstance(manifest, StyleManifest):
            raise UnknownCatalogId(f"art_style:{ref.id}@{ref.revision}")
        return manifest

    def parts_builder(self, style: PinnedRef) -> PartsBuilder:
        renderer = self._style(style).renderer
        if renderer.kind == "sandbox":
            return GeneratedPartsBuilder(self.catalog, self.sandbox)
        factory = self.builtin_parts.get(renderer.module)
        if factory is None:
            raise BuiltinNotConnected("art_style", renderer.module)
        return factory(self.catalog)

    def layer_drawer(self, template: PinnedRef) -> LayerDrawer:
        manifest = self.catalog.get("template", template.id, template.revision)
        if not isinstance(manifest, TemplateManifest):
            raise UnknownCatalogId(f"template:{template.id}@{template.revision}")
        renderer = manifest.renderer
        if renderer.kind == "sandbox":
            return GeneratedLayerDrawer(self.catalog, self.sandbox)
        factory = self.builtin_layers.get(renderer.module)
        if factory is None:
            raise BuiltinNotConnected("template", renderer.module)
        return factory(self.catalog)

    # Shared code loop -----------------------------------------------------------

    def _write_and_run(
        self,
        *,
        task: LlmTask,
        model: type[AnswerT],
        data: dict[str, Any],
        max_output_tokens: int,
        run: Callable[[AnswerT], ValidatedOutput],
        ctx: JobContext,
        images: Sequence[bytes] = (),
    ) -> tuple[CodeAnswer[AnswerT], ValidatedOutput]:
        """Ask for code, run it, and send a failure back for at most two repairs.

        ``images`` are the same reference frames on every attempt; a repair keeps
        the data it was given and only adds the failure.
        """
        request = {**data, "previous_code": None, "failure": None}
        for attempt in range(MAX_REPAIRS + 1):
            answer = complete_json(
                self.llm,
                task=task,
                route=task.value,
                model=model,
                data=request,
                max_output_tokens=max_output_tokens,
                ctx=ctx,
                images=images,
            )
            try:
                with ctx.stage(Stage.sandbox):
                    return answer, run(answer.value)
            except AppError as error:
                if error.code not in REPAIRABLE or attempt == MAX_REPAIRS:
                    raise
                request = {
                    **data,
                    "previous_code": answer.value.code,  # type: ignore[attr-defined]
                    "failure": failure_text(error),
                }
        raise AssertionError("unreachable")

    def _register(self, kind: str, staged: Path, ctx: JobContext) -> PinnedRef:
        with ctx.stage(Stage.save):
            try:
                return self.catalog.register_generated(kind, staged)
            finally:
                shutil.rmtree(staged, ignore_errors=True)

    @staticmethod
    def _staging(ctx: JobContext, item_id: str) -> Path:
        staged = ctx.job_dir / "staging" / item_id
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True)
        return staged

    @staticmethod
    def _item_id(prefix: str, *parts: str) -> str:
        return f"{prefix}_{canonical_digest(list(parts))[:16]}"

    @staticmethod
    def _provenance(
        request_digest: str,
        parent: PinnedRef | None,
        reference_digest: str | None,
        job_id: str,
        usage: Usage,
    ) -> Provenance:
        return Provenance(
            request_digest=request_digest,
            parent=parent,
            reference_digest=reference_digest,
            job_id=job_id,
            provider=usage.provider,
            model=usage.model,
        )

    # Style ------------------------------------------------------------------------

    @staticmethod
    def _test_character(video: Video, manifest: StyleManifest) -> CharacterSpec:
        """The first part of every slot, replaced by the video's parts the base rig has.

        Filling every slot keeps the prop group in the comparison even when the
        video's character holds nothing.
        """
        allowed = manifest.rig.slots.model_dump()
        chosen = {slot: (ids[0] if ids else None) for slot, ids in allowed.items()}
        character = video.settings.visual.character
        if character is not None:
            for slot, value in character.slots.model_dump().items():
                if value is not None and value in allowed[slot]:
                    chosen[slot] = value
        return CharacterSpec(preset_id=None, slots=CharacterSlots.model_validate(chosen))

    @staticmethod
    def _background(video: Video, manifest: StyleManifest) -> str:
        theme_id = video.settings.visual.theme_id
        theme = next((item for item in manifest.themes if item.id == theme_id), manifest.themes[0])
        return theme.backgrounds[0]

    def _base_masks(
        self,
        base: PinnedRef,
        manifest: StyleManifest,
        character: CharacterSpec,
        background_id: str,
        ctx: JobContext,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Group masks of the base test character, and the groups the base cannot give."""
        rig = manifest.rig
        layers = self.parts_builder(base).build_parts(
            base,
            character.model_dump(mode="json"),
            rig.expressions[0],
            rig.poses[0],
            0,
            cancel=ctx.cancel,
        )
        masks: dict[str, Any] = shapes.group_masks(layers)
        root = self.catalog.package_dir("art_style", base)
        asset = next((item for item in manifest.assets if item.id == background_id), None)
        if asset is None:
            return masks, {"background": "base style has no background asset"}
        data = (root / asset.file).read_bytes()
        if _sha256(data) != asset.sha256:
            raise AppError("internal", detail={"reason": "asset digest mismatch"})
        if asset.file.endswith(".png"):
            masks["background"] = shapes.shape_mask(shapes.decode(data, background_id))
        else:
            try:
                masks["background"] = shapes.grid_mask(json.loads(data))
            except ValueError:
                masks["background"] = None
            if masks["background"] is None:
                return masks, {"background": "base background is not a readable grid"}
        return masks, {}

    def _style_run(
        self,
        answer: StyleCodeAnswer,
        spec: dict[str, Any],
        character: dict[str, Any],
        canvas: dict[str, int],
        seed: int,
        ctx: JobContext,
    ) -> ValidatedOutput:
        output = self.sandbox.run(
            sandbox_request(
                SandboxKind.style_parts,
                answer.code,
                {"spec": spec, "character": character, "canvas": canvas},
                seed,
            ),
            cancel=ctx.cancel,
        )
        assets = spec_assets(spec)
        missing = sorted(set(assets) - set(output.files))
        extra = sorted(set(output.files) - set(assets))
        if missing or extra:
            reason = f"missing {missing[:5]}" if missing else f"unexpected {extra[:5]}"
            raise AppError("sandbox_output_invalid", detail={"reason": f"assets {reason}"})
        size = (canvas["width"], canvas["height"])
        for name, data in output.files.items():
            image = shapes.decode(data, name)
            if assets[name][0] in FREE_SIZE_KINDS:
                if assets[name][0] is AssetKind.skin and min(image.size) < SKIN_MIN_SIDE:
                    raise AppError(
                        "sandbox_output_invalid",
                        detail={"reason": f"skin {name} needs at least {SKIN_MIN_SIDE} cells"},
                    )
            elif image.size != size:
                raise AppError(
                    "sandbox_output_invalid",
                    detail={"reason": f"{name} must be {size[0]}x{size[1]}"},
                )
        return output

    def generate_style(
        self,
        req: StyleRequest,
        video: Video,
        hints: StyleFrames | None,
        *,
        ctx: JobContext,
    ) -> PinnedRef:
        """A new style (no ``base_style``) or a modification that extends ``base_style``."""
        modification = req.base_style is not None
        base = req.base_style or video.settings.visual.art_style
        manifest = self._style(base)
        job_id = _job_id(ctx)
        request_digest = canonical_digest(req.model_dump(mode="json"))
        seed = _seed(request_digest)
        reference = hints if req.use_reference and hints else None
        images = list(reference.frames) if reference is not None else []
        reference_hints = (
            {"palette": list(reference.palette)} if reference is not None else None
        )
        reference_digest = (
            _sha256(
                json.dumps(
                    {
                        "palette": reference.palette,
                        "frames": [_sha256(frame) for frame in images],
                    },
                    sort_keys=True,
                ).encode("utf-8")
            )
            if reference is not None
            else None
        )
        spec = style_spec(manifest)
        assets = spec_assets(spec)
        if len(assets) > 64 or not all(NAME.match(asset_id) for asset_id in assets):
            raise AppError("internal", detail={"reason": "base style assets do not fit the runner"})
        character = self._test_character(video, manifest)
        expression, pose = manifest.rig.expressions[0], manifest.rig.poses[0]
        background_id = self._background(video, manifest)
        base_masks, skipped = self._base_masks(base, manifest, character, background_id, ctx)
        canvas = {"width": manifest.canvas.width, "height": manifest.canvas.height}
        character_data = {
            "slots": character.slots.model_dump(mode="json"),
            "expression": expression,
            "pose": pose,
        }
        parent_program = None
        if modification and manifest.renderer.kind == "sandbox":
            root = self.catalog.package_dir("art_style", base)
            renderer = manifest.renderer
            parent_program = read_program(root, renderer.program, renderer.program_digest)
        data = {
            "mode": "modify" if modification else "new",
            "instruction": req.instruction,
            "base_style": {"id": base.id, "label": manifest.label.model_dump(), "canvas": canvas},
            "spec": spec,
            "test_character": character_data,
            "parent_program": parent_program,
            "reference_hints": reference_hints,
        }
        answer, output = self._write_and_run(
            task=LlmTask.style_code,
            model=StyleCodeAnswer,
            data=data,
            max_output_tokens=STYLE_TOKENS,
            run=lambda value: self._style_run(value, spec, character_data, canvas, seed, ctx),
            ctx=ctx,
            images=images,
        )
        with ctx.stage(Stage.validate):
            # The stored grids are what later videos draw, so the checks use them.
            grids = {
                asset_id: sprites.encode(shapes.decode(data, asset_id), asset_id)
                for asset_id, data in output.files.items()
            }
            layers = chosen_layers(manifest, character, expression, pose)
            candidate_layers = {
                name: encode_png(sprites.rasterize(grids[asset_id]))
                for name, asset_id in layers.items()
            }
            candidate: dict[str, Any] = shapes.group_masks(candidate_layers)
            candidate["background"] = shapes.shape_mask(sprites.rasterize(grids[background_id]))
            report = shapes.compare(
                base_masks, candidate, modification=modification, skipped=skipped
            )
            if not report.passed:
                raise AppError("sandbox_output_invalid", detail=report.error_detail())
        code = answer.value.code.encode("utf-8")
        item_id = self._item_id("style", job_id, request_digest, _sha256(code))
        staged = self._staging(ctx, item_id)
        try:
            (staged / "program.py").write_bytes(code)
            (staged / "sprites").mkdir()
            style_assets = []
            for asset_id, (kind, slot) in assets.items():
                grid = grids[asset_id]
                (staged / "sprites" / f"{asset_id}.json").write_bytes(grid)
                style_assets.append(
                    StyleAsset(
                        id=asset_id,
                        kind=kind,
                        slot=slot,
                        file=f"sprites/{asset_id}.json",
                        sha256=_sha256(grid),
                        license_id=next(iter(manifest.licenses), "generated"),
                    )
                )
            for license in manifest.licenses.values():
                source = self.catalog.package_dir("art_style", base) / license.license_file
                target = staged / license.license_file
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            _write_json(staged / "checks.json", {"seed": seed, "shape": report.as_json()})
            package = manifest.model_copy(
                update={
                    "id": item_id,
                    "version": PACKAGE_VERSION,
                    "label": _label(answer.value),
                    "origin": PackageOrigin.generated,
                    "status": PackageStatus.ready,
                    "extends": base if modification else None,
                    "renderer": SandboxRenderer(
                        kind="sandbox",
                        program="program.py",
                        program_digest=_sha256(code),
                        runtime_digest=self.sandbox.runtime_digest(),
                        entry="build_assets",
                    ),
                    "assets": style_assets,
                    "provenance": self._provenance(
                        request_digest, base, reference_digest, job_id, answer.usage
                    ),
                    "preview": None,
                }
            )
            checked = StyleManifest.model_validate(package.model_dump(mode="json"))
            _write_json(staged / "manifest.json", checked.model_dump(mode="json"))
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        return self._register("art_style", staged, ctx)

    # Template ---------------------------------------------------------------------

    def _template_run(
        self, answer: TemplateCodeAnswer, scene: Scene, ctx: JobContext
    ) -> ValidatedOutput:
        output = self.sandbox.run(
            sandbox_request(
                SandboxKind.template_layer,
                answer.code,
                {
                    "scene": scene.model_dump(mode="json"),
                    "regions": answer.regions.model_dump(mode="json"),
                    "canvas": {"width": FRAME[0], "height": FRAME[1]},
                },
                0,
            ),
            cancel=ctx.cancel,
        )
        layer = shapes.decode(output.files["layer"], "layer")
        if layer.size != FRAME:
            raise AppError("sandbox_output_invalid", detail={"reason": "layer must be 1080x1920"})
        visual = answer.regions.visual
        area = layer.getchannel("A").crop(
            (visual.x, visual.y, visual.x + visual.w, visual.y + visual.h)
        )
        clear = area.histogram()[0] * 1000 // (visual.w * visual.h)
        if clear < VISUAL_CLEAR_X1000:
            raise AppError(
                "sandbox_output_invalid",
                detail={
                    "reason": "layer covers the visual region",
                    "visual_clear_x1000": clear,
                    "threshold_x1000": VISUAL_CLEAR_X1000,
                },
            )
        return output

    def generate_template(
        self, req: TemplateRequest, video: Video, *, ctx: JobContext
    ) -> PinnedRef:
        job_id = _job_id(ctx)
        request_digest = canonical_digest(req.model_dump(mode="json"))
        layout = video.settings.format.layout
        current = self.catalog.get("template", layout.id, layout.revision)
        if not isinstance(current, TemplateManifest):
            raise UnknownCatalogId(f"template:{layout.id}@{layout.revision}")
        scene_text = TEST_SCENE.read_bytes()
        scene = Scene.model_validate_json(scene_text)
        data = {
            "instruction": req.instruction,
            "current_template": {
                "regions": current.regions.model_dump(mode="json"),
                "character_anchors": current.character_anchors.model_dump(mode="json"),
                "caption_modes": [mode.value for mode in current.caption_modes],
                "dialog_box": current.dialog_box,
                "safe_area": safe_area().model_dump(mode="json"),
            },
            "test_scene": scene.model_dump(mode="json"),
        }
        answer, output = self._write_and_run(
            task=LlmTask.template_code,
            model=TemplateCodeAnswer,
            data=data,
            max_output_tokens=TEMPLATE_TOKENS,
            run=lambda value: self._template_run(value, scene, ctx),
            ctx=ctx,
        )
        value = answer.value
        code = value.code.encode("utf-8")
        item_id = self._item_id("template", job_id, request_digest, _sha256(code))
        staged = self._staging(ctx, item_id)
        try:
            (staged / "program.py").write_bytes(code)
            (staged / "test_scene.json").write_bytes(scene_text)
            manifest = TemplateManifest(
                schema_version=1,
                api_version=1,
                id=item_id,
                version=PACKAGE_VERSION,
                label=_label(value),
                origin="generated",
                status="ready",
                renderer=TemplateSandboxRenderer(
                    kind="sandbox",
                    program="program.py",
                    program_digest=_sha256(code),
                    runtime_digest=self.sandbox.runtime_digest(),
                    entry="render_layer",
                    max_ms_per_scene=TEMPLATE_MS_PER_SCENE,
                ),
                regions=value.regions,
                character_anchors=value.character_anchors,
                caption_modes=value.caption_modes,
                dialog_box=value.dialog_box,
                test=TemplateTest(
                    scene="test_scene.json", layer_digest=_sha256(output.files["layer"])
                ),
                provenance=self._provenance(request_digest, None, None, job_id, answer.usage),
            )
            _write_json(staged / "manifest.json", manifest.model_dump(mode="json"))
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        return self._register("template", staged, ctx)

    # BGM --------------------------------------------------------------------------

    def _bgm_run(
        self, answer: BgmCodeAnswer, mood: str, seed: int, ctx: JobContext
    ) -> ValidatedOutput:
        output = self.sandbox.run(
            sandbox_request(
                SandboxKind.bgm_loop,
                answer.code,
                {"params": {"bpm": answer.bpm, "bars": answer.bars, "mood": mood}},
                seed,
            ),
            cancel=ctx.cancel,
        )
        measured = output.meta.get("files", {}).get("loop", {})
        if measured.get("sample_peak_dbfs_x10") is None:
            raise AppError("sandbox_output_invalid", detail={"reason": "loop is silent"})
        duration = measured.get("duration_ms")
        if not isinstance(duration, int) or abs(duration - answer.loop_ms) > LOOP_TOLERANCE_MS:
            raise AppError(
                "sandbox_output_invalid",
                detail={
                    "reason": "loop length does not match bpm and bars",
                    "duration_ms": duration,
                    "expected_ms": answer.loop_ms,
                },
            )
        return output

    def generate_bgm(self, req: BgmCodeRequest, *, ctx: JobContext) -> PinnedRef:
        job_id = _job_id(ctx)
        request_digest = canonical_digest(req.model_dump(mode="json"))
        seed = req.seed if req.seed is not None else _seed(request_digest)
        data = {
            "mood": req.mood.value,
            "instruction": req.instruction,
            "limits": {
                "max_loop_ms": 16000,
                "sample_rate": 44100,
                "channels": 1,
                "sample_bits": 16,
                "beats_per_bar": 4,
            },
        }
        answer, output = self._write_and_run(
            task=LlmTask.bgm_code,
            model=BgmCodeAnswer,
            data=data,
            max_output_tokens=BGM_TOKENS,
            run=lambda value: self._bgm_run(value, req.mood.value, seed, ctx),
            ctx=ctx,
        )
        value = answer.value
        code = value.code.encode("utf-8")
        loop = output.files["loop"]
        measured = output.meta["files"]["loop"]
        item_id = self._item_id("bgm", job_id, request_digest, _sha256(code))
        staged = self._staging(ctx, item_id)
        try:
            (staged / "program.py").write_bytes(code)
            (staged / "loop.wav").write_bytes(loop)
            entry = CodeBgm(
                schema_version=1,
                id=item_id,
                label=_label(value),
                mood=req.mood,
                file="loop.wav",
                sha256=_sha256(loop),
                duration_ms=measured["duration_ms"],
                sample_rate=44100,
                channels=1,
                loudness_lufs_x10=measured["loudness_lufs_x10"],
                true_peak_dbtp_x10=min(0, measured["sample_peak_dbfs_x10"]),
                source="code",
                program="program.py",
                program_digest=_sha256(code),
                runtime_digest=self.sandbox.runtime_digest(),
                seed=seed,
                params=BgmParams(bpm=value.bpm, bars=value.bars, mood=req.mood),
                provenance=self._provenance(request_digest, None, None, job_id, answer.usage),
            )
            _write_json(staged / "manifest.json", entry.model_dump(mode="json"))
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        return self._register("bgm", staged, ctx)


def create(
    settings: AppSettings,
    deps: ServiceDeps,
    *,
    builtin_parts: Mapping[str, PartsFactory] | None = None,
    builtin_layers: Mapping[str, LayerFactory] | None = None,
) -> TemplatesService:
    """Builtin tables map a manifest ``renderer.module`` to its implementation.

    The builtin implementations live in another service, so the bootstrap passes
    them in; without them a builtin package fails as not connected.
    """
    return TemplatesService(
        deps.llm,
        deps.sandbox,
        deps.catalog,
        builtin_parts=builtin_parts,
        builtin_layers=builtin_layers,
    )


__all__ = ["BuiltinNotConnected", "TemplatesService", "create"]
