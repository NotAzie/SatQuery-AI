"""Platform-side view of what crosses the Engine boundary.

Deliberately thin: payloads the Platform does not need to interpret stay opaque
(``dict``). The HTTP adapter maps the published Engine Agent API shapes here so the
rest of the Platform never imports Engine types.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from earth_platform.shared.geo import BoundingBox, GeoJSONGeometry, TimeRange


class EngineHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable", "unconfigured"]
    version: str | None = None
    detail: str | None = None


class EngineAgentToolCall(BaseModel):
    call_id: str
    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class EngineAgentMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    turn_id: str
    tool_calls: list[EngineAgentToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    model_id: str | None = None


class EngineAgentSession(BaseModel):
    """Conversation state returned by the Engine Agent Interface."""

    session_id: str
    revision: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime
    messages: list[EngineAgentMessage] = Field(default_factory=list)
    investigation_ids: list[str] = Field(default_factory=list)


EngineAgentEventKind = Literal[
    "turn.started",
    "assistant.delta",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "investigation.progress",
    "turn.completed",
    "turn.cancelled",
    "agent.error",
]


class EngineAgentEvent(BaseModel):
    """One event in the Engine-owned model/tool turn stream."""

    kind: EngineAgentEventKind
    session_id: str
    turn_id: str
    sequence: int = Field(ge=1)
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class EngineToolDescriptor(BaseModel):
    """A capability the Engine exposes through its Agent Interface."""

    name: str
    description: str
    input_schema: dict[str, Any]
    tags: list[str] = Field(default_factory=list)


class EngineContext(BaseModel):
    """Ambient scope forwarded with an invocation so the Engine can attach work to the
    right investigation / Earth Memory scope. Opaque ids only."""

    session_id: str
    investigation_id: str | None = None
    region: BoundingBox | None = None
    time_range: TimeRange | None = None


class EngineInvocation(BaseModel):
    call_id: str
    tool: str
    arguments: dict[str, Any]
    context: EngineContext


class EvidenceRef(BaseModel):
    """Pointer to evidence held by the Engine. The Platform never recomputes or edits it."""

    id: str
    kind: str
    title: str | None = None
    geometry: GeoJSONGeometry | None = None
    time_range: TimeRange | None = None
    uri: str | None = None


class EngineProgress(BaseModel):
    type: Literal["progress"] = "progress"
    call_id: str
    fraction: float | None = Field(default=None, ge=0, le=1)
    message: str | None = None
    investigation_id: str | None = None


class EngineEvidence(BaseModel):
    type: Literal["evidence"] = "evidence"
    call_id: str
    evidence: EvidenceRef


class EngineResult(BaseModel):
    """Always the final item of an invocation stream."""

    type: Literal["result"] = "result"
    call_id: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    error: str | None = None


EngineStreamItem = EngineProgress | EngineEvidence | EngineResult
