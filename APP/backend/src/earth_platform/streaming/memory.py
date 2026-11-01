"""Single-process live fan-out backed by the session store's durable event log."""

import asyncio
from collections.abc import AsyncGenerator

from pydantic import TypeAdapter

from earth_platform.agent.events import AgentEvent
from earth_platform.sessions.repository import EventLog
from earth_platform.streaming.bus import EventBus

_EVENT_ADAPTER = TypeAdapter(AgentEvent)


class InMemoryEventBus(EventBus):
    """Persist-before-publish bus with ordered replay and gap-free local subscriptions.

    The event log is durable; subscriber notification is process-local. Deployments with
    multiple API workers should replace this bus with a shared broker implementation.
    """

    def __init__(self, event_log: EventLog | None = None) -> None:
        self._event_log = event_log
        self._subscribers: dict[str, set[asyncio.Queue[AgentEvent | None]]] = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._subscriber_queue_size = 512

    def bind(self, event_log: EventLog) -> None:
        if self._event_log is not None:
            raise RuntimeError("Event log is already bound")
        self._event_log = event_log

    def _log(self) -> EventLog:
        if self._event_log is None:
            raise RuntimeError("EventBus requires a bound event log")
        return self._event_log

    async def publish(self, session_id: str, event: AgentEvent) -> AgentEvent:
        if self._closed:
            raise RuntimeError("EventBus is closed")
        if event.session_id != session_id:
            raise ValueError("Published event session_id does not match target session")

        async with self._lock:
            stored = await self._log().append(
                session_id,
                event.type,
                event.model_dump(mode="json"),
            )
            published = event.model_copy(update={"seq": stored.seq})
            subscribers = self._subscribers.get(session_id, set())
            for queue in tuple(subscribers):
                try:
                    queue.put_nowait(published)
                except asyncio.QueueFull:
                    subscribers.discard(queue)
                    while not queue.empty():
                        queue.get_nowait()
                    queue.put_nowait(None)
            if not subscribers:
                self._subscribers.pop(session_id, None)
        return published

    async def subscribe(
        self, session_id: str, *, after_seq: int = 0
    ) -> AsyncGenerator[AgentEvent, None]:
        if after_seq < 0:
            raise ValueError("after_seq must be non-negative")
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue(maxsize=self._subscriber_queue_size)
        async with self._lock:
            replay: list[AgentEvent] = []
            async for stored in self._log().read_after(session_id, after_seq):
                replay.append(_EVENT_ADAPTER.validate_python({**stored.payload, "seq": stored.seq}))
            if self._closed:
                return
            self._subscribers.setdefault(session_id, set()).add(queue)

        try:
            for event in replay:
                yield event
            while not self._closed:
                next_event = await queue.get()
                if next_event is None:
                    return
                yield next_event
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(session_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(session_id, None)

    async def aclose(self) -> None:
        async with self._lock:
            self._closed = True
            for subscribers in self._subscribers.values():
                for queue in subscribers:
                    queue.put_nowait(None)
            self._subscribers.clear()
