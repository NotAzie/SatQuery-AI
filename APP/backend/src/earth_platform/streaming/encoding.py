from typing import Protocol

from earth_platform.agent.events import AgentEvent
from earth_platform.streaming.messages import ControlMessage


class EventEncoder(Protocol):
    """Serialises frames for a transport. The SSE encoder uses ``seq`` as the ``id:`` field so a
    reconnecting browser resumes via ``Last-Event-ID``; the WebSocket encoder emits JSON text."""

    content_type: str

    def encode(self, item: AgentEvent | ControlMessage) -> bytes: ...

    def heartbeat(self) -> bytes: ...
