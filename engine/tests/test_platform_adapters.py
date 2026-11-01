import asyncio
from types import SimpleNamespace

import pytest

from satquery.errors import ModelError, ToolExecutionError
from satquery.platform.contracts import (
    ModelMetadata,
    ModelRequest,
    ModelResult,
    TaskStatus,
    ToolMetadata,
)
from satquery.platform.models import ModelAdapter, ModelRuntime
from satquery.platform.registry import ComponentRegistry
from satquery.platform.tools import (
    LegacyToolAdapter,
    PlatformTool,
    ToolRuntime,
)


class DemoModel(ModelAdapter):
    @property
    def metadata(self):
        return ModelMetadata(
            model_id="demo",
            name="Demo model",
            provider="local",
            capabilities=("classification", "embedding"),
            input_modalities=("image", "text"),
            output_modalities=("vector", "label"),
        )

    def infer(self, request):
        return ModelResult(
            model_id=self.metadata.model_id,
            output=request.inputs["value"],
            provider=self.metadata.provider,
        )


class DemoTool(PlatformTool):
    @property
    def metadata(self):
        return ToolMetadata(
            tool_id="demo-tool",
            name="Demo Tool",
            version="1.2",
            description="Test tool",
        )

    def run(self, inputs):
        return inputs["value"] + 1


def test_model_runtime_accepts_replaceable_sync_adapter():
    async def run():
        registry = ComponentRegistry()
        registry.register("demo", DemoModel())
        result = await ModelRuntime(registry).infer(
            "demo", ModelRequest(inputs={"value": 5})
        )
        assert result.output == 5
        assert result.provider == "local"
        assert result.latency_seconds is not None

    asyncio.run(run())


def test_model_runtime_rejects_result_from_a_different_model_identity():
    class MisidentifiedModel(DemoModel):
        def infer(self, request):
            return ModelResult(model_id="different-model", output="untrusted")

    async def run():
        registry = ComponentRegistry()
        registry.register("demo", MisidentifiedModel())
        with pytest.raises(ModelError, match="identified as 'different-model'"):
            await ModelRuntime(registry).infer("demo", ModelRequest())

    asyncio.run(run())


def test_model_runtime_rejects_registry_key_that_disagrees_with_adapter():
    async def run():
        registry = ComponentRegistry()
        registry.register("alias", DemoModel())
        with pytest.raises(ModelError, match="does not match adapter identity"):
            await ModelRuntime(registry).infer("alias", ModelRequest())

    asyncio.run(run())


def test_tool_runtime_rejects_registry_key_that_disagrees_with_metadata():
    async def run():
        registry = ComponentRegistry()
        registry.register("alias", DemoTool())
        with pytest.raises(ToolExecutionError, match="does not match tool identity"):
            await ToolRuntime(registry).execute("alias", {"value": 1})

    asyncio.run(run())


def test_tool_runtime_runs_independently_testable_platform_tool():
    async def run():
        registry = ComponentRegistry()
        registry.register("demo-tool", DemoTool())
        result = await ToolRuntime(registry).execute(
            "demo-tool", {"value": 4}
        )
        assert result.output == 5
        assert result.status == TaskStatus.SUCCEEDED
        assert result.tool_version == "1.2"

    asyncio.run(run())


def test_legacy_tool_adapter_preserves_existing_context_contract():
    async def run():
        tool = SimpleNamespace(
            name=SimpleNamespace(value="old-tool"),
            description="Existing tool",
            run=lambda context: SimpleNamespace(ok=True, warnings=["note"]),
        )
        adapter = LegacyToolAdapter(tool)
        result = await adapter.execute_legacy(object())
        assert adapter.metadata.tool_id == "old-tool"
        assert result.status == TaskStatus.SUCCEEDED
        assert result.warnings == ("note",)

    asyncio.run(run())
