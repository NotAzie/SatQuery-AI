from collections.abc import AsyncIterator
from typing import Protocol

from earth_platform.engine.models import EngineAgentEvent, EngineAgentSession, EngineHealth


class EngineClient(Protocol):
    """The Platform boundary to SatQuery Engine's existing Agent Interface.

    The Engine owns provider execution, tool routing, scientific work, and its
    conversation transcript. The Platform only creates sessions and forwards turns/events.
    """

    async def connect(self) -> None: ...

    async def aclose(self) -> None: ...

    async def health(self) -> EngineHealth: ...

    async def create_agent_session(self) -> EngineAgentSession: ...

    async def get_agent_session(self, session_id: str) -> EngineAgentSession: ...

    def stream_agent_turn(
        self,
        session_id: str,
        *,
        message: str,
        model_id: str,
        execution_authorized: bool = False,
    ) -> AsyncIterator[EngineAgentEvent]: ...

    async def cancel_agent_turn(self, session_id: str) -> None: ...
