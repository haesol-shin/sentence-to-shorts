"""Project state, immutable revisions and confirmation gates."""

from __future__ import annotations

from app.ports import (
    AppError,
    AppSettings,
    CatalogPort,
    Issue,
    ProjectStore,
    ServiceDeps,
)
from app.schemas.api import (
    ActivitySpan,
    CreateProjectRequest,
    CreateVideoRequest,
    PresetRequest,
)
from app.schemas.change import ChangePlan, ChangeStatus, Op
from app.schemas.common import PERSONAL_OWNER_ID, Origin
from app.schemas.preset import Preset
from app.schemas.project import Project
from app.schemas.settings import Settings
from app.schemas.video import STAGE_ORDER, CreatedBy, Video, VideoStage
from app.services.project import revision, state

DEFAULT_TITLE = {"ko": "새 프로젝트", "en": "New project"}


def _reached(video: Video, stage: VideoStage) -> bool:
    return STAGE_ORDER.index(video.stage) >= STAGE_ORDER.index(stage)


class ProjectService:
    def __init__(self, projects: ProjectStore, catalog: CatalogPort) -> None:
        self.projects = projects
        self.catalog = catalog

    def create_project(self, req: CreateProjectRequest) -> Project:
        created = revision.now()
        project = Project(
            schema_version=1,
            id=self.projects.new_id("p"),
            owner_id=PERSONAL_OWNER_ID,
            title=req.title or DEFAULT_TITLE[req.language.value],
            created_at=created,
            updated_at=created,
            defaults=state.default_settings(req.language, self.catalog),
            video_ids=[],
        )
        self.projects.put_project(project)
        return project

    def create_video(self, project_id: str, req: CreateVideoRequest) -> Video:
        """Create revision one through the shared validation and append path."""
        if req.from_video_id is not None or req.preset_id is not None:
            from app.services.project import derive

            video = derive.create_video(self, project_id, req)
        else:
            project = self.projects.get_project(project_id)
            video = Video(
                schema_version=2,
                id=self.projects.new_id("v"),
                project_id=project.id,
                owner_id=project.owner_id,
                revision=1,
                parent_revision=None,
                created_at=revision.now(),
                created_by=CreatedBy.create,
                change_id=None,
                stage=VideoStage.draft,
                derived_from=None,
                topic="",
                material=[],
                reference=None,
                settings=project.defaults.model_copy(deep=True),
                script=None,
                scene_order=[],
                scenes={},
            )
        issues = self.validate(video)
        if issues:
            codes = {issue.code for issue in issues}
            code = "unknown_catalog_id" if "unknown_catalog_id" in codes else "invalid_combination"
            raise AppError(code, errors=issues)
        return self.projects.append_revision(video)

    def view(self, video_id: str) -> Video:
        return self.projects.get_video(video_id)

    def apply_ops(self, video: Video, ops: list[Op], origin_default: Origin) -> Video:
        """Pure: apply ops to an in-memory video without writing any store.

        Values that would need a confirmation stay as they are; ``state.apply``
        reports them for the change plan.
        """
        return state.apply(video, ops, origin_default).video

    def validate(self, video: Video) -> list[Issue]:
        return state.validate(video, self.catalog)

    def commit(self, plan: ChangePlan, base_revision: int) -> Video:
        """Apply a plan as the next revision. Applying is the user's confirmation
        of exactly the reasons the plan lists.

        A plan is applied exactly when a revision carries its change id, so a
        crash between the revision write and the status write is repaired here,
        even after later revisions, and the retry gets the written revision.
        """
        if plan.status is ChangeStatus.applied and plan.applied_revision is not None:
            return self.projects.get_video(plan.video_id, plan.applied_revision)
        head = self.projects.get_video(plan.video_id)
        plan = self._settle(plan, self._written(plan.video_id), head.revision)
        if plan.status is ChangeStatus.applied and plan.applied_revision is not None:
            return self.projects.get_video(plan.video_id, plan.applied_revision)
        if plan.status is not ChangeStatus.proposed or plan.base_revision != head.revision:
            raise AppError("change_stale")
        revision.require_head(head, base_revision)
        applied = state.apply(
            head, plan.ops, state.SOURCE_ORIGIN[plan.source], state.confirmed_by(plan)
        )
        if applied.concept_changes:
            raise AppError("concept_locked")
        # A generated script or scene starts without translations. Keep the
        # layer and let the user fill them; validate() still reports the gap and
        # rendering rejects the line until it has its text.
        issues = state.new_issues(
            head,
            applied.video,
            self.catalog,
            ignore=("caption_text_missing",),
        )
        if issues:
            raise AppError("invalid_combination", errors=issues)
        video = self._append(applied.video, head, CreatedBy.change, plan.id)
        return self._mark_applied(plan, video.revision)

    def undo(self, video_id: str, base_revision: int) -> Video:
        head = self.projects.get_video(video_id)
        revision.require_head(head, base_revision)
        source = revision.undo_source(self.projects, head)
        return self._append(source, head, CreatedBy.undo)

    def confirm_concept(self, video_id: str, base_revision: int) -> Video:
        head = self.projects.get_video(video_id)
        revision.require_head(head, base_revision)
        if _reached(head, VideoStage.concept_confirmed):
            return head
        if not head.topic.strip():
            raise AppError("concept_missing")
        return self._advance(head, VideoStage.concept_confirmed)

    def confirm_script(self, video_id: str, base_revision: int) -> Video:
        head = self.projects.get_video(video_id)
        revision.require_head(head, base_revision)
        if _reached(head, VideoStage.script_confirmed):
            return head
        if head.script is None or not head.scene_order:
            raise AppError("script_missing")
        return self._advance(head, VideoStage.script_confirmed)

    def confirm_scenes(self, video_id: str, base_revision: int) -> Video:
        head = self.projects.get_video(video_id)
        revision.require_head(head, base_revision)
        if _reached(head, VideoStage.scenes_confirmed):
            return head
        if not _reached(head, VideoStage.script_confirmed):
            raise AppError("script_not_confirmed")
        if not head.scene_order or any(scene.visual is None for scene in head.scenes.values()):
            raise AppError("scene_data_missing")
        return self._advance(head, VideoStage.scenes_confirmed)

    def add_activity(self, video_id: str, spans: list[ActivitySpan]) -> None:
        """Store active and waiting spans of an existing video. Spans never make a
        revision, so recording time cannot change the video."""
        self.projects.get_video(video_id)
        if any(span.end_ms < span.start_ms for span in spans):
            raise AppError("validation_failed")
        self.projects.add_activity(video_id, spans)

    def pick_varied(
        self, project: Project, previous: list[Video], seed: int
    ) -> Settings:
        from app.services.project import derive

        return derive.pick_varied(self.catalog, project, previous, seed)

    def save_preset(self, project_id: str, req: PresetRequest) -> Preset:
        from app.services.project import presets

        return presets.save_preset(self, project_id, req)

    def _advance(self, head: Video, stage: VideoStage) -> Video:
        return self._append(head.model_copy(update={"stage": stage}), head, CreatedBy.confirm)

    def _append(
        self, video: Video, head: Video, created_by: CreatedBy, change_id: str | None = None
    ) -> Video:
        """Write the next revision, then settle the other plans of the video: plans
        made against an older head expire (CONTRACTS 4.1). The plan being applied
        is left to the caller."""
        written = self.projects.append_revision(
            revision.next_revision(video, head, created_by, change_id)
        )
        carried = self._written(written.id)
        for other in self.projects.list_changes(written.id):
            if other.id != change_id:
                self._settle(other, carried, written.revision)
        return written

    def _written(self, video_id: str) -> dict[str, int]:
        """Revision number of each change id that a revision carries."""
        return {
            info.change_id: info.revision
            for info in self.projects.list_revisions(video_id)
            if info.change_id is not None
        }

    def _settle(self, plan: ChangePlan, written: dict[str, int], head: int) -> ChangePlan:
        """The one rule for a plan's state: applied when a revision carries its id;
        stale when it is still proposed and its base is older than the head.
        Stores and returns the corrected plan."""
        applied_at = written.get(plan.id)
        if applied_at is not None:
            if plan.status is ChangeStatus.applied and plan.applied_revision == applied_at:
                return plan
            settled = plan.model_copy(
                update={"status": ChangeStatus.applied, "applied_revision": applied_at}
            )
        elif plan.status is ChangeStatus.proposed and plan.base_revision < head:
            settled = plan.model_copy(update={"status": ChangeStatus.stale})
        else:
            return plan
        self.projects.put_change(settled)
        return settled

    def _mark_applied(self, plan: ChangePlan, applied_revision: int) -> Video:
        self.projects.put_change(
            plan.model_copy(
                update={"status": ChangeStatus.applied, "applied_revision": applied_revision}
            )
        )
        return self.projects.get_video(plan.video_id, applied_revision)


def create(settings: AppSettings, deps: ServiceDeps) -> ProjectService:
    return ProjectService(deps.project_store, deps.catalog)


__all__ = ["ProjectService", "create"]
