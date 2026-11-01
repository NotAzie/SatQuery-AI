from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from earth_platform.agent.context import RunContext
from earth_platform.earth.commands import EarthCommand
from earth_platform.engine.models import EvidenceRef
from earth_platform.llm.types import ToolSchema


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    source_id: str  # the ToolSource that executes it
    origin: Literal["engine", "plugin", "builtin"]

    def to_llm_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name, description=self.description, input_schema=self.input_schema
        )


class ToolInvocation(BaseModel):
    """A model-requested call, identified by the provider's tool-call id."""

    id: str
    run_id: str
    tool: str
    arguments: dict[str, Any]


class ToolProgress(BaseModel):
    kind: Literal["progress"] = "progress"
    invocation_id: str
    fraction: float | None = Field(default=None, ge=0, le=1)
    message: str | None = None
    investigation_id: str | None = None


class ToolOutcome(BaseModel):
    """Final item of a tool stream. ``output`` is what the model sees; ``evidence`` and
    ``earth_commands`` are what the user sees."""

    kind: Literal["outcome"] = "outcome"
    invocation_id: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    earth_commands: list[EarthCommand] = Field(default_factory=list)
    error: str | None = None


ToolStreamItem = ToolProgress | ToolOutcome


class ToolSource(Protocol):
    """A provider of tools. The Engine bridge is one source; plugins register others."""

    @property
    def id(self) -> str: ...

    async def list_specs(self) -> list[ToolSpec]: ...

    def execute(self, invocation: ToolInvocation, ctx: RunContext) -> AsyncIterator[ToolStreamItem]:
        """Yield zero or more ``ToolProgress`` then exactly one ``ToolOutcome``."""
        ...
