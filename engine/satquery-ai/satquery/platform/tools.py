"""Self-describing platform tools and legacy tool compatibility adapters."""

from __future__ import annotations

import asyncio
import inspect
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from ..errors import ToolExecutionError
from .contracts import TaskStatus, ToolMetadata, ToolResult
from .registry import ComponentRegistry


class PlatformTool(ABC):
    """Versioned tool contract independent of the legacy query schemas."""

    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        """Describe inputs, outputs, and capabilities."""

    @abstractmethod
    def run(self, inputs: dict[str, Any]) -> Any:
        """Execute a stateless operation; implementations may be sync or async."""

    async def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(self.run):
                output = await self.run(inputs)  # type: ignore[misc]
            else:
                output = await asyncio.to_thread(self.run, inputs)
                if inspect.isawaitable(output):
                    output = await output
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(
                self.metadata.tool_id,
                f"Tool {self.metadata.tool_id!r} failed: {exc}",
                context={"tool": self.metadata.tool_id},
            ) from exc
        finished_at = datetime.now(timezone.utc)
        return ToolResult(
            tool_id=self.metadata.tool_id,
            tool_version=self.metadata.version,
            status=TaskStatus.SUCCEEDED,
            output=output,
            started_at=started_at,
            finished_at=finished_at,
            provenance={"duration_seconds": time.perf_counter() - started},
        )


class LegacyToolAdapter(PlatformTool):
    """Expose an existing synchronous ``satquery.tools.Tool`` as a platform tool."""

    def __init__(self, tool: Any) -> None:
        if not callable(getattr(tool, "run", None)) or not hasattr(tool, "name"):
            raise TypeError("legacy tool adapter requires a tool with name and run()")
        self.tool = tool

    @property
    def metadata(self) -> ToolMetadata:
        name = self.tool.name
        tool_id = getattr(name, "value", str(name))
        return ToolMetadata(
            tool_id=tool_id,
            name=tool_id.replace("_", " ").title(),
            version=getattr(self.tool, "version", "1.0.0"),
            description=getattr(self.tool, "description", ""),
            stateless=True,
            metadata={"adapter": "legacy-satquery-tool"},
        )

    def run(self, inputs: dict[str, Any]) -> Any:
        raise RuntimeError(
            "Legacy tools require their existing ToolContext; use execute_legacy()."
        )

    async def execute_legacy(self, context: Any) -> Any:
        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(self.tool.run, context)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(
                self.metadata.tool_id,
                f"Legacy tool {self.metadata.tool_id!r} failed: {exc}",
                context={"tool": self.metadata.tool_id},
            ) from exc
        if not hasattr(result, "ok"):
            raise ToolExecutionError(
                self.metadata.tool_id,
                "Legacy tool returned an unsupported result shape.",
                context={"tool": self.metadata.tool_id},
            )
        return ToolResult(
            tool_id=self.metadata.tool_id,
            tool_version=self.metadata.version,
            status=TaskStatus.SUCCEEDED if result.ok else TaskStatus.FAILED,
            output=result,
            warnings=tuple(result.warnings),
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            provenance={
                "adapter": "legacy-satquery-tool",
                "duration_seconds": time.perf_counter() - started,
            },
        )


class ToolRuntime:
    """Run registered platform tools by stable identifier."""

    def __init__(self, registry: ComponentRegistry[PlatformTool]) -> None:
        self.registry = registry

    async def execute(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        tool = self.registry.get(tool_id)
        if tool.metadata.tool_id != tool_id:
            raise ToolExecutionError(
                tool_id,
                f"Tool registry key {tool_id!r} does not match tool identity "
                f"{tool.metadata.tool_id!r}.",
                context={"registered_tool": tool_id, "metadata_tool": tool.metadata.tool_id},
            )
        if isinstance(tool, LegacyToolAdapter):
            raise ToolExecutionError(
                tool_id,
                "This legacy tool requires a satquery ToolContext; use execute_legacy().",
                context={"tool": tool_id},
            )
        return await tool.execute(inputs)

    async def execute_legacy(self, tool_id: str, context: Any) -> ToolResult:
        tool = self.registry.get(tool_id)
        if tool.metadata.tool_id != tool_id:
            raise ToolExecutionError(
                tool_id,
                f"Tool registry key {tool_id!r} does not match tool identity "
                f"{tool.metadata.tool_id!r}.",
                context={"registered_tool": tool_id, "metadata_tool": tool.metadata.tool_id},
            )
        if not isinstance(tool, LegacyToolAdapter):
            raise ToolExecutionError(
                tool_id,
                "The registered tool is not a legacy SatQuery tool.",
                context={"tool": tool_id},
            )
        return await tool.execute_legacy(context)


def register_legacy_tools(
    registry: ComponentRegistry[PlatformTool],
    tools: dict[Any, Any],
) -> None:
    """Register existing SatQuery tools without changing their API or behavior."""
    for legacy_name, tool in tools.items():
        tool_id = getattr(legacy_name, "value", str(legacy_name))
        registry.register(tool_id, LegacyToolAdapter(tool))
