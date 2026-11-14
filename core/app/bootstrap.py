"""The only composition root: wire adapters from providers and assemble services.

Every factory is called here once. A provider name that is not registered, or a
registered provider that is not implemented, fails at startup with a clear error.
Only external adapters have a fixture implementation; services have one assembly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar, cast

from app.access import SessionGuard
from app.access import create as create_access
from app.jobs import UnavailableJobSubmitter
from app.llm.providers.anthropic_api.adapter import create as create_anthropic
from app.llm.providers.claude_cli.adapter import create as create_claude_cli
from app.llm.providers.fixture.adapter import create as create_fixture_llm
from app.llm.providers.openai_compat.adapter import create as create_openai_compat
from app.plugins.registry import Registry
from app.ports import (
    AlignerPort,
    ArtifactStore,
    DownloaderPort,
    JobInputStore,
    JobStore,
    JobSubmitter,
    LlmPort,
    MediaPort,
    ProjectStore,
    SandboxPort,
    ServiceDeps,
    TranscriberPort,
    TtsPort,
)
from app.runtime import RuntimeSetup
from app.runtime import create as create_runtime_setup
from app.services.assemble import service as assemble_service
from app.services.pipeline.types import Services
from app.services.project import service as project_service
from app.services.reference import service as reference_service
from app.services.render import service as render_service
from app.services.sound import service as sound_service
from app.services.story import service as story_service
from app.services.templates import service as templates_service
from app.services.voice import service as voice_service
from app.settings import Settings
from app.storage.fixture import (
    create_artifact_store,
    create_job_store,
    create_project_store,
)
from app.storage.job_inputs import create_job_input_store
from app.tools.align import adapter as align_adapter
from app.tools.asr import adapter as asr_adapter
from app.tools.downloaders import adapter as downloader_adapter
from app.tools.media import adapter as media_adapter
from app.tools.sandbox import adapter as sandbox_adapter
from app.tools.tts.fixed_wav.adapter import create as create_fixed_wav

AdapterFactory = Callable[[Settings], object]
Built = TypeVar("Built")

ADAPTER_FACTORIES: dict[str, dict[str, AdapterFactory]] = {
    "llm": {
        "fixture": create_fixture_llm,
        "anthropic_api": create_anthropic,
        "openai_compat": create_openai_compat,
        "claude_cli": create_claude_cli,
    },
    "tts": {"fixed_wav": create_fixed_wav},
    "aligner": {"default": align_adapter.create, "skeleton": align_adapter.create_skeleton},
    "transcriber": {"default": asr_adapter.create, "skeleton": asr_adapter.create_skeleton},
    "media": {"default": media_adapter.create, "skeleton": media_adapter.create_skeleton},
    "sandbox": {"default": sandbox_adapter.create, "skeleton": sandbox_adapter.create_skeleton},
    "downloader": {
        "default": downloader_adapter.create,
        "skeleton": downloader_adapter.create_skeleton,
    },
}


@dataclass(frozen=True)
class AppDeclaration:
    """What OpenAPI and the docs flags need, without building adapters."""

    version: str
    docs_enabled: bool
    settings: Settings


def declare(settings: Settings | None = None) -> AppDeclaration:
    resolved = settings or Settings()
    return AppDeclaration(
        version=resolved.app_version,
        docs_enabled=not resolved.lan,
        settings=resolved,
    )


@dataclass
class AppRuntime:
    settings: Settings
    catalog: Registry
    llm: LlmPort
    tts: TtsPort
    media: MediaPort
    sandbox: SandboxPort
    aligner: AlignerPort
    transcriber: TranscriberPort
    downloader: DownloaderPort
    project_store: ProjectStore
    artifact_store: ArtifactStore
    job_store: JobStore
    job_inputs: JobInputStore
    submitter: JobSubmitter
    services: Services
    access: SessionGuard
    runtime_setup: RuntimeSetup

    def close(self) -> None:
        self.tts.close()


def _build_adapter(name: str, settings: Settings) -> Built:
    implementations = ADAPTER_FACTORIES[name]
    table = settings.providers.adapters
    if settings.profile == "fixture":
        selected = settings.providers.fixture_adapters.get(name, table.get(name))
    else:
        selected = table.get(name)
    if selected is None:
        raise RuntimeError(f"app.yaml does not select a {name} adapter")
    factory = implementations.get(selected)
    if factory is None:
        known = ", ".join(sorted(implementations))
        raise RuntimeError(
            f"unknown {name} adapter {selected!r}; select one of: {known}"
        )
    if selected == "skeleton" and settings.profile != "fixture":
        raise RuntimeError(
            f"{name} adapter 'skeleton' is only available in the fixture profile"
        )
    try:
        return cast(Built, factory(settings))
    except NotImplementedError as error:
        raise RuntimeError(
            f"{name} adapter {selected!r} is not implemented"
        ) from error


def _build_services(settings: Settings, deps: ServiceDeps) -> Services:
    return Services(
        project=project_service.create(settings, deps),
        story=story_service.create(settings, deps),
        reference=reference_service.create(settings, deps),
        render=render_service.create(settings, deps),
        voice=voice_service.create(settings, deps),
        sound=sound_service.create(settings, deps),
        assemble=assemble_service.create(settings, deps),
        templates=templates_service.create(settings, deps),
    )


def build_runtime(settings: Settings | None = None) -> AppRuntime:
    resolved = settings or Settings()
    catalog = Registry(data_dir=resolved.data_dir)
    catalog.load()
    project_store = create_project_store(resolved)
    artifact_store = create_artifact_store(resolved)
    job_store = create_job_store(resolved)
    job_inputs = create_job_input_store(resolved)
    deps = ServiceDeps(
        project_store=project_store,
        artifact_store=artifact_store,
        job_store=job_store,
        catalog=catalog,
        llm=_build_adapter("llm", resolved),
        tts=_build_adapter("tts", resolved),
        aligner=_build_adapter("aligner", resolved),
        transcriber=_build_adapter("transcriber", resolved),
        media=_build_adapter("media", resolved),
        sandbox=_build_adapter("sandbox", resolved),
        downloader=_build_adapter("downloader", resolved),
    )
    services = _build_services(resolved, deps)
    access = create_access(resolved)
    runtime_setup = create_runtime_setup(resolved, deps.downloader, job_store)
    return AppRuntime(
        settings=resolved,
        catalog=catalog,
        llm=deps.llm,
        tts=deps.tts,
        media=deps.media,
        sandbox=deps.sandbox,
        aligner=deps.aligner,
        transcriber=deps.transcriber,
        downloader=deps.downloader,
        project_store=project_store,
        artifact_store=artifact_store,
        job_store=job_store,
        job_inputs=job_inputs,
        submitter=UnavailableJobSubmitter(job_store),
        services=services,
        access=access,
        runtime_setup=runtime_setup,
    )
