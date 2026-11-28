"""Generated style, caption box, template and code BGM packages.

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
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.caption_layout import PLATE_SIDE_PAD, clamp_place, place_area, safe_area
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
from app.schemas.caption_style_manifest import (
    CaptionSandboxRenderer,
    CaptionStyleManifest,
    CaptionTest,
    CaptionTestPlate,
)
from app.schemas.common import (
    TYPEID_PATTERN,
    CharacterRole,
    LocalizedText,
    PackageOrigin,
    PackageStatus,
    PinnedRef,
    Provenance,
)
from app.schemas.job import Stage, Usage, WaitingOn
from app.schemas.sandbox_io import SandboxKind
from app.schemas.scene import Scene
from app.schemas.settings import CaptionPlace, CharacterSlots, CharacterSpec
from app.schemas.style_manifest import AssetKind, SandboxRenderer, StyleAsset, StyleManifest
from app.schemas.template_manifest import (
    TemplateManifest,
    TemplateSandboxRenderer,
    TemplateTest,
)
from app.schemas.video import CaptionBoxDescription, Video
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
    CaptionBoxCodeAnswer,
    CaptionPlaceAnswer,
    StyleCodeAnswer,
    TemplateCodeAnswer,
)
from app.services.templates.prompting import (
    CodeAnswer,
    complete_json,
    failure_text,
    load_prompt_note,
)

PartsFactory = Callable[[CatalogPort], PartsBuilder]
LayerFactory = Callable[[CatalogPort], LayerDrawer]
AnswerT = TypeVar("AnswerT", bound=BaseModel)

MAX_REPAIRS = 2
STYLE_ROUNDS = 3
STYLE_FINALIZE_RESERVE_S = 120
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
CAPTION_BOX_TOKENS = 6000
CAPTION_PLACE_TOKENS = 350
CAPTION_BOX_MS = 5000
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


def _label(
    answer: StyleCodeAnswer | TemplateCodeAnswer | BgmCodeAnswer | CaptionBoxCodeAnswer,
) -> LocalizedText:
    return LocalizedText(ko=answer.label.ko, en=answer.label.en)


def _box_rect(raw: Any, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, list) or len(raw) != 4 or any(type(n) is not int for n in raw):
        return None
    x, y, w, h = raw
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        return None
    return x, y, x + w, y + h


class _DeadlineContext:
    """The same job context with an earlier deadline, for a later style round."""

    def __init__(self, ctx: JobContext, deadline: float) -> None:
        self._ctx = ctx
        self._deadline = deadline

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)

    @property
    def deadline(self) -> float:
        return self._deadline


class _CandidateCatalog:
    """The real catalog with one round's style swapped in for composing its frame."""

    def __init__(
        self, catalog: CatalogPort, ref: PinnedRef, root: Path, manifest: StyleManifest
    ) -> None:
        self._catalog = catalog
        self._ref = ref
        self._root = root
        self._manifest = manifest

    def list(self, kind: str, *, video: Video | None = None) -> list[Any]:
        return self._catalog.list(kind, video=video)

    def get(self, kind: str, item_id: str, revision: str | None = None) -> Any:
        if kind == "art_style" and item_id == self._ref.id:
            return self._manifest
        return self._catalog.get(kind, item_id, revision)

    def pin(self, kind: str, item_id: str) -> PinnedRef:
        return self._catalog.pin(kind, item_id)

    def package_dir(self, kind: str, ref: PinnedRef) -> Path:
        if kind == "art_style" and ref.id == self._ref.id:
            return self._root
        return self._catalog.package_dir(kind, ref)

    def register_generated(self, kind: str, staged_dir: Path) -> PinnedRef:
        return self._catalog.register_generated(kind, staged_dir)


class TemplatesService:
    def __init__(
        self,
        llm: LlmPort,
        sandbox: SandboxPort,
        catalog: CatalogPort,
        *,
        render_factory: Callable[[CatalogPort], Any] | None = None,
        builtin_parts: Mapping[str, PartsFactory] | None = None,
        builtin_layers: Mapping[str, LayerFactory] | None = None,
    ) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self.catalog = catalog
        self.render_factory = render_factory
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
        prompt_suffix: str = "",
        previous_code: str | None = None,
    ) -> tuple[CodeAnswer[AnswerT], ValidatedOutput]:
        """Ask for code, run it, and send a failure back for at most two repairs.

        ``images`` are the same on every attempt; a repair keeps the data it was
        given and only adds the failed code and its failure.
        """
        request = {**data, "previous_code": previous_code, "failure": None}
        bounded = task is LlmTask.caption_box_code
        for attempt in range(MAX_REPAIRS + 1):
            try:
                answer = complete_json(
                    self.llm,
                    task=task,
                    route=task.value,
                    model=model,
                    data=request,
                    max_output_tokens=max_output_tokens,
                    ctx=ctx,
                    images=images,
                    system_suffix=prompt_suffix,
                    repairs=0 if bounded else 1,
                    provider_repairs=not bounded,
                )
            except AppError as error:
                if not bounded or error.code != "llm_invalid_output" or attempt == MAX_REPAIRS:
                    raise
                request["failure"] = failure_text(error)
                continue
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
                # A cancelled job must not publish a package it will report as cancelled.
                ctx.cancel.raise_if_set()
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

    def _checked_style(
        self,
        output: ValidatedOutput,
        manifest: StyleManifest,
        character: CharacterSpec,
        expression: str,
        pose: str,
        background_id: str,
        base_masks: dict[str, Any],
        *,
        modification: bool,
        skipped: Mapping[str, str],
    ) -> tuple[dict[str, bytes], shapes.ShapeReport, dict[str, bytes]]:
        """Store every asset as a grid and compare the drawn test character."""
        # The stored grids are what later videos draw, so the checks use them.
        grids = {
            asset_id: sprites.encode(shapes.decode(data, asset_id), asset_id)
            for asset_id, data in output.files.items()
        }
        part_layers = {
            name: encode_png(sprites.rasterize(grids[asset_id]))
            for name, asset_id in chosen_layers(
                manifest, character, expression, pose
            ).items()
        }
        candidate: dict[str, Any] = shapes.group_masks(part_layers)
        candidate["background"] = shapes.shape_mask(sprites.rasterize(grids[background_id]))
        report = shapes.compare(
            base_masks, candidate, modification=modification, skipped=skipped
        )
        if not report.passed:
            raise AppError("sandbox_output_invalid", detail=report.error_detail())
        return grids, report, part_layers

    def _style_package(
        self,
        staged: Path,
        *,
        item_id: str,
        answer: CodeAnswer[StyleCodeAnswer],
        manifest: StyleManifest,
        base: PinnedRef,
        assets: Mapping[str, tuple[AssetKind, str | None]],
        grids: Mapping[str, bytes],
        report: shapes.ShapeReport,
        seed: int,
        request_digest: str,
        reference_digest: str | None,
        job_id: str,
        modification: bool,
    ) -> StyleManifest:
        """Write one round's package and return its checked manifest."""
        code = answer.value.code.encode("utf-8")
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
        return checked

    def _compose_style_frame(
        self,
        video: Video,
        character: CharacterSpec,
        part_layers: dict[str, bytes],
        grids: dict[str, bytes],
        candidate: StyleManifest,
        staged: Path,
        ctx: JobContext,
    ) -> bytes:
        """The test scene drawn with one round's style, for the next round to see.

        The test video keeps only the candidate style and the video's layout. It
        drops the user's script, reference, extra caption layer and character
        role, so a title or a setting the test scene cannot draw never reaches
        the model or stops the rounds. The font and caption mode fall back to
        ones the candidate style and layout can draw.
        """
        if self.render_factory is None:
            raise AppError("internal", detail={"reason": "style self-view has no renderer"})
        if not candidate.fonts:
            raise AppError("internal", detail={"reason": "style has no font"})
        scene = Scene.model_validate_json(TEST_SCENE.read_bytes())
        theme_id = video.settings.visual.theme_id
        theme = next(
            (item for item in candidate.themes if item.id == theme_id), candidate.themes[0]
        )
        filler = dict(part_layers)
        filler["skin"] = encode_png(sprites.rasterize(grids[theme.skin_id], cell=1))
        layout = video.settings.format.layout
        template = self.catalog.get("template", layout.id, layout.revision)
        if not isinstance(template, TemplateManifest):
            raise AppError("unknown_catalog_id", detail={"kind": "template", "id": layout.id})
        layer, _ = self.layer_drawer(layout).draw_layer(
            layout, scene, FRAME, filler, 0, cancel=ctx.cancel
        )
        ref = PinnedRef(id=candidate.id, revision="0" * 64)
        still = video.model_copy(deep=True)
        still.script = None
        still.reference = None
        still.settings.visual.art_style = ref
        still.settings.visual.theme_id = theme.id
        still.settings.visual.character = character
        still.settings.caption.extra = []
        if still.settings.caption.font_id.id not in candidate.fonts:
            still.settings.caption.font_id = self.catalog.pin("font", candidate.fonts[0])
        if still.settings.caption.mode not in template.caption_modes:
            still.settings.caption.mode = template.caption_modes[0]
        if still.settings.format.character_role is CharacterRole.none:
            still.settings.format.character_role = CharacterRole.presenter
        still.scene_order = [scene.id]
        still.scenes = {scene.id: scene}
        render = self.render_factory(
            _CandidateCatalog(self.catalog, ref, staged, candidate)
        )
        frame, _ = render.compose(still, scene.id, filler, layer)
        return encode_png(frame)

    def generate_style(
        self,
        req: StyleRequest,
        video: Video,
        hints: StyleFrames | None,
        *,
        ctx: JobContext,
    ) -> PinnedRef:
        """A new style (no ``base_style``) or a modification that extends ``base_style``.

        Up to ``STYLE_ROUNDS`` rounds: each later round sees the previous round's
        composed frame and code. Only the last accepted round is registered, so a
        failure after round 1 returns that round instead of failing the job.
        """
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
        selfview_note = load_prompt_note("style_code", "selfview")
        last_staged: Path | None = None
        previous_code: str | None = None
        previous_frame: bytes | None = None
        for number in range(1, STYLE_ROUNDS + 1):
            ctx.progress(done=number - 1, total=STYLE_ROUNDS, waiting_on=WaitingOn.llm)
            round_ctx: JobContext = ctx
            if number > 1:
                cutoff = ctx.deadline - STYLE_FINALIZE_RESERVE_S
                if time.monotonic() >= cutoff:
                    break
                round_ctx = _DeadlineContext(ctx, cutoff)
            round_data = {**data, "frame_code": previous_code} if number > 1 else data
            round_images = [*images, *([previous_frame] if previous_frame is not None else [])]
            try:
                answer, output = self._write_and_run(
                    task=LlmTask.style_code,
                    model=StyleCodeAnswer,
                    data=round_data,
                    max_output_tokens=STYLE_TOKENS,
                    run=lambda value: self._style_run(
                        value, spec, character_data, canvas, seed, round_ctx
                    ),
                    ctx=round_ctx,
                    images=round_images,
                    prompt_suffix=selfview_note if number > 1 else "",
                )
                with ctx.stage(Stage.validate):
                    grids, report, part_layers = self._checked_style(
                        output,
                        manifest,
                        character,
                        expression,
                        pose,
                        background_id,
                        base_masks,
                        modification=modification,
                        skipped=skipped,
                    )
            except AppError:
                if last_staged is None:
                    raise
                break
            code = answer.value.code.encode("utf-8")
            item_id = self._item_id(
                "style", job_id, request_digest, _sha256(code), f"r{number}"
            )
            staged = self._staging(ctx, item_id)
            try:
                candidate = self._style_package(
                    staged,
                    item_id=item_id,
                    answer=answer,
                    manifest=manifest,
                    base=base,
                    assets=assets,
                    grids=grids,
                    report=report,
                    seed=seed,
                    request_digest=request_digest,
                    reference_digest=reference_digest,
                    job_id=job_id,
                    modification=modification,
                )
            except Exception:
                # A later package that cannot be written leaves the finished one to register.
                shutil.rmtree(staged, ignore_errors=True)
                if last_staged is None:
                    raise
                break
            except BaseException:
                shutil.rmtree(staged, ignore_errors=True)
                if last_staged is not None:
                    shutil.rmtree(last_staged, ignore_errors=True)
                raise
            try:
                with ctx.stage(Stage.validate):
                    frame = self._compose_style_frame(
                        video, character, part_layers, grids, candidate, staged, ctx
                    )
            except AppError:
                if last_staged is None:
                    # Round 1 stands as before; without a frame the later rounds cannot run.
                    last_staged = staged
                    ctx.progress(done=number, total=STYLE_ROUNDS)
                    break
                shutil.rmtree(staged, ignore_errors=True)
                break
            if last_staged is not None:
                shutil.rmtree(last_staged, ignore_errors=True)
            last_staged = staged
            previous_code = answer.value.code
            previous_frame = frame
            ctx.progress(done=number, total=STYLE_ROUNDS)
            # Only the staged path, code and frame carry to the next round; the rest is on disk.
            del answer, output, grids, report, part_layers, candidate
        assert last_staged is not None
        return self._register("art_style", last_staged, ctx)

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

    # Captions ---------------------------------------------------------------------

    def edit_caption_place(
        self, instruction: str, video: Video, *, ctx: JobContext
    ) -> tuple[CaptionPlace, bool]:
        caption = video.settings.caption
        current = (
            caption.place.model_dump(mode="json")
            if caption.place is not None
            else {"position": caption.position.value, "band": safe_area().model_dump(mode="json")}
        )
        line = (
            video.scenes[video.scene_order[0]].lines[0].display_text if video.scene_order else None
        )
        answer = complete_json(
            self.llm,
            task=LlmTask.caption_place,
            route="caption_place",
            model=CaptionPlaceAnswer,
            data={
                "instruction": instruction,
                "current_place": current,
                "safe_area": place_area().model_dump(mode="json"),
                "transcript_line": line,
            },
            max_output_tokens=CAPTION_PLACE_TOKENS,
            ctx=ctx,
            repairs=MAX_REPAIRS,
            provider_repairs=False,
            stage=Stage.llm_chat,
        ).value
        raw, moved = clamp_place({**answer.place.model_dump(), "align": answer.align})
        return CaptionPlace.model_validate(raw), moved

    def _caption_box_run(
        self,
        answer: CaptionBoxCodeAnswer,
        tests: Sequence[dict[str, Any]],
        ctx: JobContext,
    ) -> ValidatedOutput:
        outputs = []
        for sample in tests:
            w, h = sample["plate"]["w"], sample["plate"]["h"]
            output = self.sandbox.run(
                sandbox_request(
                    SandboxKind.caption_box,
                    answer.code,
                    {**sample, "canvas": {"width": w, "height": h}},
                    0,
                ),
                cancel=ctx.cancel,
            )
            layer = shapes.decode(output.files["box"], "box")
            if layer.size != (w, h):
                raise AppError("sandbox_output_invalid", detail={"reason": "wrong box image size"})
            spec = sample["spec"]
            program = output.meta.get("program", {})
            text = _box_rect(program.get("text_area"), w, h)
            if (
                text is None
                or text[2] - text[0] < max(line["w"] for line in spec["lines"])
                or text[3] - text[1] < sum(line["h"] for line in spec["lines"])
            ):
                raise AppError(
                    "sandbox_output_invalid", detail={"reason": "text_area does not fit the lines"}
                )
            pixels = layer.getchannel("A").getbbox()
            box = _box_rect(program.get("box"), w, h)
            if pixels is None and program.get("box") == [0, 0, 0, 0]:
                outputs.append(output)
                continue
            if box is None or (pixels is not None and not (
                box[0] <= pixels[0] and box[1] <= pixels[1]
                and box[2] >= pixels[2] and box[3] >= pixels[3]
            )):
                raise AppError(
                    "sandbox_output_invalid", detail={"reason": "box does not contain the layer"}
                )
            outputs.append(output)
        return outputs[0]

    def generate_caption_box(
        self,
        instruction: str,
        video: Video,
        *,
        ctx: JobContext,
        reference_box: CaptionBoxDescription | None = None,
        art_style: PinnedRef | None = None,
    ) -> PinnedRef:
        """Test one new package, using the current program as the parent of a word edit."""
        caption = video.settings.caption
        previous_code = None
        if reference_box is None:
            base = caption.style or self.catalog.pin("caption_style", "plate")
            manifest = self.catalog.get("caption_style", base.id, base.revision)
            if not isinstance(manifest, CaptionStyleManifest):
                raise UnknownCatalogId(f"caption_style:{base.id}@{base.revision}")
            renderer = manifest.renderer
            previous_code = read_program(
                self.catalog.package_dir("caption_style", base),
                renderer.program,
                renderer.program_digest,
            )
        visual = video.settings.visual
        manifest_style = self._style(art_style or visual.art_style)
        theme = next(
            (item for item in manifest_style.themes if item.id == visual.theme_id),
            manifest_style.themes[0],
        )
        palette = theme.palette
        width = caption.place.w if caption.place is not None else 640
        align = caption.place.align if caption.place is not None else "center"
        samples = []
        for w, count in ((width, 1), (min(width, 360), 2)):
            line_height = 60
            samples.append({
                "plate": {"w": w, "h": line_height * count + 8},
                "spec": {
                    "size_px": 48,
                    "line_height": line_height,
                    "text_color": palette.caption_text,
                    "box_color": palette.caption_box,
                    "align": align,
                    "lines": [
                        {"w": min(360, w - 2 * PLATE_SIDE_PAD), "h": line_height}
                        for _ in range(count)
                    ],
                },
            })
        answer, output = self._write_and_run(
            task=LlmTask.caption_box_code,
            model=CaptionBoxCodeAnswer,
            data={
                "instruction": instruction,
                "reference_box": None if reference_box is None else reference_box.model_dump(),
                "palette": palette.model_dump(mode="json"),
                "plate": samples[0]["plate"],
                "safe_area": place_area().model_dump(mode="json"),
                "test_plates": samples,
            },
            max_output_tokens=CAPTION_BOX_TOKENS,
            run=lambda value: self._caption_box_run(value, samples, ctx),
            ctx=ctx,
            previous_code=previous_code,
        )
        code = answer.value.code.encode("utf-8")
        program_digest = _sha256(code)
        item_id = self._item_id("caption_box", _job_id(ctx), program_digest)
        staged = self._staging(ctx, item_id)
        try:
            (staged / "program.py").write_bytes(code)
            package = CaptionStyleManifest(
                schema_version=1,
                api_version=1,
                id=item_id,
                version=PACKAGE_VERSION,
                label=_label(answer.value),
                origin="generated",
                status="ready",
                renderer=CaptionSandboxRenderer(
                    kind="sandbox",
                    program="program.py",
                    program_digest=program_digest,
                    runtime_digest=self.sandbox.runtime_digest(),
                    entry="draw_caption_box",
                    max_ms_per_box=CAPTION_BOX_MS,
                ),
                test=CaptionTest(
                    plate=CaptionTestPlate.model_validate(samples[0]["plate"]),
                    layer_digest=_sha256(output.files["box"]),
                ),
            )
            _write_json(staged / "manifest.json", package.model_dump(mode="json"))
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        return self._register("caption_style", staged, ctx)

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
    render_factory: Callable[[CatalogPort], Any] | None = None,
    builtin_parts: Mapping[str, PartsFactory] | None = None,
    builtin_layers: Mapping[str, LayerFactory] | None = None,
) -> TemplatesService:
    """Builtin tables map a manifest ``renderer.module`` to its implementation.

    The builtin implementations live in another service, so the bootstrap passes
    them in; without them a builtin package fails as not connected. The render
    factory comes from the bootstrap for the same reason: this service may not
    import the render service to compose a self-view frame.
    """
    return TemplatesService(
        deps.llm,
        deps.sandbox,
        deps.catalog,
        render_factory=render_factory,
        builtin_parts=builtin_parts,
        builtin_layers=builtin_layers,
    )


__all__ = ["BuiltinNotConnected", "TemplatesService", "create"]
