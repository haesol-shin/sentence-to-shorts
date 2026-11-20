"""Export JSON Schema documents and the OpenAPI document from the Pydantic source.

Run from the repository root or from core/ after `poetry install`:

    poetry run python ../scripts/export_schemas.py

The generated files are committed. CI fails when regeneration changes them.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CORE = Path(__file__).resolve().parent.parent / "core"
sys.path.insert(0, str(CORE))

from pydantic import BaseModel, TypeAdapter  # noqa: E402

from app.schemas import (  # noqa: E402
    api,
    artifact,
    bgm_entry,
    change,
    common,
    font_manifest,
    format_card,
    job,
    preset,
    project,
    sandbox_io,
    scene,
    script,
    settings,
    style_manifest,
    template_manifest,
    video,
    voice_manifest,
)

SCHEMA_BASE = "https://app.invalid/schemas"
REF_TEMPLATE = "#/$defs/{model}"


class CommonDefs(BaseModel):
    """Carrier so that scalar aliases and enums appear as named definitions."""

    EntityId: common.EntityId
    CatalogId: common.CatalogId
    Digest: common.Digest
    Timestamp: common.Timestamp
    RelPath: common.RelPath
    HexColor: common.HexColor
    OwnerId: common.OwnerId
    Language: common.Language
    Origin: common.Origin
    Mood: common.Mood
    CaptionMode: common.CaptionMode
    CharacterRole: common.CharacterRole
    PackageStatus: common.PackageStatus
    PackageOrigin: common.PackageOrigin


@dataclass(frozen=True)
class Document:
    filename: str
    title: str
    description: str | None = None
    root: type[BaseModel] | None = None
    models: tuple[type[BaseModel], ...] = ()
    adapter: TypeAdapter[Any] | None = None
    drop: tuple[str, ...] = ()


DOCUMENTS = [
    Document(
        filename="common",
        title="Common definitions",
        root=None,
        models=(
            CommonDefs,
            common.PinnedRef,
            common.LocalizedText,
            common.ArtifactRef,
            common.Box,
            common.Point,
            common.License,
            common.Provenance,
        ),
        drop=("CommonDefs",),
    ),
    Document(
        filename="settings",
        title="Production settings",
        description=(
            "Typed settings shared by project defaults, video snapshots and presets. "
            "Cards, picker and chat all edit this one object."
        ),
        root=settings.Settings,
        models=(settings.PresetSettings,),
    ),
    Document(
        filename="project",
        title="Project",
        description="A project groups videos made with the same settings.",
        root=project.Project,
    ),
    Document(
        filename="video",
        title="Video revision",
        description="Immutable snapshot of one video at one revision.",
        root=video.Video,
        models=(video.ReferenceSummary, video.ArtifactStatus, video.VideoBuild),
    ),
    Document(
        filename="script",
        title="Script",
        description="Script metadata of a video. The spoken lines live in scenes.",
        root=script.Script,
        models=(script.Line,),
    ),
    Document(
        filename="scene",
        title="Scene",
        description="Source data of one scene.",
        root=scene.Scene,
    ),
    Document(
        filename="change",
        title="Change plan",
        description="Every edit becomes a plan against a base revision.",
        root=change.ChangePlan,
    ),
    Document(
        filename="preset",
        title="Preset",
        description="Saved format. Created only by an explicit user action.",
        root=preset.Preset,
    ),
    Document(
        filename="format-card",
        title="Format card",
        description="Data file core/app/catalog/format_cards/<id>.json.",
        root=format_card.FormatCard,
        models=(format_card.StoryStructure,),
    ),
    Document(
        filename="style-manifest",
        title="Style package manifest",
        description="manifest.json of an art style package.",
        root=style_manifest.StyleManifest,
    ),
    Document(
        filename="template-manifest",
        title="Template manifest",
        description="A template is a layout that returns one RGBA layer per scene.",
        root=template_manifest.TemplateManifest,
    ),
    Document(
        filename="voice-manifest",
        title="Voice manifest",
        description="core/app/plugins/voices/<id>/manifest.json.",
        root=voice_manifest.VoiceManifest,
    ),
    Document(
        filename="bgm-entry",
        title="BGM entry",
        description="One BGM source: builtin, uploaded or generated loop.",
        models=(bgm_entry.SfxEntry, bgm_entry.TypingSoundEntry),
        adapter=TypeAdapter(bgm_entry.BgmEntry),
    ),
    Document(
        filename="font-manifest",
        title="Font manifest",
        description="core/app/plugins/fonts/<id>/manifest.json.",
        root=font_manifest.FontManifest,
    ),
    Document(
        filename="job",
        title="Job",
        description="Row in the jobs table, returned by the jobs API.",
        root=job.Job,
        models=(job.JobError,),
    ),
    Document(
        filename="artifact",
        title="Artifact",
        description="Row of the artifact index in state.db.",
        root=artifact.Artifact,
        models=(artifact.Timing,),
    ),
    Document(
        filename="sandbox-io",
        title="Sandbox runner protocol",
        description="One request JSON on stdin, one response JSON line on stdout.",
        models=(sandbox_io.SandboxRequest,),
        adapter=TypeAdapter(sandbox_io.SandboxResponse),
    ),
    Document(
        filename="api",
        title="HTTP API bodies",
        description="Request and response bodies that are not documents themselves.",
        models=tuple(
            model
            for model in (
                api.ApiError,
                api.Problem,
                api.Health,
                api.BaseRevision,
                api.PairRequest,
                api.PairResponse,
                api.CsrfResponse,
                api.ApiKeyRequest,
                api.CredentialState,
                api.RuntimeStatus,
                api.CatalogItem,
                api.CatalogList,
                api.CreateProjectRequest,
                api.ProjectSummary,
                api.ProjectList,
                api.CreateVideoRequest,
                api.DraftRequest,
                api.ChangeRequest,
                api.MessageRequest,
                api.LinkRequest,
                api.StyleRequest,
                api.TemplateRequest,
                api.BgmCodeRequest,
                api.PresetRequest,
                api.PresetList,
                api.PreviewRequest,
                api.VideoView,
                api.CaptionLayout,
                api.PrecheckReport,
                api.ActivityRequest,
                api.Metrics,
                api.RevisionList,
                api.JobList,
            )
        ),
    ),
]


def _merge(schema: dict[str, Any], into: dict[str, Any]) -> None:
    for name, definition in schema.get("$defs", {}).items():
        if name in into and into[name] != definition:
            raise SystemExit(f"conflicting definition for {name}")
        into[name] = definition


def _strip(schema: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in schema.items() if key != "$defs"}


def build_document(document: Document) -> dict[str, Any]:
    definitions: dict[str, Any] = {}
    root_schema: dict[str, Any] = {}
    adapter_schema: dict[str, Any] | None = None
    if document.root is not None:
        root_schema = document.root.model_json_schema(
            ref_template=REF_TEMPLATE, by_alias=True
        )
        _merge(root_schema, definitions)
        definitions[document.root.__name__] = _strip(root_schema)
    for model in document.models:
        schema = model.model_json_schema(ref_template=REF_TEMPLATE, by_alias=True)
        _merge(schema, definitions)
        definitions.setdefault(model.__name__, _strip(schema))
    if document.adapter is not None:
        adapter_schema = document.adapter.json_schema(ref_template=REF_TEMPLATE)
        _merge(adapter_schema, definitions)
    for name in document.drop:
        definitions.pop(name, None)

    body: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_BASE}/{document.filename}.schema.json",
        "title": document.title,
    }
    if document.description:
        body["description"] = document.description
    if document.root is not None:
        body["$ref"] = f"#/$defs/{document.root.__name__}"
    elif adapter_schema is not None:
        for keyword in ("oneOf", "anyOf", "discriminator"):
            if keyword in adapter_schema:
                body[keyword] = adapter_schema[keyword]
        if "$ref" in adapter_schema:
            body["$ref"] = adapter_schema["$ref"]
    body["$defs"] = {name: definitions[name] for name in sorted(definitions)}
    return body


def write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def export_schemas() -> None:
    target = CORE.parent / "schemas"
    for document in DOCUMENTS:
        write_json(target / f"{document.filename}.schema.json", build_document(document))


def export_openapi() -> None:
    from app.main import create_app

    app = create_app()
    write_json(CORE / "openapi.json", app.openapi())


def main() -> int:
    export_schemas()
    export_openapi()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
