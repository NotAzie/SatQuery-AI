from typing import Protocol

from earth_platform.agent.events import AgentEvent


class ResponseStream(Protocol):
    """Async-iterable handle on a run. Iteration ends after ``run.completed`` or ``run.failed``."""

    @property
    def run_id(self) -> str: ...

    def __aiter__(self) -> "ResponseStream": ...

    async def __anext__(self) -> AgentEvent: ...

    async def cancel(self) -> None: ...
