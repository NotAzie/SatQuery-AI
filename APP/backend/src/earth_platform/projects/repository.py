from __future__ import annotations

from typing import Protocol

from earth_platform.projects.models import (
    Project,
    ProjectActivity,
    ProjectEarthView,
    ProjectInvestigationCollection,
    ProjectInvestigationCollectionMemberUpdate,
    ProjectInvestigationComparison,
    ProjectInvestigationRef,
    ProjectInvestigationRelationship,
    ProjectInvestigationTemplate,
    ProjectInvestigationTemplateRun,
    ProjectInvestigationTemplateRunUpdate,
    ProjectMonitoringLink,
    ProjectNote,
    ProjectSessionLink,
)
from earth_platform.sessions.models import Session


class ProjectRepository(Protocol):
    async def open(self) -> None: ...
    async def aclose(self) -> None: ...
    async def create(self, project: Project) -> Project: ...
    async def get(self, project_id: str) -> Project: ...
    async def list_projects(
        self, *, include_archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Project]: ...
    async def update(self, project: Project, *, expected_revision: int) -> Project: ...
    async def create_session(self, project_id: str, session: Session) -> ProjectSessionLink: ...
    async def link_session(
        self, project_id: str, session_id: str
    ) -> ProjectSessionLink: ...
    async def list_sessions(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectSessionLink]: ...
    async def get_session_link(
        self, project_id: str, session_id: str
    ) -> ProjectSessionLink: ...
    async def list_unlinked_sessions(self, *, limit: int = 50) -> list[Session]: ...
    async def create_investigation_comparison(
        self, project_id: str, comparison: ProjectInvestigationComparison
    ) -> ProjectInvestigationComparison: ...
    async def get_investigation_comparison(
        self, project_id: str, comparison_id: str
    ) -> ProjectInvestigationComparison: ...
    async def list_investigation_comparisons(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectInvestigationComparison]: ...
    async def delete_investigation_comparison(
        self, project_id: str, comparison_id: str
    ) -> None: ...
    async def create_investigation_relationship(
        self, project_id: str, relationship: ProjectInvestigationRelationship
    ) -> ProjectInvestigationRelationship: ...
    async def list_investigation_relationships(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectInvestigationRelationship]: ...
    async def delete_investigation_relationship(
        self, project_id: str, relationship_id: str
    ) -> None: ...
    async def create_investigation_collection(
        self, collection: ProjectInvestigationCollection
    ) -> ProjectInvestigationCollection: ...
    async def get_investigation_collection(
        self, project_id: str, collection_id: str
    ) -> ProjectInvestigationCollection: ...
    async def list_investigation_collections(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectInvestigationCollection]: ...
    async def update_investigation_collection(
        self,
        collection: ProjectInvestigationCollection,
        *,
        expected_revision: int,
    ) -> ProjectInvestigationCollection: ...
    async def update_investigation_collection_members(
        self,
        project_id: str,
        collection_id: str,
        update: ProjectInvestigationCollectionMemberUpdate,
    ) -> ProjectInvestigationCollection: ...
    async def delete_investigation_collection(
        self, project_id: str, collection_id: str
    ) -> None: ...
    async def create_investigation_template(
        self, template: ProjectInvestigationTemplate
    ) -> ProjectInvestigationTemplate: ...
    async def list_investigation_templates(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectInvestigationTemplate]: ...
    async def get_investigation_template(
        self, project_id: str, template_id: str
    ) -> ProjectInvestigationTemplate: ...
    async def update_investigation_template(
        self,
        template: ProjectInvestigationTemplate,
        *,
        expected_revision: int,
    ) -> ProjectInvestigationTemplate: ...
    async def delete_investigation_template(self, project_id: str, template_id: str) -> None: ...
    async def apply_investigation_template(
        self, project_id: str, template_id: str
    ) -> ProjectInvestigationTemplateRun: ...
    async def list_investigation_template_runs(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectInvestigationTemplateRun]: ...
    async def update_investigation_template_run(
        self,
        project_id: str,
        run_id: str,
        update: ProjectInvestigationTemplateRunUpdate,
    ) -> ProjectInvestigationTemplateRun: ...
    async def create_note(self, project_id: str, note: ProjectNote) -> ProjectNote: ...
    async def get_note(self, project_id: str, note_id: str) -> ProjectNote: ...
    async def list_notes(
        self,
        project_id: str,
        *,
        investigation_id: str | None = None,
        investigation_session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectNote]: ...
    async def update_note(
        self, note: ProjectNote, *, expected_revision: int
    ) -> ProjectNote: ...
    async def delete_note(self, project_id: str, note_id: str) -> None: ...
    async def create_view_from_bookmark(
        self,
        project_id: str,
        session_id: str,
        bookmark_id: str,
        title: str,
        investigation_id: str | None = None,
    ) -> ProjectEarthView: ...
    async def list_views(
        self,
        project_id: str,
        *,
        investigation_id: str | None = None,
        source_session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectEarthView]: ...
    async def delete_view(self, project_id: str, view_id: str) -> None: ...
    async def list_activity(
        self,
        project_id: str,
        *,
        investigation: ProjectInvestigationRef | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectActivity]: ...
    async def link_monitoring_schedule(
        self, project_id: str, schedule_id: str, mission_id: str
    ) -> ProjectMonitoringLink: ...
    async def list_monitoring_links(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectMonitoringLink]: ...
    async def unlink_monitoring_schedule(self, project_id: str, schedule_id: str) -> None: ...
