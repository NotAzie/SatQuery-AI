import sqlite3

import pytest

from earth_platform.projects.models import (
    Project,
    ProjectInvestigationComparison,
    ProjectInvestigationRef,
    ProjectNote,
)
from earth_platform.projects.sqlite import SQLiteProjectRepository
from earth_platform.sessions.models import Session
from earth_platform.sessions.sqlite import SQLiteSessionStore
from earth_platform.shared.clock import utcnow
from earth_platform.shared.earth import (
    CameraState,
    EarthBookmark,
    EarthContext,
    EarthMeasurement,
    EarthWorkspaceState,
)
from earth_platform.shared.errors import ConflictError, NotFoundError
from earth_platform.shared.geo import LngLat


@pytest.mark.asyncio
async def test_investigation_comparison_is_persisted_and_journaled(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()
    project = await projects.create(Project(title="Comparison archive"))
    comparison = ProjectInvestigationComparison(
        project_id=project.id,
        title="Baseline and follow-up",
        left=ProjectInvestigationRef(
            investigation_id="investigation-1", session_id="session-1"
        ),
        right=ProjectInvestigationRef(
            investigation_id="investigation-2", session_id="session-2"
        ),
    )

    saved = await projects.create_investigation_comparison(project.id, comparison)
    await projects.aclose()
    await sessions.aclose()

    reopened_sessions = SQLiteSessionStore(database)
    reopened_projects = SQLiteProjectRepository(database)
    await reopened_sessions.open()
    await reopened_projects.open()
    assert await reopened_projects.get_investigation_comparison(project.id, saved.id) == saved
    assert await reopened_projects.list_investigation_comparisons(project.id) == [saved]
    activity = await reopened_projects.list_activity(project.id)
    assert any(item.action == "investigation_comparison.created" for item in activity)
    await reopened_projects.delete_investigation_comparison(project.id, saved.id)
    assert await reopened_projects.list_investigation_comparisons(project.id) == []
    activity = await reopened_projects.list_activity(project.id)
    assert any(item.action == "investigation_comparison.deleted" for item in activity)
    await reopened_projects.aclose()
    await reopened_sessions.aclose()


@pytest.mark.asyncio
async def test_projects_and_session_links_survive_reopen(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    project = await projects.create(Project(title="Coastal change"))
    link = await projects.create_session(project.id, Session(title="Baseline review"))
    await projects.aclose()
    await sessions.aclose()

    reopened_sessions = SQLiteSessionStore(database)
    reopened_projects = SQLiteProjectRepository(database)
    await reopened_sessions.open()
    await reopened_projects.open()
    saved = await reopened_projects.get(project.id)
    links = await reopened_projects.list_sessions(project.id)

    assert saved.title == "Coastal change"
    assert [item.session_id for item in links] == [link.session_id]
    assert links[0].session.title == "Baseline review"
    assert await reopened_projects.list_unlinked_sessions() == []
    await reopened_projects.aclose()
    await reopened_sessions.aclose()


@pytest.mark.asyncio
async def test_project_notes_are_investigation_scoped_and_legacy_schema_migrates(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE project_notes ("
        "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "revision INTEGER NOT NULL, data TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE project_views ("
        "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_session_id TEXT NOT NULL, "
        "created_at TEXT NOT NULL, data TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()

    projects = SQLiteProjectRepository(database)
    await projects.open()
    project = await projects.create(Project(title="Scoped notes"))
    project_note = await projects.create_note(
        project.id,
        ProjectNote(project_id=project.id, title="Project note", body="General context"),
    )
    first = await projects.create_note(
        project.id,
        ProjectNote(
            project_id=project.id,
            title="Investigation note",
            body="Review this source",
            investigation_id="investigation-1",
            investigation_session_id="session-1",
        ),
    )
    second = await projects.create_note(
        project.id,
        ProjectNote(
            project_id=project.id,
            title="Other investigation",
            body="Keep this separate",
            investigation_id="investigation-2",
            investigation_session_id="session-1",
        ),
    )

    scoped = await projects.list_notes(
        project.id,
        investigation_id="investigation-1",
        investigation_session_id="session-1",
    )
    assert [note.id for note in scoped] == [first.id]
    assert {note.id for note in await projects.list_notes(project.id)} == {
        project_note.id,
        first.id,
        second.id,
    }
    with pytest.raises(ValueError, match="provided together"):
        await projects.list_notes(project.id, investigation_id="investigation-1")

    await projects.aclose()
    reopened = SQLiteProjectRepository(database)
    await reopened.open()
    persisted = await reopened.list_notes(
        project.id,
        investigation_id="investigation-1",
        investigation_session_id="session-1",
    )
    assert [note.id for note in persisted] == [first.id]
    await reopened.aclose()
    connection = sqlite3.connect(database)
    note_columns = {row[1] for row in connection.execute("PRAGMA table_info(project_notes)")}
    view_columns = {row[1] for row in connection.execute("PRAGMA table_info(project_views)")}
    connection.close()
    assert {"investigation_id", "investigation_session_id"} <= note_columns
    assert "investigation_id" in view_columns


@pytest.mark.asyncio
async def test_existing_session_link_is_idempotent_and_single_project_owned(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    first = await projects.create(Project(title="First"))
    second = await projects.create(Project(title="Second"))
    session = await sessions.sessions.create(Session(title="Existing"))
    original = await projects.link_session(first.id, session.id)
    repeated = await projects.link_session(first.id, session.id)

    assert repeated.linked_at == original.linked_at
    with pytest.raises(ConflictError, match="already belongs"):
        await projects.link_session(second.id, session.id)
    with pytest.raises(NotFoundError):
        await projects.link_session(first.id, "missing-session")
    assert sum(
        item.action == "session.linked" for item in await projects.list_activity(first.id)
    ) == 1
    await projects.aclose()
    await sessions.aclose()


@pytest.mark.asyncio
async def test_archived_projects_reject_new_sessions_and_associations(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    project = await projects.create(Project(title="Archived"))
    archived = project.model_copy(update={"archived": True})
    await projects.update(archived, expected_revision=project.revision)
    standalone = await sessions.sessions.create(Session())

    with pytest.raises(ConflictError, match="archived"):
        await projects.create_session(project.id, Session())
    with pytest.raises(ConflictError, match="archived"):
        await projects.link_session(project.id, standalone.id)
    assert await projects.list_unlinked_sessions() == [standalone]
    await projects.aclose()
    await sessions.aclose()


@pytest.mark.asyncio
async def test_project_revision_conflict_and_session_delete_cascade(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    project = await projects.create(Project(title="Study"))
    link = await projects.create_session(project.id, Session())
    current = await projects.get(project.id)
    await projects.update(
        current.model_copy(update={"title": "Revised"}),
        expected_revision=current.revision,
    )
    with pytest.raises(ConflictError, match="revision changed"):
        await projects.update(
            current.model_copy(update={"title": "Stale"}),
            expected_revision=current.revision,
        )

    await sessions.sessions.delete(link.session_id)
    assert await projects.list_sessions(project.id) == []
    with pytest.raises(NotFoundError):
        await sessions.sessions.get(link.session_id)
    await projects.aclose()
    await sessions.aclose()


@pytest.mark.asyncio
async def test_project_list_is_ordered_and_archived_projects_are_opt_in(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    older = await projects.create(Project(title="Older"))
    newer = await projects.create(Project(title="Newer"))
    await projects.update(
        older.model_copy(update={"archived": True}),
        expected_revision=older.revision,
    )

    assert [item.id for item in await projects.list_projects()] == [newer.id]
    assert {item.id for item in await projects.list_projects(include_archived=True)} == {
        older.id,
        newer.id,
    }
    await projects.aclose()
    await sessions.aclose()


@pytest.mark.asyncio
async def test_project_notes_support_revisions_pagination_and_delete(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    project = await projects.create(Project(title="Field notes"))
    first = await projects.create_note(
        project.id, ProjectNote(project_id=project.id, title="Initial", body="Observed change")
    )
    await projects.create_note(
        project.id, ProjectNote(project_id=project.id, title="Follow-up", body="Check imagery")
    )
    revised = await projects.update_note(
        first.model_copy(update={"title": "Revised"}),
        expected_revision=first.revision,
    )

    assert revised.revision == 2
    assert (await projects.get_note(project.id, first.id)).title == "Revised"
    assert [note.id for note in await projects.list_notes(project.id, limit=1)] == [
        first.id
    ]
    with pytest.raises(ConflictError, match="revision changed"):
        await projects.update_note(
            first.model_copy(update={"title": "Stale"}),
            expected_revision=first.revision,
        )

    await projects.delete_note(project.id, first.id)
    with pytest.raises(NotFoundError):
        await projects.get_note(project.id, first.id)
    activity = await projects.list_activity(project.id)
    assert {item.action for item in activity} >= {
        "project.created",
        "note.created",
        "note.updated",
        "note.deleted",
    }
    assert sum(item.action == "note.created" for item in activity) == 2
    await projects.aclose()
    await sessions.aclose()


@pytest.mark.asyncio
async def test_project_earth_view_is_a_durable_bookmark_snapshot(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    project = await projects.create(Project(title="Coastal imagery"))
    timestamp = utcnow()
    context = EarthContext(
        camera=CameraState(position=LngLat(lat=12.5, lng=34.5), height_m=2400),
        measurement=EarthMeasurement(
            kind="distance",
            value=1250,
            unit="m",
            position=LngLat(lat=12.5, lng=34.5),
        ),
    )
    bookmark = EarthBookmark(
        id="bookmark-baseline",
        name="Baseline shoreline",
        context=context,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = Session(
        title="Shoreline survey",
        earth_workspace=EarthWorkspaceState(bookmarks=[bookmark]),
    )
    link = await projects.create_session(project.id, session)
    view = await projects.create_view_from_bookmark(
        project.id, session.id, bookmark.id, "Baseline"
    )

    assert view.context == context
    await sessions.sessions.delete(session.id)
    await projects.aclose()
    await sessions.aclose()

    reopened_sessions = SQLiteSessionStore(database)
    reopened_projects = SQLiteProjectRepository(database)
    await reopened_sessions.open()
    await reopened_projects.open()
    saved_views = await reopened_projects.list_views(project.id)
    assert len(saved_views) == 1
    assert saved_views[0].id == view.id
    assert saved_views[0].source_session_id == link.session_id
    assert saved_views[0].source_session_exists is False
    assert saved_views[0].context == context
    activity = await reopened_projects.list_activity(project.id)
    assert any(item.action == "earth_view.saved" for item in activity)
    assert sum(item.action == "session.linked" for item in activity) == 1
    await reopened_projects.aclose()
    await reopened_sessions.aclose()


@pytest.mark.asyncio
async def test_project_notes_and_views_reject_archived_projects_and_unowned_bookmarks(
    tmp_path,
):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    project = await projects.create(Project(title="Archive"))
    other_project = await projects.create(Project(title="Other"))
    timestamp = utcnow()
    bookmark = EarthBookmark(
        id="bookmark",
        name="Saved place",
        context=EarthContext(
            camera=CameraState(position=LngLat(lat=0, lng=0), height_m=1000)
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = Session(earth_workspace=EarthWorkspaceState(bookmarks=[bookmark]))
    await projects.create_session(other_project.id, session)
    with pytest.raises(NotFoundError, match="not linked"):
        await projects.create_view_from_bookmark(
            project.id, session.id, bookmark.id, bookmark.name
        )

    await projects.update(
        project.model_copy(update={"archived": True}),
        expected_revision=project.revision,
    )
    with pytest.raises(ConflictError, match="archived"):
        await projects.create_note(
            project.id, ProjectNote(project_id=project.id, title="Note", body="Body")
        )
    with pytest.raises(ConflictError, match="archived"):
        await projects.create_view_from_bookmark(
            project.id, session.id, bookmark.id, bookmark.name
        )
    await projects.aclose()
    await sessions.aclose()


@pytest.mark.asyncio
async def test_project_monitoring_links_are_idempotent_and_keep_engine_ownership(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()

    project = await projects.create(Project(title="Recurring observation"))
    other_project = await projects.create(Project(title="Related study"))
    first = await projects.link_monitoring_schedule(project.id, "schedule-1", "mission-1")
    repeated = await projects.link_monitoring_schedule(project.id, "schedule-1", "mission-1")
    shared = await projects.link_monitoring_schedule(
        other_project.id, "schedule-1", "mission-1"
    )

    assert repeated.linked_at == first.linked_at
    assert shared.project_id == other_project.id
    assert await projects.list_monitoring_links(project.id) == [first]
    with pytest.raises(ConflictError, match="different Engine mission"):
        await projects.link_monitoring_schedule(project.id, "schedule-1", "mission-2")

    await projects.unlink_monitoring_schedule(project.id, "schedule-1")
    assert await projects.list_monitoring_links(project.id) == []
    with pytest.raises(NotFoundError):
        await projects.unlink_monitoring_schedule(project.id, "schedule-1")
    actions = [item.action for item in await projects.list_activity(project.id)]
    assert actions.count("monitoring.linked") == 1
    assert actions.count("monitoring.unlinked") == 1

    archived = await projects.get(project.id)
    await projects.update(
        archived.model_copy(update={"archived": True}),
        expected_revision=archived.revision,
    )
    with pytest.raises(ConflictError, match="archived"):
        await projects.link_monitoring_schedule(project.id, "schedule-2", "mission-1")
    await projects.aclose()
    await sessions.aclose()

    reopened_sessions = SQLiteSessionStore(database)
    reopened_projects = SQLiteProjectRepository(database)
    await reopened_sessions.open()
    await reopened_projects.open()
    assert await reopened_projects.list_monitoring_links(other_project.id) == [shared]
    await reopened_projects.aclose()
    await reopened_sessions.aclose()
