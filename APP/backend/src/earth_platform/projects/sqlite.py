"""SQLite persistence for Platform Projects and their session associations."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import aiosqlite

from earth_platform.projects.models import (
    Project,
    ProjectActivity,
    ProjectActivityAction,
    ProjectEarthView,
    ProjectInvestigationComparison,
    ProjectMonitoringLink,
    ProjectNote,
    ProjectSessionLink,
)
from earth_platform.sessions.models import Session
from earth_platform.shared.clock import utcnow
from earth_platform.shared.errors import ConflictError, NotFoundError


def _ensure_parent_directory(dsn: str) -> None:
    Path(dsn).resolve().parent.mkdir(parents=True, exist_ok=True)


async def _record_activity(
    db: aiosqlite.Connection,
    *,
    project_id: str,
    action: ProjectActivityAction,
    subject_id: str | None = None,
    session_id: str | None = None,
    label: str | None = None,
    occurred_at: datetime | None = None,
) -> None:
    activity = ProjectActivity(
        project_id=project_id,
        action=action,
        subject_id=subject_id,
        session_id=session_id,
        label=label,
        occurred_at=occurred_at or utcnow(),
    )
    await db.execute(
        "INSERT INTO project_activity(id, project_id, occurred_at, data) "
        "VALUES (?, ?, ?, ?)",
        (
            activity.id,
            project_id,
            activity.occurred_at.isoformat(),
            activity.model_dump_json(),
        ),
    )


class SQLiteProjectRepository:
    """Transactional Project store sharing the Platform session database."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn if dsn == ":memory:" else str(Path(dsn).expanduser())
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        if self._db is not None:
            return
        if self._dsn != ":memory:":
            await asyncio.to_thread(_ensure_parent_directory, self._dsn)
        self._db = await aiosqlite.connect(self._dsn)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                archived INTEGER NOT NULL,
                revision INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_sessions (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
                linked_at TEXT NOT NULL,
                PRIMARY KEY (project_id, session_id)
            );
            CREATE INDEX IF NOT EXISTS project_sessions_by_project
                ON project_sessions(project_id, linked_at, session_id);
            CREATE TABLE IF NOT EXISTS project_notes (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                investigation_id TEXT,
                investigation_session_id TEXT,
                updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS project_notes_by_project
                ON project_notes(project_id, updated_at DESC, id);
            CREATE TABLE IF NOT EXISTS project_views (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                source_session_id TEXT NOT NULL,
                investigation_id TEXT,
                created_at TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS project_views_by_project
                ON project_views(project_id, created_at DESC, id);
            CREATE TABLE IF NOT EXISTS project_activity (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                occurred_at TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_investigation_comparisons (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS project_investigation_comparisons_by_project
                ON project_investigation_comparisons(project_id, created_at DESC, id);
            CREATE INDEX IF NOT EXISTS project_activity_by_project
                ON project_activity(project_id, occurred_at DESC, id);
            CREATE TABLE IF NOT EXISTS project_monitoring_links (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                schedule_id TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                linked_at TEXT NOT NULL,
                PRIMARY KEY (project_id, schedule_id)
            );
            CREATE INDEX IF NOT EXISTS project_monitoring_links_by_project
                ON project_monitoring_links(project_id, linked_at DESC, schedule_id);
            """
        )
        note_columns = await self._db.execute("PRAGMA table_info(project_notes)")
        existing_note_columns = {row["name"] for row in await note_columns.fetchall()}
        if "investigation_id" not in existing_note_columns:
            await self._db.execute("ALTER TABLE project_notes ADD COLUMN investigation_id TEXT")
        if "investigation_session_id" not in existing_note_columns:
            await self._db.execute(
                "ALTER TABLE project_notes ADD COLUMN investigation_session_id TEXT"
            )
        view_columns = await self._db.execute("PRAGMA table_info(project_views)")
        existing_view_columns = {row["name"] for row in await view_columns.fetchall()}
        if "investigation_id" not in existing_view_columns:
            await self._db.execute(
                "ALTER TABLE project_views ADD COLUMN investigation_id TEXT"
            )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS project_notes_by_investigation "
            "ON project_notes(project_id, investigation_session_id, investigation_id, "
            "updated_at DESC, id)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS project_views_by_investigation "
            "ON project_views(project_id, source_session_id, investigation_id, created_at DESC, id)"
        )
        await self._db.commit()

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteProjectRepository.open() must be called before use")
        return self._db

    async def create(self, project: Project) -> Project:
        async with self._lock:
            db = self._connection()
            try:
                await db.execute(
                    "INSERT INTO projects(id, updated_at, archived, revision, data) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        project.id,
                        project.updated_at.isoformat(),
                        int(project.archived),
                        project.revision,
                        project.model_dump_json(),
                    ),
                )
                await _record_activity(
                    db,
                    project_id=project.id,
                    action="project.created",
                    subject_id=project.id,
                    label=project.title,
                    occurred_at=project.created_at,
                )
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                raise ConflictError(f"Project '{project.id}' already exists") from exc
            except BaseException:
                await db.rollback()
                raise
        return project

    async def get(self, project_id: str) -> Project:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT data FROM projects WHERE id = ?", (project_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"Project '{project_id}' was not found")
        return Project.model_validate_json(row["data"])

    async def list_projects(
        self, *, include_archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Project]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("limit must be between 1 and 500 and offset must be non-negative")
        query = "SELECT data FROM projects"
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY updated_at DESC, id LIMIT ? OFFSET ?"
        async with self._lock:
            cursor = await self._connection().execute(query, (limit, offset))
            rows = await cursor.fetchall()
        return [Project.model_validate_json(row["data"]) for row in rows]

    async def update(self, project: Project, *, expected_revision: int) -> Project:
        updated = project.model_copy(
            update={"revision": expected_revision + 1, "updated_at": utcnow()}
        )
        async with self._lock:
            db = self._connection()
            try:
                await db.execute("BEGIN IMMEDIATE")
                current = await db.execute(
                    "SELECT revision, data FROM projects WHERE id = ?", (project.id,)
                )
                row = await current.fetchone()
                if row is None:
                    raise NotFoundError(f"Project '{project.id}' was not found")
                if row["revision"] != expected_revision:
                    raise ConflictError(
                        f"Project '{project.id}' revision changed from "
                        f"{expected_revision} to {row['revision']}"
                    )
                previous = Project.model_validate_json(row["data"])
                cursor = await db.execute(
                    "UPDATE projects SET updated_at = ?, archived = ?, revision = ?, data = ? "
                    "WHERE id = ? AND revision = ?",
                    (
                        updated.updated_at.isoformat(),
                        int(updated.archived),
                        updated.revision,
                        updated.model_dump_json(),
                        updated.id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ConflictError(
                        f"Project '{project.id}' revision changed from "
                        f"{expected_revision}"
                    )
                action: ProjectActivityAction = "project.updated"
                if updated.archived != previous.archived:
                    action = "project.archived" if updated.archived else "project.unarchived"
                await _record_activity(
                    db,
                    project_id=updated.id,
                    action=action,
                    subject_id=updated.id,
                    label=updated.title,
                    occurred_at=updated.updated_at,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return updated

    async def create_session(self, project_id: str, session: Session) -> ProjectSessionLink:
        db = self._connection()
        linked_at = utcnow()
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                project = await db.execute(
                    "SELECT archived FROM projects WHERE id = ?", (project_id,)
                )
                project_row = await project.fetchone()
                if project_row is None:
                    raise NotFoundError(f"Project '{project_id}' was not found")
                if project_row["archived"]:
                    raise ConflictError("Cannot create a session in an archived Project")
                await db.execute(
                    "INSERT INTO sessions(id, updated_at, archived, data) VALUES (?, ?, ?, ?)",
                    (
                        session.id,
                        session.updated_at.isoformat(),
                        int(session.archived),
                        session.model_dump_json(),
                    ),
                )
                await db.execute(
                    "INSERT INTO project_sessions(project_id, session_id, linked_at) "
                    "VALUES (?, ?, ?)",
                    (project_id, session.id, linked_at.isoformat()),
                )
                await _record_activity(
                    db,
                    project_id=project_id,
                    action="session.linked",
                    subject_id=session.id,
                    session_id=session.id,
                    label=session.title or "Untitled session",
                    occurred_at=linked_at,
                )
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                raise ConflictError(
                    f"Session '{session.id}' already exists or is linked to a Project"
                ) from exc
            except BaseException:
                await db.rollback()
                raise
        return ProjectSessionLink(
            project_id=project_id,
            session_id=session.id,
            linked_at=linked_at,
            session=session,
        )

    async def link_session(
        self, project_id: str, session_id: str
    ) -> ProjectSessionLink:
        db = self._connection()
        linked_at = utcnow()
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                project_cursor = await db.execute(
                    "SELECT archived FROM projects WHERE id = ?", (project_id,)
                )
                project = await project_cursor.fetchone()
                if project is None:
                    raise NotFoundError(f"Project '{project_id}' was not found")
                if project["archived"]:
                    raise ConflictError("Cannot add a session to an archived Project")
                session_cursor = await db.execute(
                    "SELECT data FROM sessions WHERE id = ?", (session_id,)
                )
                session_row = await session_cursor.fetchone()
                if session_row is None:
                    raise NotFoundError(f"Session '{session_id}' was not found")
                existing_cursor = await db.execute(
                    "SELECT project_id, linked_at FROM project_sessions WHERE session_id = ?",
                    (session_id,),
                )
                existing = await existing_cursor.fetchone()
                if existing is not None:
                    if existing["project_id"] != project_id:
                        raise ConflictError(
                            f"Session '{session_id}' already belongs to another Project"
                        )
                    linked_at = datetime.fromisoformat(existing["linked_at"])
                else:
                    await db.execute(
                        "INSERT INTO project_sessions(project_id, session_id, linked_at) "
                        "VALUES (?, ?, ?)",
                        (project_id, session_id, linked_at.isoformat()),
                    )
                    session = Session.model_validate_json(session_row["data"])
                    await _record_activity(
                        db,
                        project_id=project_id,
                        action="session.linked",
                        subject_id=session_id,
                        session_id=session_id,
                        label=session.title or "Untitled session",
                        occurred_at=linked_at,
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        session = Session.model_validate_json(session_row["data"])
        return ProjectSessionLink(
            project_id=project_id,
            session_id=session_id,
            linked_at=linked_at,
            session=session,
        )

    async def list_sessions(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectSessionLink]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("limit must be between 1 and 500 and offset must be non-negative")
        async with self._lock:
            project = await self._connection().execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            )
            if await project.fetchone() is None:
                raise NotFoundError(f"Project '{project_id}' was not found")
            cursor = await self._connection().execute(
                "SELECT ps.project_id, ps.session_id, ps.linked_at, s.data "
                "FROM project_sessions ps JOIN sessions s ON s.id = ps.session_id "
                "WHERE ps.project_id = ? ORDER BY ps.linked_at DESC, ps.session_id "
                "LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            )
            rows = await cursor.fetchall()
        return [
            ProjectSessionLink(
                project_id=row["project_id"],
                session_id=row["session_id"],
                linked_at=row["linked_at"],
                session=Session.model_validate_json(row["data"]),
            )
            for row in rows
        ]

    async def get_session_link(
        self, project_id: str, session_id: str
    ) -> ProjectSessionLink:
        async with self._lock:
            db = self._connection()
            project_cursor = await db.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            )
            if await project_cursor.fetchone() is None:
                raise NotFoundError(f"Project '{project_id}' was not found")
            cursor = await db.execute(
                "SELECT ps.project_id, ps.session_id, ps.linked_at, s.data "
                "FROM project_sessions ps JOIN sessions s ON s.id = ps.session_id "
                "WHERE ps.project_id = ? AND ps.session_id = ?",
                (project_id, session_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(
                f"Session '{session_id}' is not linked to Project '{project_id}'"
            )
        return ProjectSessionLink(
            project_id=row["project_id"],
            session_id=row["session_id"],
            linked_at=row["linked_at"],
            session=Session.model_validate_json(row["data"]),
        )

    async def list_unlinked_sessions(self, *, limit: int = 50) -> list[Session]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT s.data FROM sessions s "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM project_sessions ps WHERE ps.session_id = s.id"
                ") AND s.archived = 0 ORDER BY s.updated_at DESC, s.id LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        return [Session.model_validate_json(row["data"]) for row in rows]

    async def create_investigation_comparison(
        self, project_id: str, comparison: ProjectInvestigationComparison
    ) -> ProjectInvestigationComparison:
        if comparison.project_id != project_id:
            raise ValueError("comparison project_id must match the requested Project")
        async with self._lock:
            db = self._connection()
            try:
                await db.execute("BEGIN IMMEDIATE")
                project_cursor = await db.execute(
                    "SELECT archived FROM projects WHERE id = ?", (project_id,)
                )
                project = await project_cursor.fetchone()
                if project is None:
                    raise NotFoundError(f"Project '{project_id}' was not found")
                if project["archived"]:
                    raise ConflictError("Cannot create a comparison in an archived Project")
                await db.execute(
                    "INSERT INTO project_investigation_comparisons"
                    "(id, project_id, created_at, data) VALUES (?, ?, ?, ?)",
                    (
                        comparison.id,
                        project_id,
                        comparison.created_at.isoformat(),
                        comparison.model_dump_json(),
                    ),
                )
                await _record_activity(
                    db,
                    project_id=project_id,
                    action="investigation_comparison.created",
                    subject_id=comparison.id,
                    label=comparison.title,
                    occurred_at=comparison.created_at,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return comparison

    async def get_investigation_comparison(
        self, project_id: str, comparison_id: str
    ) -> ProjectInvestigationComparison:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT data FROM project_investigation_comparisons "
                "WHERE project_id = ? AND id = ?",
                (project_id, comparison_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(
                f"Project investigation comparison '{comparison_id}' was not found"
            )
        return ProjectInvestigationComparison.model_validate_json(row["data"])

    async def list_investigation_comparisons(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectInvestigationComparison]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("limit must be between 1 and 500 and offset must be non-negative")
        async with self._lock:
            db = self._connection()
            project = await db.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
            if await project.fetchone() is None:
                raise NotFoundError(f"Project '{project_id}' was not found")
            cursor = await db.execute(
                "SELECT data FROM project_investigation_comparisons "
                "WHERE project_id = ? ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            )
            rows = await cursor.fetchall()
        return [
            ProjectInvestigationComparison.model_validate_json(row["data"]) for row in rows
        ]

    async def delete_investigation_comparison(
        self, project_id: str, comparison_id: str
    ) -> None:
        async with self._lock:
            db = self._connection()
            try:
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    "SELECT data FROM project_investigation_comparisons "
                    "WHERE project_id = ? AND id = ?",
                    (project_id, comparison_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise NotFoundError(
                        f"Project investigation comparison '{comparison_id}' was not found"
                    )
                comparison = ProjectInvestigationComparison.model_validate_json(row["data"])
                await db.execute(
                    "DELETE FROM project_investigation_comparisons "
                    "WHERE project_id = ? AND id = ?",
                    (project_id, comparison_id),
                )
                await _record_activity(
                    db,
                    project_id=project_id,
                    action="investigation_comparison.deleted",
                    subject_id=comparison_id,
                    label=comparison.title,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def create_note(self, project_id: str, note: ProjectNote) -> ProjectNote:
        db = self._connection()
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                project = await db.execute(
                    "SELECT archived FROM projects WHERE id = ?", (project_id,)
                )
                row = await project.fetchone()
                if row is None:
                    raise NotFoundError(f"Project '{project_id}' was not found")
                if row["archived"]:
                    raise ConflictError("Cannot add a note to an archived Project")
                if note.project_id != project_id:
                    raise ValueError("note project_id does not match the target Project")
                await db.execute(
                    "INSERT INTO project_notes(id, project_id, investigation_id, "
                    "investigation_session_id, updated_at, revision, data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        note.id,
                        project_id,
                        note.investigation_id,
                        note.investigation_session_id,
                        note.updated_at.isoformat(),
                        note.revision,
                        note.model_dump_json(),
                    ),
                )
                await _record_activity(
                    db,
                    project_id=project_id,
                    action="note.created",
                    subject_id=note.id,
                    label=note.title,
                    occurred_at=note.created_at,
                )
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                raise ConflictError(f"Project note '{note.id}' already exists") from exc
            except BaseException:
                await db.rollback()
                raise
        return note

    async def list_notes(
        self,
        project_id: str,
        *,
        investigation_id: str | None = None,
        investigation_session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectNote]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("limit must be between 1 and 500 and offset must be non-negative")
        if (investigation_id is None) != (investigation_session_id is None):
            raise ValueError(
                "investigation_id and investigation_session_id must be provided together"
            )
        async with self._lock:
            db = self._connection()
            project = await db.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
            if await project.fetchone() is None:
                raise NotFoundError(f"Project '{project_id}' was not found")
            filters = ""
            parameters: tuple[str | int, ...] = (project_id,)
            if investigation_id is not None and investigation_session_id is not None:
                filters = " AND investigation_id = ? AND investigation_session_id = ?"
                parameters += (investigation_id, investigation_session_id)
            cursor = await db.execute(
                "SELECT data FROM project_notes WHERE project_id = ?"
                + filters
                + " ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            )
            rows = await cursor.fetchall()
        return [ProjectNote.model_validate_json(row["data"]) for row in rows]

    async def get_note(self, project_id: str, note_id: str) -> ProjectNote:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT data FROM project_notes WHERE id = ? AND project_id = ?",
                (note_id, project_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"Project note '{note_id}' was not found")
        return ProjectNote.model_validate_json(row["data"])

    async def update_note(
        self, note: ProjectNote, *, expected_revision: int
    ) -> ProjectNote:
        updated = note.model_copy(
            update={"revision": expected_revision + 1, "updated_at": utcnow()}
        )
        async with self._lock:
            db = self._connection()
            try:
                await db.execute("BEGIN IMMEDIATE")
                current = await db.execute(
                    "SELECT revision FROM project_notes WHERE id = ? AND project_id = ?",
                    (note.id, note.project_id),
                )
                row = await current.fetchone()
                if row is None:
                    raise NotFoundError(f"Project note '{note.id}' was not found")
                if row["revision"] != expected_revision:
                    raise ConflictError(
                        f"Project note '{note.id}' revision changed from "
                        f"{expected_revision} to {row['revision']}"
                    )
                await db.execute(
                    "UPDATE project_notes SET updated_at = ?, revision = ?, data = ? "
                    "WHERE id = ? AND project_id = ? AND revision = ?",
                    (
                        updated.updated_at.isoformat(),
                        updated.revision,
                        updated.model_dump_json(),
                        updated.id,
                        updated.project_id,
                        expected_revision,
                    ),
                )
                await _record_activity(
                    db,
                    project_id=updated.project_id,
                    action="note.updated",
                    subject_id=updated.id,
                    label=updated.title,
                    occurred_at=updated.updated_at,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return updated

    async def delete_note(self, project_id: str, note_id: str) -> None:
        async with self._lock:
            db = self._connection()
            try:
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    "SELECT data FROM project_notes WHERE id = ? AND project_id = ?",
                    (note_id, project_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise NotFoundError(f"Project note '{note_id}' was not found")
                note = ProjectNote.model_validate_json(row["data"])
                await db.execute(
                    "DELETE FROM project_notes WHERE id = ? AND project_id = ?",
                    (note_id, project_id),
                )
                await _record_activity(
                    db,
                    project_id=project_id,
                    action="note.deleted",
                    subject_id=note_id,
                    label=note.title,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def create_view_from_bookmark(
        self,
        project_id: str,
        session_id: str,
        bookmark_id: str,
        title: str,
        investigation_id: str | None = None,
    ) -> ProjectEarthView:
        db = self._connection()
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                project_cursor = await db.execute(
                    "SELECT archived FROM projects WHERE id = ?", (project_id,)
                )
                project = await project_cursor.fetchone()
                if project is None:
                    raise NotFoundError(f"Project '{project_id}' was not found")
                if project["archived"]:
                    raise ConflictError("Cannot save an Earth view to an archived Project")
                session_cursor = await db.execute(
                    "SELECT s.data FROM project_sessions ps "
                    "JOIN sessions s ON s.id = ps.session_id "
                    "WHERE ps.project_id = ? AND ps.session_id = ?",
                    (project_id, session_id),
                )
                session_row = await session_cursor.fetchone()
                if session_row is None:
                    raise NotFoundError(
                        f"Session '{session_id}' is not linked to Project '{project_id}'"
                    )
                session = Session.model_validate_json(session_row["data"])
                bookmark = next(
                    (
                        item
                        for item in session.earth_workspace.bookmarks
                        if item.id == bookmark_id
                    ),
                    None,
                )
                if bookmark is None:
                    raise NotFoundError(
                        f"Earth bookmark '{bookmark_id}' was not found in session '{session_id}'"
                    )
                view = ProjectEarthView(
                    project_id=project_id,
                    title=title,
                    source_session_id=session_id,
                    source_bookmark_id=bookmark_id,
                    investigation_id=investigation_id,
                    context=bookmark.context,
                )
                await db.execute(
                    "INSERT INTO project_views("
                    "id, project_id, source_session_id, investigation_id, created_at, data) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        view.id,
                        project_id,
                        session_id,
                        investigation_id,
                        view.created_at.isoformat(),
                        view.model_dump_json(),
                    ),
                )
                await _record_activity(
                    db,
                    project_id=project_id,
                    action="earth_view.saved",
                    subject_id=view.id,
                    session_id=session_id,
                    label=view.title,
                    occurred_at=view.created_at,
                )
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                raise ConflictError(f"Project Earth view '{bookmark_id}' already exists") from exc
            except BaseException:
                await db.rollback()
                raise
        return view

    async def list_views(
        self,
        project_id: str,
        *,
        investigation_id: str | None = None,
        source_session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProjectEarthView]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("limit must be between 1 and 500 and offset must be non-negative")
        if (investigation_id is None) != (source_session_id is None):
            raise ValueError(
                "investigation_id and source_session_id must be provided together"
            )
        async with self._lock:
            db = self._connection()
            project = await db.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
            if await project.fetchone() is None:
                raise NotFoundError(f"Project '{project_id}' was not found")
            filters = ""
            parameters: tuple[str | int, ...] = (project_id,)
            if investigation_id is not None and source_session_id is not None:
                filters = " AND investigation_id = ? AND source_session_id = ?"
                parameters += (investigation_id, source_session_id)
            cursor = await db.execute(
                "SELECT project_views.data, sessions.id AS live_session_id "
                "FROM project_views LEFT JOIN sessions "
                "ON sessions.id = project_views.source_session_id "
                "WHERE project_views.project_id = ?"
                + filters
                + " ORDER BY project_views.created_at DESC, project_views.id LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            )
            rows = await cursor.fetchall()
        return [
            ProjectEarthView.model_validate_json(row["data"]).model_copy(
                update={"source_session_exists": row["live_session_id"] is not None}
            )
            for row in rows
        ]

    async def delete_view(self, project_id: str, view_id: str) -> None:
        async with self._lock:
            db = self._connection()
            try:
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    "SELECT data FROM project_views WHERE id = ? AND project_id = ?",
                    (view_id, project_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise NotFoundError(f"Project Earth view '{view_id}' was not found")
                view = ProjectEarthView.model_validate_json(row["data"])
                await db.execute(
                    "DELETE FROM project_views WHERE id = ? AND project_id = ?",
                    (view_id, project_id),
                )
                await _record_activity(
                    db,
                    project_id=project_id,
                    action="earth_view.deleted",
                    subject_id=view_id,
                    session_id=view.source_session_id,
                    label=view.title,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def list_activity(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectActivity]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("limit must be between 1 and 500 and offset must be non-negative")
        async with self._lock:
            db = self._connection()
            project = await db.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
            if await project.fetchone() is None:
                raise NotFoundError(f"Project '{project_id}' was not found")
            cursor = await db.execute(
                "SELECT data FROM project_activity WHERE project_id = ? "
                "ORDER BY occurred_at DESC, id LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            )
            rows = await cursor.fetchall()
        return [ProjectActivity.model_validate_json(row["data"]) for row in rows]

    async def link_monitoring_schedule(
        self, project_id: str, schedule_id: str, mission_id: str
    ) -> ProjectMonitoringLink:
        db = self._connection()
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                project = await db.execute(
                    "SELECT archived FROM projects WHERE id = ?", (project_id,)
                )
                project_row = await project.fetchone()
                if project_row is None:
                    raise NotFoundError(f"Project '{project_id}' was not found")
                if project_row["archived"]:
                    raise ConflictError("Cannot link monitoring to an archived Project")
                existing_cursor = await db.execute(
                    "SELECT mission_id, linked_at FROM project_monitoring_links "
                    "WHERE project_id = ? AND schedule_id = ?",
                    (project_id, schedule_id),
                )
                existing = await existing_cursor.fetchone()
                if existing is not None:
                    if existing["mission_id"] != mission_id:
                        raise ConflictError(
                            f"Schedule '{schedule_id}' is linked to a different Engine mission"
                        )
                    link = ProjectMonitoringLink(
                        project_id=project_id,
                        schedule_id=schedule_id,
                        mission_id=mission_id,
                        linked_at=datetime.fromisoformat(existing["linked_at"]),
                    )
                else:
                    link = ProjectMonitoringLink(
                        project_id=project_id,
                        schedule_id=schedule_id,
                        mission_id=mission_id,
                    )
                    await db.execute(
                        "INSERT INTO project_monitoring_links("
                        "project_id, schedule_id, mission_id, linked_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            project_id,
                            schedule_id,
                            mission_id,
                            link.linked_at.isoformat(),
                        ),
                    )
                    await _record_activity(
                        db,
                        project_id=project_id,
                        action="monitoring.linked",
                        subject_id=schedule_id,
                        label=schedule_id,
                        occurred_at=link.linked_at,
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return link

    async def list_monitoring_links(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ProjectMonitoringLink]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("limit must be between 1 and 500 and offset must be non-negative")
        async with self._lock:
            db = self._connection()
            project = await db.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
            if await project.fetchone() is None:
                raise NotFoundError(f"Project '{project_id}' was not found")
            cursor = await db.execute(
                "SELECT project_id, schedule_id, mission_id, linked_at "
                "FROM project_monitoring_links WHERE project_id = ? "
                "ORDER BY linked_at DESC, schedule_id LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            )
            rows = await cursor.fetchall()
        return [
            ProjectMonitoringLink(
                project_id=row["project_id"],
                schedule_id=row["schedule_id"],
                mission_id=row["mission_id"],
                linked_at=row["linked_at"],
            )
            for row in rows
        ]

    async def unlink_monitoring_schedule(self, project_id: str, schedule_id: str) -> None:
        db = self._connection()
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    "SELECT mission_id FROM project_monitoring_links "
                    "WHERE project_id = ? AND schedule_id = ?",
                    (project_id, schedule_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise NotFoundError(
                        f"Monitoring schedule '{schedule_id}' is not linked to "
                        f"Project '{project_id}'"
                    )
                await db.execute(
                    "DELETE FROM project_monitoring_links "
                    "WHERE project_id = ? AND schedule_id = ?",
                    (project_id, schedule_id),
                )
                await _record_activity(
                    db,
                    project_id=project_id,
                    action="monitoring.unlinked",
                    subject_id=schedule_id,
                    label=schedule_id,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
