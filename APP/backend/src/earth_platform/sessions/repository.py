from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from earth_platform.sessions.models import (
    ActiveTask,
    Conversation,
    Session,
    StoredEvent,
    TaskStatus,
)
from earth_platform.shared.messages import Message


class SessionRepository(Protocol):
    async def create(self, session: Session) -> Session: ...
    async def get(self, session_id: str) -> Session: ...

    async def update(self, session: Session) -> Session:
        """Replace the full record; use ``mutate`` for concurrent partial changes."""
        ...

    async def mutate(
        self,
        session_id: str,
        mutation: Callable[[Session], None],
    ) -> Session:
        """Apply a synchronous mutation to the latest record in one storage transaction."""
        ...
    async def list(
        self, *, include_archived: bool = False, limit: int = 50, offset: int = 0
    ) -> list[Session]: ...
    async def delete(self, session_id: str) -> None: ...


class ConversationRepository(Protocol):
    async def create(self, conversation: Conversation) -> Conversation: ...
    async def get(self, conversation_id: str) -> Conversation: ...
    async def list_for_session(self, session_id: str) -> list[Conversation]: ...
    async def append_message(self, conversation_id: str, message: Message) -> None: ...


class TaskRepository(Protocol):
    async def upsert(self, task: ActiveTask) -> ActiveTask: ...
    async def get(self, task_id: str) -> ActiveTask: ...
    async def list_for_session(
        self, session_id: str, *, statuses: set[TaskStatus] | None = None
    ) -> list[ActiveTask]: ...


class EventLog(Protocol):
    async def append(self, session_id: str, type: str, payload: dict[str, Any]) -> StoredEvent:
        """Assigns the next monotonically increasing ``seq`` for the session."""
        ...

    def read_after(
        self,
        session_id: str,
        seq: int,
        *,
        through_seq: int | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[StoredEvent]: ...

    async def latest_seq(self, session_id: str) -> int: ...


class SessionStore(Protocol):
    """Persistence facade. Backends (memory, sqlite, postgres) implement all repositories
    behind one connection lifecycle."""

    sessions: SessionRepository
    conversations: ConversationRepository
    tasks: TaskRepository
    events: EventLog

    async def open(self) -> None: ...
    async def aclose(self) -> None: ...
