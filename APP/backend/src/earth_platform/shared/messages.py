"""Provider-neutral conversation messages.

One representation is used by sessions (persistence), the agent (orchestration) and LLM
providers (translation to vendor formats). Persisted messages reference images by
``asset_id``; ``ImagePart.data`` is populated transiently just before a provider call.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from earth_platform.shared.clock import utcnow
from earth_platform.shared.ids import new_id


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ReasoningPart(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    text: str
    signature: str | None = None  # opaque vendor token required to replay thinking blocks


class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    asset_id: str
    mime_type: str
    alt: str | None = None
    data: bytes | None = Field(default=None, exclude=True, repr=False)


class ToolCallPart(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    invocation_id: str
    tool: str
    arguments: dict[str, Any]


class ToolResultPart(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    invocation_id: str
    ok: bool
    output: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


ContentPart = Annotated[
    TextPart | ReasoningPart | ImagePart | ToolCallPart | ToolResultPart,
    Field(discriminator="type"),
]

Role = Literal["system", "user", "assistant", "tool"]


class Message(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    role: Role
    content: list[ContentPart]
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
