"""Run-time bundle of service instances assembled by the bootstrap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ports import ArtifactStore, CatalogPort, JobStore
from app.services.assemble.service import AssembleService
from app.services.project.service import ProjectService
from app.services.reference.service import ReferenceService
from app.services.render.service import RenderService
from app.services.sound.service import SoundService
from app.services.story.service import StoryService
from app.services.templates.service import TemplatesService
from app.services.voice.service import VoiceService

BuildStateKey = tuple[str, int, str, str | None, str | None]
"""Video, revision, artifact kind, scene id and line id of a build observation."""

PreviousKey = tuple[str, str, str | None, str | None]
"""Video, artifact kind, scene id and line id of the last published key."""


@dataclass(frozen=True)
class KeyRuntime:
    """Runtime identities that belong in cache keys.

    A value left as None is read from the active port or from the installed
    implementation, so the bootstrap needs no extra wiring. Tests and tools can
    pin every value explicitly.
    """

    tts_digest: str | None = None
    sandbox_digest: str | None = None
    aligner_digest: str | None = None
    renderer_revision: str | None = None
    encoder_digest: str | None = None


@dataclass(frozen=True)
class Services:
    project: ProjectService
    story: StoryService
    reference: ReferenceService
    render: RenderService
    voice: VoiceService
    sound: SoundService
    assemble: AssembleService
    templates: TemplatesService
    artifacts: ArtifactStore | None = None
    catalog: CatalogPort | None = None
    jobs: JobStore | None = None
    key_runtime: KeyRuntime | None = None
    build_states: dict[BuildStateKey, dict[str, Any]] = field(default_factory=dict)
    previous_keys: dict[PreviousKey, str] = field(default_factory=dict)

    @property
    def artifact_store(self) -> ArtifactStore:
        return self.artifacts if self.artifacts is not None else self.render.artifacts

    @property
    def catalog_port(self) -> CatalogPort:
        return self.catalog if self.catalog is not None else self.project.catalog


__all__ = [
    "BuildStateKey",
    "KeyRuntime",
    "PreviousKey",
    "Services",
]
