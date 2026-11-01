from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from earth_platform.shared.clock import utcnow
from earth_platform.shared.earth import EarthContext, EarthWorkspaceState
from earth_platform.shared.geo import BoundingBox, TimeRange
from earth_platform.shared.ids import new_id
from earth_platform.shared.messages import Message


class InvestigationContext(BaseModel):
    """The working focus of a session. References only; evidence lives in the Engine."""

    focus_region: BoundingBox | None = None
    focus_time: TimeRange | None = None
    active_investigation_ids: list[str] = Field(default_factory=list)
    pinned_evidence_ids: list[str] = Field(default_factory=list)
    notes: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ses"))
    title: str | None = None
    engine_agent_session_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    context: InvestigationContext = Field(default_factory=InvestigationContext)
    earth_workspace: EarthWorkspaceState = Field(default_factory=EarthWorkspaceState)
    earth_context_snapshots: list[EarthContext] = Field(default_factory=list, max_length=20)
    archived: bool = False


class Conversation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("conv"))
    session_id: str
    title: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    messages: list[Message] = Field(default_factory=list)


TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class ActiveTask(BaseModel):
    """A long-running unit of work (agent run, engine investigation, monitoring job)
    whose lifetime can exceed a single HTTP request or browser connection."""

    id: str = Field(default_factory=lambda: new_id("task"))
    session_id: str
    kind: str  # "agent_run" | "engine_call" | plugin-defined
    status: TaskStatus = "queued"
    progress: float | None = Field(default=None, ge=0, le=1)
    engine_call_id: str | None = None
    run_id: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    error: str | None = None


class StoredEvent(BaseModel):
    """Opaque, ordered record of everything streamed for a session, enabling resume after a
    dropped connection. ``payload`` is the serialised event; this module does not interpret it."""

    session_id: str
    seq: int
    type: str
    payload: dict[str, Any]
    at: datetime = Field(default_factory=utcnow)
