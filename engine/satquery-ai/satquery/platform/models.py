"""Provider-neutral model execution interfaces."""

from __future__ import annotations

import asyncio
import inspect
import time
from abc import ABC, abstractmethod
from typing import Awaitable

from ..errors import ModelError
from .contracts import ModelMetadata, ModelRequest, ModelResult
from .registry import ComponentRegistry


class ModelAdapter(ABC):
    """Common interface for local and remote inference providers."""

    @property
    @abstractmethod
    def metadata(self) -> ModelMetadata:
        """Describe model identity, modalities, and supported capabilities."""

    @abstractmethod
    def infer(self, request: ModelRequest) -> ModelResult | Awaitable[ModelResult]:
        """Run inference; synchronous local adapters are offloaded by ModelRuntime."""


class ModelRuntime:
    """Resolve registered adapters and normalize sync/async inference."""

    def __init__(self, registry: ComponentRegistry[ModelAdapter]) -> None:
        self.registry = registry

    async def infer(self, model_id: str, request: ModelRequest) -> ModelResult:
        adapter = self.registry.get(model_id)
        if adapter.metadata.model_id != model_id:
            raise ModelError(
                f"Model registry key {model_id!r} does not match adapter identity "
                f"{adapter.metadata.model_id!r}.",
                context={
                    "registered_model": model_id,
                    "adapter_model": adapter.metadata.model_id,
                    "trace_id": request.trace_id,
                },
            )
        started = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(adapter.infer):
                result = await adapter.infer(request)
            else:
                result = await asyncio.to_thread(adapter.infer, request)
                if inspect.isawaitable(result):
                    result = await result
        except ModelError:
            raise
        except Exception as exc:
            raise ModelError(
                f"Model {model_id!r} inference failed: {exc}",
                context={"model": model_id, "trace_id": request.trace_id},
            ) from exc
        if not isinstance(result, ModelResult):
            raise ModelError(
                f"Model {model_id!r} returned {type(result).__name__}, not ModelResult.",
                context={"model": model_id, "trace_id": request.trace_id},
            )
        if result.model_id != adapter.metadata.model_id:
            raise ModelError(
                f"Model {model_id!r} returned a result identified as "
                f"{result.model_id!r}.",
                context={
                    "registered_model": model_id,
                    "adapter_model": adapter.metadata.model_id,
                    "result_model": result.model_id,
                    "trace_id": request.trace_id,
                },
            )
        if result.latency_seconds is None:
            return result.model_copy(
                update={"latency_seconds": time.perf_counter() - started}
            )
        return result
