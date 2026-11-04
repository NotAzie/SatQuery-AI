from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from earth_platform.sessions.models import Session
from earth_platform.shared.clock import utcnow
from earth_platform.shared.earth import EarthContext
from earth_platform.shared.ids import new_id


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prj"))
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    archived: bool = False
    revision: int = Field(default=1, ge=1)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    archived: bool | None = None


class ProjectSessionLink(BaseModel):
    project_id: str
    session_id: str
    linked_at: datetime
    session: Session


class ProjectInvestigationRef(BaseModel):
    """A reference to an Engine-owned investigation as observed in a linked session."""

    investigation_id: str
    session_id: str


class ProjectInvestigationComparison(BaseModel):
    id: str = Field(default_factory=lambda: new_id("comparison"))
    project_id: str
    title: str = Field(min_length=1, max_length=160)
    left: ProjectInvestigationRef
    right: ProjectInvestigationRef
    engine_comparison_id: str | None = Field(default=None, min_length=1, max_length=128)
    engine_comparison_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_engine_comparison_reference(self) -> "ProjectInvestigationComparison":
        if (self.engine_comparison_id is None) != (self.engine_comparison_sha256 is None):
            raise ValueError(
                "engine_comparison_id and engine_comparison_sha256 must be set together"
            )
        return self


class ProjectInvestigationComparisonCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    left: ProjectInvestigationRef
    right: ProjectInvestigationRef

    @model_validator(mode="after")
    def validate_distinct_investigations(self) -> "ProjectInvestigationComparisonCreate":
        if self.left.investigation_id == self.right.investigation_id:
            raise ValueError("A comparison requires two different investigations")
        return self


class ProjectNote(BaseModel):
    id: str = Field(default_factory=lambda: new_id("note"))
    project_id: str
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=20_000)
    investigation_id: str | None = Field(default=None, min_length=1, max_length=128)
    investigation_session_id: str | None = Field(default=None, min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_investigation_reference(self) -> "ProjectNote":
        if (self.investigation_id is None) != (self.investigation_session_id is None):
            raise ValueError("investigation_id and investigation_session_id must be set together")
        return self


class ProjectNoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=20_000)
    investigation_id: str | None = Field(default=None, min_length=1, max_length=128)
    investigation_session_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_investigation_reference(self) -> "ProjectNoteCreate":
        if (self.investigation_id is None) != (self.investigation_session_id is None):
            raise ValueError("investigation_id and investigation_session_id must be set together")
        return self


class ProjectNoteUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    body: str | None = Field(default=None, min_length=1, max_length=20_000)


class ProjectEarthView(BaseModel):
    id: str = Field(default_factory=lambda: new_id("view"))
    project_id: str
    title: str = Field(min_length=1, max_length=160)
    source_session_id: str
    source_bookmark_id: str
    investigation_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_session_exists: bool = True
    context: EarthContext
    created_at: datetime = Field(default_factory=utcnow)


class ProjectEarthViewCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    source_session_id: str = Field(min_length=1)
    source_bookmark_id: str = Field(min_length=1)
    investigation_id: str | None = Field(default=None, min_length=1, max_length=128)


ProjectActivityAction = Literal[
    "project.created",
    "project.updated",
    "project.archived",
    "project.unarchived",
    "session.linked",
    "note.created",
    "note.updated",
    "note.deleted",
    "earth_view.saved",
    "earth_view.deleted",
    "investigation_comparison.created",
    "investigation_comparison.deleted",
    "monitoring.linked",
    "monitoring.unlinked",
]


class ProjectActivity(BaseModel):
    id: str = Field(default_factory=lambda: new_id("activity"))
    project_id: str
    action: ProjectActivityAction
    occurred_at: datetime = Field(default_factory=utcnow)
    subject_id: str | None = None
    session_id: str | None = None
    label: str | None = Field(default=None, max_length=160)


class ProjectMonitoringLink(BaseModel):
    project_id: str
    schedule_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    linked_at: datetime = Field(default_factory=utcnow)
