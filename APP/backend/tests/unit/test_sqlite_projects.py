import json
import sqlite3

import pytest

from earth_platform.projects.models import (
    Project,
    ProjectInvestigationCollection,
    ProjectInvestigationCollectionMemberUpdate,
    ProjectInvestigationComparison,
    ProjectInvestigationRef,
    ProjectInvestigationRelationship,
    ProjectInvestigationTemplate,
    ProjectInvestigationTemplateRunUpdate,
    ProjectInvestigationTemplateStep,
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
async def test_investigation_relationship_persists_and_journals_transactionally(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()
    project = await projects.create(Project(title="Relationship archive"))
    relationship = ProjectInvestigationRelationship(
        project_id=project.id,
        from_investigation=ProjectInvestigationRef(
            investigation_id="investigation-1",
            session_id="session-1",
        ),
        to_investigation=ProjectInvestigationRef(
            investigation_id="investigation-2",
            session_id="session-2",
        ),
        relationship_type="follow_up_to",
        rationale="The second investigation revisits the same location one season later.",
    )

    saved = await projects.create_investigation_relationship(project.id, relationship)
    with pytest.raises(ConflictError, match="already exists"):
        await projects.create_investigation_relationship(project.id, relationship)
    await projects.aclose()
    await sessions.aclose()
    with sqlite3.connect(database) as legacy_db:
        rows = legacy_db.execute(
            "SELECT id, data FROM project_activity"
        ).fetchall()
        for activity_id, payload in rows:
            data = json.loads(payload)
            if data["action"] == "investigation_relationship.created":
                data.pop("investigations", None)
                legacy_db.execute(
                    "UPDATE project_activity SET data = ? WHERE id = ?",
                    (json.dumps(data), activity_id),
                )
        legacy_db.execute("DELETE FROM project_activity_investigations")
        legacy_db.execute(
            "DELETE FROM project_migrations WHERE name = ?",
            ("investigation_activity_provenance_v1",),
        )

    reopened = SQLiteProjectRepository(database)
    await reopened.open()
    assert await reopened.list_investigation_relationships(project.id) == [saved]
    activity = await reopened.list_activity(project.id)
    created_activity = [
        item for item in activity if item.action == "investigation_relationship.created"
    ]
    assert len(created_activity) == 1
    assert created_activity[0].investigations == [
        relationship.from_investigation,
        relationship.to_investigation,
    ]
    filtered_activity = await reopened.list_activity(
        project.id,
        investigation=relationship.to_investigation,
    )
    assert [item.action for item in filtered_activity] == [
        "investigation_relationship.created"
    ]
    await reopened.delete_investigation_relationship(project.id, saved.id)
    assert await reopened.list_investigation_relationships(project.id) == []
    activity = await reopened.list_activity(project.id)
    assert any(item.action == "investigation_relationship.deleted" for item in activity)
    filtered_activity = await reopened.list_activity(
        project.id,
        investigation=relationship.to_investigation,
    )
    assert {item.action for item in filtered_activity} == {
        "investigation_relationship.created",
        "investigation_relationship.deleted",
    }
    with pytest.raises(NotFoundError):
        await reopened.delete_investigation_relationship(project.id, saved.id)
    await reopened.aclose()


@pytest.mark.asyncio
async def test_investigation_collection_is_revisioned_persisted_and_journaled(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()
    project = await projects.create(Project(title="Campaign archive"))
    collection = await projects.create_investigation_collection(
        ProjectInvestigationCollection(
            project_id=project.id,
            title="Coastal change campaign",
            description="Researcher-curated investigations across seasons.",
        )
    )
    first_reference = ProjectInvestigationRef(
        session_id="session-1",
        investigation_id="investigation-1",
    )
    first_update = ProjectInvestigationCollectionMemberUpdate(
        expected_revision=collection.revision,
        operation="add",
        investigation=first_reference,
    )
    collection = await projects.update_investigation_collection_members(
        project.id, collection.id, first_update
    )
    assert collection.revision == 2
    assert collection.investigations == [first_reference]
    with pytest.raises(ConflictError, match="already in this collection"):
        await projects.update_investigation_collection_members(
            project.id, collection.id, first_update.model_copy(
                update={"expected_revision": collection.revision}
            )
        )
    with pytest.raises(ConflictError, match="changed by another request"):
        await projects.update_investigation_collection_members(
            project.id, collection.id, first_update
        )

    updated = collection.model_copy(
        update={"title": "Coastal change campaign 2026", "updated_at": utcnow()}
    )
    collection = await projects.update_investigation_collection(
        updated,
        expected_revision=collection.revision,
    )
    assert collection.title.endswith("2026")
    assert collection.revision == 3
    second_reference = ProjectInvestigationRef(
        session_id="session-2",
        investigation_id="investigation-2",
    )
    collection = await projects.update_investigation_collection_members(
        project.id,
        collection.id,
        ProjectInvestigationCollectionMemberUpdate(
            expected_revision=collection.revision,
            operation="add",
            investigation=second_reference,
        ),
    )
    await projects.aclose()
    await sessions.aclose()

    reopened = SQLiteProjectRepository(database)
    await reopened.open()
    assert await reopened.get_investigation_collection(project.id, collection.id) == collection
    assert await reopened.list_investigation_collections(project.id) == [collection]
    filtered_activity = await reopened.list_activity(
        project.id,
        investigation=first_reference,
    )
    assert {
        item.action for item in filtered_activity
    } == {
        "investigation_collection.member_added",
        "investigation_collection.updated",
    }

    removed = await reopened.update_investigation_collection_members(
        project.id,
        collection.id,
        ProjectInvestigationCollectionMemberUpdate(
            expected_revision=collection.revision,
            operation="remove",
            investigation=first_reference,
        ),
    )
    assert removed.investigations == [second_reference]
    await reopened.delete_investigation_collection(project.id, collection.id)
    assert await reopened.list_investigation_collections(project.id) == []
    with pytest.raises(NotFoundError):
        await reopened.get_investigation_collection(project.id, collection.id)
    deleted_events = [
        item
        for item in await reopened.list_activity(project.id)
        if item.action == "investigation_collection.deleted"
    ]
    assert len(deleted_events) == 1
    assert deleted_events[0].investigations == [second_reference]
    await reopened.aclose()


@pytest.mark.asyncio
async def test_investigation_template_reuse_persists_snapshots_and_revision_checks(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()
    project = await projects.create(Project(title="Campaign"))
    template = ProjectInvestigationTemplate(
        project_id=project.id,
        title="Seasonal shoreline review",
        description="Researcher-authored workflow",
        steps=[
            ProjectInvestigationTemplateStep(title="Record observation window"),
            ProjectInvestigationTemplateStep(title="Review existing evidence"),
        ],
    )
    saved = await projects.create_investigation_template(template)
    assert await projects.list_investigation_templates(project.id) == [saved]
    first_run = await projects.apply_investigation_template(project.id, saved.id)
    second_run = await projects.apply_investigation_template(project.id, saved.id)
    assert first_run.session_id != second_run.session_id
    assert first_run.steps == second_run.steps
    assert first_run.template_revision == saved.revision == 1
    revised_template = await projects.update_investigation_template(
        saved.model_copy(
            update={
                "title": "Seasonal shoreline review v2",
                "steps": [
                    ProjectInvestigationTemplateStep(title="Confirm the study area"),
                    ProjectInvestigationTemplateStep(title="Record the observation window"),
                ],
                "updated_at": utcnow(),
            }
        ),
        expected_revision=saved.revision,
    )
    assert revised_template.revision == 2
    with pytest.raises(ConflictError, match="changed by another request"):
        await projects.update_investigation_template(
            saved.model_copy(update={"title": "Stale edit"}),
            expected_revision=saved.revision,
        )
    third_run = await projects.apply_investigation_template(project.id, saved.id)
    assert third_run.template_revision == revised_template.revision
    assert third_run.template_title == revised_template.title
    assert third_run.steps != first_run.steps
    assert len(await projects.list_sessions(project.id)) == 3
    await projects.aclose()
    await sessions.aclose()
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()
    assert await projects.list_investigation_templates(project.id) == [revised_template]
    assert {run.id for run in await projects.list_investigation_template_runs(project.id)} == {
        first_run.id,
        second_run.id,
        third_run.id,
    }
    updated = await projects.update_investigation_template_run(
        project.id,
        first_run.id,
        ProjectInvestigationTemplateRunUpdate(
            expected_revision=first_run.revision,
            completed_step_ids=[first_run.steps[0].id],
        ),
    )
    assert updated.revision == first_run.revision + 1
    assert updated.steps[0].completed is True
    assert updated.steps[1].completed is False
    with pytest.raises(ConflictError, match="revision changed"):
        await projects.update_investigation_template_run(
            project.id,
            first_run.id,
            ProjectInvestigationTemplateRunUpdate(
                expected_revision=first_run.revision,
                completed_step_ids=[],
            ),
        )
    await projects.delete_investigation_template(project.id, saved.id)
    assert await projects.list_investigation_templates(project.id) == []
    await sessions.sessions.delete(first_run.session_id)
    retained_runs = await projects.list_investigation_template_runs(project.id)
    assert {run.id: run for run in retained_runs} == {
        updated.id: updated,
        second_run.id: second_run,
        third_run.id: third_run,
    }
    activity = await projects.list_activity(project.id)
    assert {
        event.action
        for event in activity
        if event.action.startswith("investigation_template")
    } == {
        "investigation_template.created",
        "investigation_template.updated",
        "investigation_template.applied",
        "investigation_template_run.updated",
        "investigation_template.deleted",
    }
    await projects.aclose()
    await sessions.aclose()


@pytest.mark.asyncio
async def test_legacy_template_records_default_to_revision_one(tmp_path):
    database = str(tmp_path / "platform.sqlite3")
    sessions = SQLiteSessionStore(database)
    projects = SQLiteProjectRepository(database)
    await sessions.open()
    await projects.open()
    project = await projects.create(Project(title="Legacy workflows"))
    template = await projects.create_investigation_template(
        ProjectInvestigationTemplate(
            project_id=project.id,
            title="Existing workflow",
            steps=[ProjectInvestigationTemplateStep(title="Review the evidence")],
        )
    )
    run = await projects.apply_investigation_template(project.id, template.id)
    await projects.aclose()
    await sessions.aclose()

    with sqlite3.connect(database) as legacy_db:
        template_row = legacy_db.execute(
            "SELECT data FROM project_investigation_templates WHERE id = ?",
            (template.id,),
        ).fetchone()
        template_data = json.loads(template_row[0])
        template_data.pop("revision")
        legacy_db.execute(
            "UPDATE project_investigation_templates SET data = ? WHERE id = ?",
            (json.dumps(template_data), template.id),
        )
        run_row = legacy_db.execute(
            "SELECT data FROM project_investigation_template_runs WHERE id = ?",
            (run.id,),
        ).fetchone()
        run_data = json.loads(run_row[0])
        run_data.pop("template_revision")
        legacy_db.execute(
            "UPDATE project_investigation_template_runs SET data = ? WHERE id = ?",
            (json.dumps(run_data), run.id),
        )

    reopened = SQLiteProjectRepository(database)
    await reopened.open()
    loaded_template = await reopened.get_investigation_template(project.id, template.id)
    loaded_run = (await reopened.list_investigation_template_runs(project.id))[0]
    assert loaded_template.revision == 1
    assert loaded_run.template_revision == 1
    revised = await reopened.update_investigation_template(
        loaded_template.model_copy(update={"title": "Revised workflow"}),
        expected_revision=loaded_template.revision,
    )
    assert revised.revision == 2
    await reopened.aclose()


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
