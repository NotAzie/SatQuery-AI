from typing import Protocol

from earth_platform.llm.provider import LLMProvider, ProviderHealth
from earth_platform.llm.types import ModelInfo, ModelRef


class ProviderManager(Protocol):
    """Runtime provider management: builds providers from settings via registered
    factories, resolves defaults, aggregates health and the model catalogue."""

    def get(self, provider_id: str) -> LLMProvider: ...

    def list_providers(self) -> list[LLMProvider]: ...

    def default_model(self) -> ModelRef: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def health(self) -> dict[str, ProviderHealth]: ...

    async def aclose(self) -> None: ...
