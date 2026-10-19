from satquery.config import Settings
from satquery.orchestrator import SatQueryEngine
from satquery.platform.config import PlatformConfig
from satquery.platform.runtime import PlatformRuntime

from test_platform_adapters import DemoModel, DemoTool


def test_existing_engine_registers_legacy_tools_without_loading_models():
    engine = SatQueryEngine(settings=Settings.from_env(dotenv_path=None))

    expected = {name.value for name in engine.tools}
    assert set(engine.platform_registries.tools.names()) == expected
    assert engine.connector_manager.registry is engine.platform_registries.connectors
    assert engine.registry.loaded_keys() == []


def test_platform_runtime_composes_injected_services_and_closes_cleanly():
    async def run():
        runtime = PlatformRuntime(config=PlatformConfig.load(
            environ={"SATQUERY_PLATFORM_PROFILE": "testing"}
        ))
        model = DemoModel()
        tool = DemoTool()
        runtime.register_model(model)
        runtime.register_tool(tool)
        runtime.register_task_handler("noop", lambda _context: "done")

        async with runtime as active:
            assert active is runtime
            assert active.registries.models.get("demo") is model
            assert active.registries.tools.get("demo-tool") is tool
            assert active.task_handlers.get("noop") is not None
            assert active.execution_engine.handlers is active.task_handlers
            assert active.connector_manager.registry is active.registries.connectors

        assert runtime._closed

    import asyncio

    asyncio.run(run())
