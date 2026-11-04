"""Project organization and Project-owned session endpoints."""

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from earth_platform.api.deps import AgentRuntimeDep, EngineDep, ProjectRepositoryDep
from earth_platform.engine.models import (
    EngineInvestigationComparison,
    EngineInvestigationComparisonRequest,
)
from earth_platform.projects.models import (
    Project,
    ProjectActivity,
    ProjectCreate,
    ProjectEarthView,
    ProjectEarthViewCreate,
    ProjectInvestigationComparison,
    ProjectInvestigationComparisonCreate,
    ProjectInvestigationRef,
    ProjectMonitoringLink,
    ProjectNote,
    ProjectNoteCreate,
    ProjectNoteUpdate,
    ProjectSessionLink,
    ProjectUpdate,
)
from earth_platform.sessions.models import Session
from earth_platform.shared.clock import utcnow
from earth_platform.shared.errors import ConflictError, NotFoundError, ValidationFailedError

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectSession(BaseModel):
    title: str | None = Field(default=None, max_length=160)


class LinkProjectSession(BaseModel):
    session_id: str = Field(min_length=1)


class LinkProjectMonitoringSchedule(BaseModel):
    schedule_id: str = Field(min_length=1)


async def _require_project_investigation(
    project_id: str,
    session_id: str,
    investigation_id: str,
    projects: ProjectRepositoryDep,
    runtime: AgentRuntimeDep,
) -> None:
    link = await projects.get_session_link(project_id, session_id)
    if link.session.engine_agent_session_id is None:
        raise NotFoundError(
            f"Investigation '{investigation_id}' is not available in this Project session"
        )
    transcript = await runtime.get_engine_session(session_id)
    if investigation_id not in transcript.investigation_ids:
        raise NotFoundError(
            f"Investigation '{investigation_id}' is not available in this Project session"
        )


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, projects: ProjectRepositoryDep
) -> Project:
    return await projects.create(Project(**body.model_dump()))


@router.get("", response_model=list[Project])
async def list_projects(
    projects: ProjectRepositoryDep,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Project]:
    return await projects.list_projects(
        include_archived=include_archived, limit=limit, offset=offset
    )


@router.get("/unlinked-sessions", response_model=list[Session])
async def list_unlinked_sessions(
    projects: ProjectRepositoryDep,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[Session]:
    return await projects.list_unlinked_sessions(limit=limit)


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, projects: ProjectRepositoryDep) -> Project:
    return await projects.get(project_id)


@router.patch("/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    projects: ProjectRepositoryDep,
) -> Project:
    changes = body.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    if not changes:
        raise ValidationFailedError("At least one Project field must be updated")
    if "title" in changes and changes["title"] is None:
        raise ValidationFailedError("Project title cannot be null")
    project = await projects.get(project_id)
    project = project.model_copy(update=changes)
    project.updated_at = utcnow()
    return await projects.update(project, expected_revision=body.expected_revision)


@router.get("/{project_id}/sessions", response_model=list[ProjectSessionLink])
async def list_project_sessions(
    project_id: str,
    projects: ProjectRepositoryDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectSessionLink]:
    return await projects.list_sessions(project_id, limit=limit, offset=offset)


@router.get("/{project_id}/activity", response_model=list[ProjectActivity])
async def list_project_activity(
    project_id: str,
    projects: ProjectRepositoryDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectActivity]:
    return await projects.list_activity(project_id, limit=limit, offset=offset)


@router.get(
    "/{project_id}/monitoring-links",
    response_model=list[ProjectMonitoringLink],
)
async def list_project_monitoring_links(
    project_id: str,
    projects: ProjectRepositoryDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectMonitoringLink]:
    return await projects.list_monitoring_links(project_id, limit=limit, offset=offset)


@router.post(
    "/{project_id}/monitoring-links",
    response_model=ProjectMonitoringLink,
    status_code=status.HTTP_201_CREATED,
)
async def link_project_monitoring_schedule(
    project_id: str,
    body: LinkProjectMonitoringSchedule,
    projects: ProjectRepositoryDep,
    engine: EngineDep,
) -> ProjectMonitoringLink:
    project = await projects.get(project_id)
    if project.archived:
        raise ConflictError("Cannot link monitoring to an archived Project")
    schedules = await engine.list_monitoring_schedules()
    schedule = next(
        (item for item in schedules if item.schedule_id == body.schedule_id),
        None,
    )
    if schedule is None:
        raise NotFoundError(f"Engine monitoring schedule '{body.schedule_id}' was not found")
    return await projects.link_monitoring_schedule(
        project_id, schedule.schedule_id, schedule.mission_id
    )


@router.delete(
    "/{project_id}/monitoring-links/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_project_monitoring_schedule(
    project_id: str,
    schedule_id: str,
    projects: ProjectRepositoryDep,
) -> Response:
    await projects.unlink_monitoring_schedule(project_id, schedule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{project_id}/investigations",
    response_model=list[ProjectInvestigationRef],
)
async def list_project_investigations(
    project_id: str,
    projects: ProjectRepositoryDep,
    runtime: AgentRuntimeDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectInvestigationRef]:
    links = await projects.list_sessions(project_id, limit=limit, offset=offset)
    investigations: list[ProjectInvestigationRef] = []
    for link in links:
        if link.session.engine_agent_session_id is None:
            continue
        transcript = await runtime.get_engine_session(link.session_id)
        investigations.extend(
            ProjectInvestigationRef(
                investigation_id=investigation_id,
                session_id=link.session_id,
            )
            for investigation_id in sorted(set(transcript.investigation_ids))
        )
    return investigations


@router.get(
    "/{project_id}/investigations/{investigation_id}",
    response_model=ProjectInvestigationRef,
)
async def get_project_investigation(
    project_id: str,
    investigation_id: str,
    session_id: str,
    projects: ProjectRepositoryDep,
    runtime: AgentRuntimeDep,
) -> ProjectInvestigationRef:
    await _require_project_investigation(
        project_id, session_id, investigation_id, projects, runtime
    )
    return ProjectInvestigationRef(
        investigation_id=investigation_id,
        session_id=session_id,
    )


@router.post(
    "/{project_id}/comparisons",
    response_model=ProjectInvestigationComparison,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_investigation_comparison(
    project_id: str,
    body: ProjectInvestigationComparisonCreate,
    projects: ProjectRepositoryDep,
    runtime: AgentRuntimeDep,
    engine: EngineDep,
) -> ProjectInvestigationComparison:
    project = await projects.get(project_id)
    if project.archived:
        raise ConflictError("Cannot create a comparison in an archived Project")
    await _require_project_investigation(
        project_id,
        body.left.session_id,
        body.left.investigation_id,
        projects,
        runtime,
    )
    await _require_project_investigation(
        project_id,
        body.right.session_id,
        body.right.investigation_id,
        projects,
        runtime,
    )
    engine_comparison = await engine.create_investigation_comparison(
        EngineInvestigationComparisonRequest(
            investigation_ids=[
                body.left.investigation_id,
                body.right.investigation_id,
            ]
        )
    )
    comparison = ProjectInvestigationComparison(
        project_id=project_id,
        **body.model_dump(),
        engine_comparison_id=engine_comparison.comparison_id,
        engine_comparison_sha256=engine_comparison.comparison_sha256,
    )
    return await projects.create_investigation_comparison(project_id, comparison)


@router.get(
    "/{project_id}/comparisons",
    response_model=list[ProjectInvestigationComparison],
)
async def list_project_investigation_comparisons(
    project_id: str,
    projects: ProjectRepositoryDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectInvestigationComparison]:
    return await projects.list_investigation_comparisons(
        project_id, limit=limit, offset=offset
    )


@router.get(
    "/{project_id}/comparisons/{comparison_id}",
    response_model=ProjectInvestigationComparison,
)
async def get_project_investigation_comparison(
    project_id: str,
    comparison_id: str,
    projects: ProjectRepositoryDep,
) -> ProjectInvestigationComparison:
    return await projects.get_investigation_comparison(project_id, comparison_id)


@router.get(
    "/{project_id}/comparisons/{comparison_id}/engine-result",
    response_model=EngineInvestigationComparison,
)
async def get_project_investigation_comparison_result(
    project_id: str,
    comparison_id: str,
    projects: ProjectRepositoryDep,
    runtime: AgentRuntimeDep,
    engine: EngineDep,
) -> EngineInvestigationComparison:
    comparison = await projects.get_investigation_comparison(project_id, comparison_id)
    if comparison.engine_comparison_id is None or comparison.engine_comparison_sha256 is None:
        raise ConflictError("This saved comparison does not have an Engine snapshot")
    for reference in (comparison.left, comparison.right):
        await _require_project_investigation(
            project_id,
            reference.session_id,
            reference.investigation_id,
            projects,
            runtime,
        )
    engine_comparison = await engine.get_investigation_comparison(
        comparison.engine_comparison_sha256
    )
    if engine_comparison.comparison_id != comparison.engine_comparison_id:
        raise ConflictError(
            "The Engine comparison identity does not match the saved Project record"
        )
    return engine_comparison


@router.delete(
    "/{project_id}/comparisons/{comparison_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_investigation_comparison(
    project_id: str,
    comparison_id: str,
    projects: ProjectRepositoryDep,
) -> Response:
    await projects.delete_investigation_comparison(project_id, comparison_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/sessions",
    response_model=ProjectSessionLink,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_session(
    project_id: str,
    body: CreateProjectSession,
    projects: ProjectRepositoryDep,
) -> ProjectSessionLink:
    return await projects.create_session(
        project_id, Session(title=body.title)
    )


@router.post(
    "/{project_id}/sessions/link",
    response_model=ProjectSessionLink,
)
async def link_project_session(
    project_id: str,
    body: LinkProjectSession,
    projects: ProjectRepositoryDep,
) -> ProjectSessionLink:
    return await projects.link_session(project_id, body.session_id)


@router.post(
    "/{project_id}/notes",
    response_model=ProjectNote,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_note(
    project_id: str,
    body: ProjectNoteCreate,
    projects: ProjectRepositoryDep,
    runtime: AgentRuntimeDep,
) -> ProjectNote:
    if body.investigation_id is not None and body.investigation_session_id is not None:
        await _require_project_investigation(
            project_id,
            body.investigation_session_id,
            body.investigation_id,
            projects,
            runtime,
        )
    return await projects.create_note(
        project_id,
        ProjectNote(project_id=project_id, **body.model_dump()),
    )


@router.get("/{project_id}/notes", response_model=list[ProjectNote])
async def list_project_notes(
    project_id: str,
    projects: ProjectRepositoryDep,
    investigation_id: str | None = Query(default=None, min_length=1, max_length=128),
    investigation_session_id: str | None = Query(
        default=None, min_length=1, max_length=128
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectNote]:
    if (investigation_id is None) != (investigation_session_id is None):
        raise ValidationFailedError(
            "investigation_id and investigation_session_id must be provided together"
        )
    return await projects.list_notes(
        project_id,
        investigation_id=investigation_id,
        investigation_session_id=investigation_session_id,
        limit=limit,
        offset=offset,
    )


@router.patch("/{project_id}/notes/{note_id}", response_model=ProjectNote)
async def update_project_note(
    project_id: str,
    note_id: str,
    body: ProjectNoteUpdate,
    projects: ProjectRepositoryDep,
) -> ProjectNote:
    changes = body.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    if not changes:
        raise ValidationFailedError("At least one Project note field must be updated")
    if any(value is None for value in changes.values()):
        raise ValidationFailedError("Project note fields cannot be null")
    note = await projects.get_note(project_id, note_id)
    note = note.model_copy(update=changes)
    return await projects.update_note(note, expected_revision=body.expected_revision)


@router.delete(
    "/{project_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_note(
    project_id: str, note_id: str, projects: ProjectRepositoryDep
) -> Response:
    await projects.delete_note(project_id, note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/views",
    response_model=ProjectEarthView,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_earth_view(
    project_id: str,
    body: ProjectEarthViewCreate,
    projects: ProjectRepositoryDep,
    runtime: AgentRuntimeDep,
) -> ProjectEarthView:
    if body.investigation_id is not None:
        await _require_project_investigation(
            project_id,
            body.source_session_id,
            body.investigation_id,
            projects,
            runtime,
        )
    return await projects.create_view_from_bookmark(
        project_id,
        body.source_session_id,
        body.source_bookmark_id,
        body.title,
        body.investigation_id,
    )


@router.get("/{project_id}/views", response_model=list[ProjectEarthView])
async def list_project_earth_views(
    project_id: str,
    projects: ProjectRepositoryDep,
    investigation_id: str | None = Query(default=None, min_length=1, max_length=128),
    source_session_id: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectEarthView]:
    if (investigation_id is None) != (source_session_id is None):
        raise ValidationFailedError(
            "investigation_id and source_session_id must be provided together"
        )
    return await projects.list_views(
        project_id,
        investigation_id=investigation_id,
        source_session_id=source_session_id,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/{project_id}/views/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_earth_view(
    project_id: str, view_id: str, projects: ProjectRepositoryDep
) -> Response:
    await projects.delete_view(project_id, view_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
