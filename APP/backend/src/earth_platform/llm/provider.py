from collections.abc import AsyncIterator
from typing import Literal, Protocol

from pydantic import BaseModel

from earth_platform.llm.types import LLMChunk, LLMRequest, LLMResponse, ModelInfo
from earth_platform.settings.models import ProviderSettings


class ProviderHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    detail: str | None = None


class LLMProvider(Protocol):
    """One configured endpoint of a vendor (OpenAI, Claude, Gemini, Ollama, OpenRouter, ...).

    Implementations own vendor SDK usage, message/tool/image translation and error
    normalisation (see ``earth_platform.llm.errors``). They hold no conversation state.
    """

    @property
    def id(self) -> str: ...

    @property
    def kind(self) -> str: ...

    async def list_models(self) -> list[ModelInfo]: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]: ...

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def health(self) -> ProviderHealth: ...

    async def aclose(self) -> None: ...


class ProviderFactory(Protocol):
    """Registered under ``kind`` by the core or by a plugin."""

    @property
    def kind(self) -> str: ...

    def create(self, provider_id: str, config: ProviderSettings) -> LLMProvider: ...
