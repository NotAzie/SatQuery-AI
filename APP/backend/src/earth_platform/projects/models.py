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


ProjectInvestigationRelationshipType = Literal[
    "related_to",
    "follow_up_to",
    "baseline_for",
    "context_for",
]


class ProjectInvestigationRelationship(BaseModel):
    id: str = Field(default_factory=lambda: new_id("relationship"))
    project_id: str
    from_investigation: ProjectInvestigationRef
    to_investigation: ProjectInvestigationRef
    relationship_type: ProjectInvestigationRelationshipType
    rationale: str = Field(min_length=1, max_length=2000)
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def validate_distinct_endpoints(self) -> "ProjectInvestigationRelationship":
        if self.from_investigation == self.to_investigation:
            raise ValueError("An investigation relationship requires two distinct investigations")
        if not self.rationale.strip():
            raise ValueError("A relationship rationale cannot be blank")
        return self


class ProjectInvestigationRelationshipCreate(BaseModel):
    from_investigation: ProjectInvestigationRef
    to_investigation: ProjectInvestigationRef
    relationship_type: ProjectInvestigationRelationshipType
    rationale: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_distinct_endpoints(self) -> "ProjectInvestigationRelationshipCreate":
        if self.from_investigation == self.to_investigation:
            raise ValueError("An investigation relationship requires two distinct investigations")
        if not self.rationale.strip():
            raise ValueError("A relationship rationale cannot be blank")
        return self


class ProjectInvestigationCollection(BaseModel):
    id: str = Field(default_factory=lambda: new_id("collection"))
    project_id: str
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    investigations: list[ProjectInvestigationRef] = Field(default_factory=list, max_length=500)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_unique_investigations(self) -> "ProjectInvestigationCollection":
        references = [
            (item.session_id, item.investigation_id) for item in self.investigations
        ]
        if len(references) != len(set(references)):
            raise ValueError("An investigation can only appear once in a collection")
        return self


class ProjectInvestigationCollectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)


class ProjectInvestigationCollectionUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class ProjectInvestigationCollectionMemberUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    operation: Literal["add", "remove"]
    investigation: ProjectInvestigationRef


class ProjectInvestigationTemplateStep(BaseModel):
    id: str = Field(default_factory=lambda: new_id("template-step"))
    title: str = Field(min_length=1, max_length=160)


class ProjectInvestigationTemplateStepCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ProjectInvestigationTemplate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("template"))
    project_id: str
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    steps: list[ProjectInvestigationTemplateStep] = Field(min_length=1, max_length=30)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_unique_steps(self) -> "ProjectInvestigationTemplate":
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Template step IDs must be unique")
        return self


class ProjectInvestigationTemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    steps: list[ProjectInvestigationTemplateStepCreate] = Field(min_length=1, max_length=30)


class ProjectInvestigationTemplateUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    steps: list[ProjectInvestigationTemplateStepCreate] | None = Field(
        default=None, min_length=1, max_length=30
    )


class ProjectInvestigationTemplateRunStep(ProjectInvestigationTemplateStep):
    completed: bool = False


class ProjectInvestigationTemplateRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("template-run"))
    project_id: str
    template_id: str
    template_revision: int = Field(default=1, ge=1)
    template_title: str = Field(min_length=1, max_length=160)
    session_id: str
    steps: list[ProjectInvestigationTemplateRunStep] = Field(min_length=1, max_length=30)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    revision: int = Field(default=1, ge=1)


class ProjectInvestigationTemplateRunUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    completed_step_ids: list[str] = Field(max_length=30)

    @model_validator(mode="after")
    def validate_unique_completed_steps(self) -> "ProjectInvestigationTemplateRunUpdate":
        if len(self.completed_step_ids) != len(set(self.completed_step_ids)):
            raise ValueError("Completed step IDs must be unique")
        return self


ProjectSearchKind = Literal[
    "project",
    "session",
    "note",
    "earth_view",
    "comparison",
    "relationship",
    "investigation_template",
    "investigation_collection",
]


class ProjectSearchHit(BaseModel):
    kind: ProjectSearchKind
    id: str
    title: str
    summary: str
    score: float = Field(ge=0, le=1)
    matched_terms: list[str]
    matched_fields: list[Literal["title", "content"]]
    created_at: datetime
    session_id: str | None = None
    investigation_id: str | None = None


class ProjectSearchResponse(BaseModel):
    project_id: str
    query: str
    results: list[ProjectSearchHit]
    total_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


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
    "investigation_relationship.created",
    "investigation_relationship.deleted",
    "investigation_template.updated",
    "investigation_collection.created",
    "investigation_collection.updated",
    "investigation_collection.deleted",
    "investigation_collection.member_added",
    "investigation_collection.member_removed",
    "investigation_template.created",
    "investigation_template.deleted",
    "investigation_template.applied",
    "investigation_template_run.updated",
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
    investigations: list[ProjectInvestigationRef] = Field(default_factory=list)


class ProjectMonitoringLink(BaseModel):
    project_id: str
    schedule_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    linked_at: datetime = Field(default_factory=utcnow)
