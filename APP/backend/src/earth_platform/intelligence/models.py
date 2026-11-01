from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from earth_platform.shared.earth import EarthContext
from earth_platform.shared.geo import LngLat, TimeRange
from earth_platform.vision.types import VisionContext

MemoryKind = Literal[
    "asset",
    "bookmark",
    "conversation",
    "drawing",
    "evidence",
    "investigation",
    "session",
    "earth_context",
]


class MemoryRecord(BaseModel):
    id: str
    kind: MemoryKind
    session_id: str
    title: str
    content: str
    created_at: datetime
    location: LngLat | None = None
    time_reference: datetime | None = None
    time_range: TimeRange | None = None


class RankedMemoryRecord(BaseModel):
    record: MemoryRecord
    score: float = Field(ge=0)


class ContextMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str


class ConversationContext(BaseModel):
    messages: list[ContextMessage]
    compressed_summary: str | None = None
    omitted_message_count: int = 0
    estimated_tokens: int = Field(ge=0)


class CapabilityEntry(BaseModel):
    id: str
    kind: str
    status: Literal["available", "configured", "unavailable", "unknown"]
    detail: str | None = None


class CapabilitySnapshot(BaseModel):
    providers: list[CapabilityEntry]
    provider_streaming: list[CapabilityEntry]
    provider_vision: list[CapabilityEntry]
    provider_attachments: list[CapabilityEntry]
    platform_tool_sources: list[CapabilityEntry]
    earth_layers: list[CapabilityEntry]
    earth_commands: list[CapabilityEntry]
    workspace_capabilities: list[CapabilityEntry]
    vision_ingestion: CapabilityEntry
    vision_engine_delivery: CapabilityEntry
    streaming: CapabilityEntry
    engine_tool_discovery: CapabilityEntry
    dataset_discovery: CapabilityEntry


class Recommendation(BaseModel):
    kind: Literal[
        "related_investigation",
        "recent_asset",
        "related_bookmark",
        "related_conversation",
        "timeline_overlap",
    ]
    title: str
    detail: str
    session_id: str
    reference_id: str


class NormalizedExecutionRequest(BaseModel):
    session_id: str
    message: str
    engine_message: str
    earth_context: EarthContext | None
    conversation_context: ConversationContext
    vision_context: VisionContext
    retrieved_memory: list[RankedMemoryRecord]
    capabilities: CapabilitySnapshot
    recommendations: list[Recommendation]
    estimated_tokens: int = Field(ge=0)
    compressed: bool
    dropped_memory_count: int = Field(ge=0)
    attachments_supported_by_engine: bool
    warnings: list[str] = Field(default_factory=list)


class RequestPlanResponse(BaseModel):
    request: NormalizedExecutionRequest
    engine_supports_earth_context: bool
    engine_supports_attachments: bool
    integration_boundaries: list[str]


class MemorySearchResponse(BaseModel):
    query: str
    results: list[RankedMemoryRecord]
