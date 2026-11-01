"""SQLite-backed session, conversation, task, and event repositories."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite

from earth_platform.sessions.models import (
    ActiveTask,
    Conversation,
    Session,
    StoredEvent,
    TaskStatus,
)
from earth_platform.sessions.repository import (
    ConversationRepository,
    EventLog,
    SessionRepository,
    TaskRepository,
)
from earth_platform.shared.errors import ConflictError, NotFoundError
from earth_platform.shared.messages import Message


def _ensure_parent_directory(dsn: str) -> None:
    Path(dsn).resolve().parent.mkdir(parents=True, exist_ok=True)


class SQLiteSessionStore:
    """Single-process durable store. A different store can implement the same protocols."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn if dsn == ":memory:" else str(Path(dsn).expanduser())
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self.sessions: SessionRepository = _Sessions(self)
        self.conversations: ConversationRepository = _Conversations(self)
        self.tasks: TaskRepository = _Tasks(self)
        self.events: EventLog = _Events(self)

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
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                archived INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS conversations_by_session
                ON conversations(session_id, created_at);
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tasks_by_session ON tasks(session_id, started_at);
            CREATE TABLE IF NOT EXISTS events (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                at TEXT NOT NULL,
                PRIMARY KEY (session_id, seq)
            );
            """
        )
        await self._db.commit()

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteSessionStore.open() must be called before use")
        return self._db


class _Sessions:
    def __init__(self, store: SQLiteSessionStore) -> None:
        self._store = store

    async def create(self, session: Session) -> Session:
        async with self._store._lock:
            try:
                await self._store._connection().execute(
                    "INSERT INTO sessions(id, updated_at, archived, data) VALUES (?, ?, ?, ?)",
                    (
                        session.id,
                        session.updated_at.isoformat(),
                        int(session.archived),
                        session.model_dump_json(),
                    ),
                )
                await self._store._connection().commit()
            except aiosqlite.IntegrityError as exc:
                raise ConflictError(f"Session '{session.id}' already exists") from exc
        return session

    async def get(self, session_id: str) -> Session:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "SELECT data FROM sessions WHERE id = ?", (session_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"Session '{session_id}' was not found")
        return Session.model_validate_json(row["data"])

    async def update(self, session: Session) -> Session:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "UPDATE sessions SET updated_at = ?, archived = ?, data = ? WHERE id = ?",
                (
                    session.updated_at.isoformat(),
                    int(session.archived),
                    session.model_dump_json(),
                    session.id,
                ),
            )
            await self._store._connection().commit()
        if cursor.rowcount == 0:
            raise NotFoundError(f"Session '{session.id}' was not found")
        return session

    async def list(
        self, *, include_archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Session]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("limit must be between 1 and 500 and offset must be non-negative")
        async with self._store._lock:
            query = "SELECT data FROM sessions"
            params: tuple[Any, ...] = ()
            if not include_archived:
                query += " WHERE archived = 0"
            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            cursor = await self._store._connection().execute(query, (*params, limit, offset))
            rows = await cursor.fetchall()
        return [Session.model_validate_json(row["data"]) for row in rows]

    async def delete(self, session_id: str) -> None:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            await self._store._connection().commit()
        if cursor.rowcount == 0:
            raise NotFoundError(f"Session '{session_id}' was not found")


class _Conversations:
    def __init__(self, store: SQLiteSessionStore) -> None:
        self._store = store

    async def create(self, conversation: Conversation) -> Conversation:
        async with self._store._lock:
            try:
                await self._store._connection().execute(
                    "INSERT INTO conversations(id, session_id, created_at, data) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        conversation.id,
                        conversation.session_id,
                        conversation.created_at.isoformat(),
                        conversation.model_dump_json(),
                    ),
                )
                await self._store._connection().commit()
            except aiosqlite.IntegrityError as exc:
                raise ConflictError(
                    f"Conversation '{conversation.id}' already exists or session is missing"
                ) from exc
        return conversation

    async def get(self, conversation_id: str) -> Conversation:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "SELECT data FROM conversations WHERE id = ?", (conversation_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"Conversation '{conversation_id}' was not found")
        return Conversation.model_validate_json(row["data"])

    async def list_for_session(self, session_id: str) -> list[Conversation]:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "SELECT data FROM conversations WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )
            rows = await cursor.fetchall()
        return [Conversation.model_validate_json(row["data"]) for row in rows]

    async def append_message(self, conversation_id: str, message: Message) -> None:
        async with self._store._lock:
            db = self._store._connection()
            cursor = await db.execute(
                "SELECT data FROM conversations WHERE id = ?", (conversation_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                raise NotFoundError(f"Conversation '{conversation_id}' was not found")
            conversation = Conversation.model_validate_json(row["data"])
            conversation.messages.append(message)
            await db.execute(
                "UPDATE conversations SET data = ? WHERE id = ?",
                (conversation.model_dump_json(), conversation_id),
            )
            await db.commit()


class _Tasks:
    def __init__(self, store: SQLiteSessionStore) -> None:
        self._store = store

    async def upsert(self, task: ActiveTask) -> ActiveTask:
        async with self._store._lock:
            try:
                await self._store._connection().execute(
                    "INSERT INTO tasks(id, session_id, started_at, data) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET session_id = excluded.session_id, "
                    "started_at = excluded.started_at, data = excluded.data",
                    (
                        task.id,
                        task.session_id,
                        task.started_at.isoformat(),
                        task.model_dump_json(),
                    ),
                )
                await self._store._connection().commit()
            except aiosqlite.IntegrityError as exc:
                raise NotFoundError(f"Session '{task.session_id}' was not found") from exc
        return task

    async def get(self, task_id: str) -> ActiveTask:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "SELECT data FROM tasks WHERE id = ?", (task_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise NotFoundError(f"Task '{task_id}' was not found")
        return ActiveTask.model_validate_json(row["data"])

    async def list_for_session(
        self, session_id: str, *, statuses: set[TaskStatus] | None = None
    ) -> list[ActiveTask]:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "SELECT data FROM tasks WHERE session_id = ? ORDER BY started_at",
                (session_id,),
            )
            rows = await cursor.fetchall()
        tasks = [ActiveTask.model_validate_json(row["data"]) for row in rows]
        if statuses is not None:
            tasks = [task for task in tasks if task.status in statuses]
        return tasks


class _Events:
    def __init__(self, store: SQLiteSessionStore) -> None:
        self._store = store

    async def append(self, session_id: str, type: str, payload: dict[str, Any]) -> StoredEvent:
        db = self._store._connection()
        async with self._store._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM events WHERE session_id = ?",
                    (session_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("SQLite failed to allocate an event sequence")
                seq = int(row["next_seq"])
                at = str(payload.get("at", ""))
                await db.execute(
                    "INSERT INTO events(session_id, seq, type, payload, at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, seq, type, json.dumps(payload), at),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return StoredEvent(
            session_id=session_id,
            seq=seq,
            type=type,
            payload=payload,
        )

    async def read_after(self, session_id: str, seq: int) -> AsyncIterator[StoredEvent]:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "SELECT seq, type, payload FROM events WHERE session_id = ? AND seq > ? "
                "ORDER BY seq",
                (session_id, seq),
            )
            rows = await cursor.fetchall()
        for row in rows:
            yield StoredEvent(
                session_id=session_id,
                seq=row["seq"],
                type=row["type"],
                payload=json.loads(row["payload"]),
            )

    async def latest_seq(self, session_id: str) -> int:
        async with self._store._lock:
            cursor = await self._store._connection().execute(
                "SELECT COALESCE(MAX(seq), 0) AS latest FROM events WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("SQLite failed to read the latest event sequence")
            return int(row["latest"])
