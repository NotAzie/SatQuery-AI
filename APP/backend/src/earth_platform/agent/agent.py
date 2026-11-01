from typing import Protocol

from pydantic import BaseModel, Field

from earth_platform.agent.stream import ResponseStream
from earth_platform.earth.state import EarthContext
from earth_platform.llm.types import ModelRef
from earth_platform.shared.ids import new_id
from earth_platform.shared.messages import Message


class AgentRequest(BaseModel):
    session_id: str
    conversation_id: str
    message: Message  # may contain ImagePart(s)
    earth_context: EarthContext | None = None
    model: ModelRef | None = None  # None = platform default / selector decides
    run_id: str = Field(default_factory=lambda: new_id("run"))


class Agent(Protocol):
    """Compatibility seam for an Agent implementation.

    Engine-backed Earth turns must delegate to SatQuery Engine's Agent API; a Platform
    implementation must not introduce a second model/tool loop or scientific runtime.
    """

    def run(self, request: AgentRequest) -> ResponseStream: ...

    async def cancel(self, run_id: str) -> None: ...
