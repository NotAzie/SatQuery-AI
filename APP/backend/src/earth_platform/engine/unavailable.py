from collections.abc import AsyncIterator
from typing import NoReturn

from earth_platform.engine.errors import EngineUnavailableError
from earth_platform.engine.models import EngineAgentEvent, EngineAgentSession, EngineHealth

_MESSAGE = "SatQuery Engine is not configured; set engine.kind and its connection settings"


class UnavailableEngineClient:
    """Explicit null object used until an Engine adapter is configured.

    It never fabricates results: every operation except ``health`` fails loudly.
    """

    async def connect(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def health(self) -> EngineHealth:
        return EngineHealth(status="unconfigured", detail=_MESSAGE)

    def _fail(self) -> NoReturn:
        raise EngineUnavailableError(_MESSAGE)

    async def create_agent_session(self) -> EngineAgentSession:
        self._fail()

    async def get_agent_session(self, session_id: str) -> EngineAgentSession:
        self._fail()

    def stream_agent_turn(
        self,
        session_id: str,
        *,
        message: str,
        model_id: str,
        execution_authorized: bool = False,
    ) -> AsyncIterator[EngineAgentEvent]:
        self._fail()

    async def cancel_agent_turn(self, session_id: str) -> None:
        self._fail()
