"""Provider-neutral request/response vocabulary. Adapters translate to and from vendor APIs."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from earth_platform.shared.messages import Message


class ModelRef(BaseModel):
    provider_id: str
    model: str


class ModelCapabilities(BaseModel):
    vision: bool = False
    tool_calling: bool = False
    reasoning: bool = False
    streaming: bool = True
    structured_output: bool = False
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None


class ModelInfo(BaseModel):
    ref: ModelRef
    display_name: str | None = None
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    local: bool = False


class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema


class GenerationParams(BaseModel):
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    stop: list[str] = Field(default_factory=list)
    seed: int | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None


class LLMRequest(BaseModel):
    model: ModelRef
    messages: list[Message]
    system: str | None = None
    tools: list[ToolSchema] = Field(default_factory=list)
    tool_choice: Literal["auto", "none", "required"] | str = "auto"
    params: GenerationParams = Field(default_factory=GenerationParams)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None


FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "error"]


class TextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ReasoningDelta(BaseModel):
    type: Literal["reasoning_delta"] = "reasoning_delta"
    text: str


class ToolCallDelta(BaseModel):
    type: Literal["tool_call_delta"] = "tool_call_delta"
    invocation_id: str
    tool: str | None = None
    arguments_fragment: str


class ToolCallComplete(BaseModel):
    type: Literal["tool_call_complete"] = "tool_call_complete"
    invocation_id: str
    tool: str
    arguments: dict[str, Any]


class UsageUpdate(BaseModel):
    type: Literal["usage"] = "usage"
    usage: Usage


class Finish(BaseModel):
    type: Literal["finish"] = "finish"
    reason: FinishReason


LLMChunk = Annotated[
    TextDelta | ReasoningDelta | ToolCallDelta | ToolCallComplete | UsageUpdate | Finish,
    Field(discriminator="type"),
]


class LLMResponse(BaseModel):
    message: Message
    usage: Usage = Field(default_factory=Usage)
    finish_reason: FinishReason = "stop"
