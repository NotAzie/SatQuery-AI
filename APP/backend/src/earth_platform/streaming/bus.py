from collections.abc import AsyncGenerator
from typing import Protocol

from earth_platform.agent.events import AgentEvent


class EventBus(Protocol):
    """Fan-out of session events to any number of subscribers, with replay.

    ``publish`` appends to the session's durable event log (assigning ``seq``) and delivers to live
    subscribers. ``subscribe`` first yields logged events with ``seq > after_seq`` and then live
    ones, with no gaps or duplicates. In-memory today; Redis/NATS later, same contract."""

    async def publish(self, session_id: str, event: AgentEvent) -> AgentEvent:
        """Returns the event with ``seq`` populated."""
        ...

    def subscribe(
        self, session_id: str, *, after_seq: int = 0
    ) -> AsyncGenerator[AgentEvent, None]: ...

    async def aclose(self) -> None: ...
