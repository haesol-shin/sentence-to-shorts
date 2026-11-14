"""Run-time bundle of service instances assembled by the bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.assemble.service import AssembleService
from app.services.project.service import ProjectService
from app.services.reference.service import ReferenceService
from app.services.render.service import RenderService
from app.services.sound.service import SoundService
from app.services.story.service import StoryService
from app.services.templates.service import TemplatesService
from app.services.voice.service import VoiceService


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
