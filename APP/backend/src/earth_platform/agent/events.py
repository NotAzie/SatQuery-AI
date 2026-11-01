"""The event vocabulary of a run. This is the platform's primary wire contract: SSE and WebSocket
transports carry these, the session event log persists them, the frontend reduces them into UI and
globe state. Change it additively; bump ``EVENT_SCHEMA_VERSION`` for breaking changes."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from earth_platform.earth.commands import EarthCommand
from earth_platform.engine.models import EvidenceRef
from earth_platform.llm.types import FinishReason, ModelRef, Usage
from earth_platform.shared.clock import utcnow
from earth_platform.shared.constants import EVENT_SCHEMA_VERSION
from earth_platform.shared.ids import new_id
from earth_platform.shared.messages import Message


class _EventBase(BaseModel):
    id: str = Field(default_factory=lambda: new_id("evt"))
    schema_version: int = EVENT_SCHEMA_VERSION
    session_id: str
    conversation_id: str
    run_id: str
    seq: int | None = None  # assigned per session when the event is published
    at: datetime = Field(default_factory=utcnow)


class RunStarted(_EventBase):
    type: Literal["run.started"] = "run.started"
    model: ModelRef


class MessageDelta(_EventBase):
    type: Literal["message.delta"] = "message.delta"
    message_id: str
    text: str


class ReasoningDeltaEvent(_EventBase):
    type: Literal["reasoning.delta"] = "reasoning.delta"
    message_id: str
    text: str


class MessageCompleted(_EventBase):
    type: Literal["message.completed"] = "message.completed"
    message: Message


class ToolRequested(_EventBase):
    type: Literal["tool.requested"] = "tool.requested"
    invocation_id: str
    tool: str
    arguments: dict[str, Any]


class ToolStarted(_EventBase):
    type: Literal["tool.started"] = "tool.started"
    invocation_id: str


class ToolProgressed(_EventBase):
    type: Literal["tool.progress"] = "tool.progress"
    invocation_id: str
    fraction: float | None = Field(default=None, ge=0, le=1)
    message: str | None = None


class ToolCompleted(_EventBase):
    type: Literal["tool.completed"] = "tool.completed"
    invocation_id: str
    ok: bool
    error: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class InvestigationUpdated(_EventBase):
    type: Literal["investigation.updated"] = "investigation.updated"
    investigation_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    fraction: float | None = Field(default=None, ge=0, le=1)
    message: str | None = None


class EarthCommandIssued(_EventBase):
    type: Literal["earth.command"] = "earth.command"
    command: EarthCommand


class UsageReported(_EventBase):
    type: Literal["usage"] = "usage"
    usage: Usage


class RunCompleted(_EventBase):
    type: Literal["run.completed"] = "run.completed"
    finish_reason: FinishReason = "stop"


class RunFailed(_EventBase):
    type: Literal["run.failed"] = "run.failed"
    code: str
    message: str


class EngineEventReceived(_EventBase):
    """Unmodified Engine Agent event carried inside the Platform event envelope."""

    type: Literal["engine.event"] = "engine.event"
    engine_session_id: str
    engine_kind: str
    engine_turn_id: str
    engine_sequence: int
    engine_timestamp: datetime
    payload: dict[str, Any]


AgentEvent = Annotated[
    RunStarted
    | MessageDelta
    | ReasoningDeltaEvent
    | MessageCompleted
    | ToolRequested
    | ToolStarted
    | ToolProgressed
    | ToolCompleted
    | InvestigationUpdated
    | EarthCommandIssued
    | UsageReported
    | RunCompleted
    | RunFailed
    | EngineEventReceived,
    Field(discriminator="type"),
]
