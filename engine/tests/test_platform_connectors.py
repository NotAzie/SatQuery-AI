import asyncio
import logging

import pytest

from satquery.errors import AuthenticationError, NetworkError, ValidationError
from satquery.platform.cache import MemoryCache
from satquery.platform.connectors import (
    Connector,
    ConnectorManager,
    ConnectorPolicy,
)
from satquery.platform.contracts import ConnectorMetadata, DatasetReference
from satquery.platform.registry import ComponentRegistry


class DemoConnector(Connector):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.opens = 0
        self.closes = 0
        self.calls = 0

    @property
    def metadata(self):
        return ConnectorMetadata(
            connector_id="demo",
            name="Demo",
            version="1",
            capabilities=("read",),
            supports_streaming=True,
            datasets=(DatasetReference(connector_id="demo", dataset_id="sample"),),
        )

    async def open(self):
        self.opens += 1

    async def close(self):
        self.closes += 1

    async def discover(self):
        return self.metadata.datasets

    async def acquire(self, request):
        self.calls += 1
        if request.get("transient") and self.calls == 1:
            raise NetworkError("temporary")
        return {"value": request["value"]}

    async def stream(self, request):
        for value in request["values"]:
            yield value


def test_connector_lifecycle_retries_and_cache_hooks():
    async def run():
        cache = MemoryCache()
        connector = DemoConnector(
            cache=cache,
            policy=ConnectorPolicy(
                max_attempts=2,
                retry_safe=True,
                retry_delay_seconds=0,
            ),
        )
        registry = ComponentRegistry()
        manager = ConnectorManager(registry)
        manager.register(connector)

        assert await manager.discover("demo") == connector.metadata.datasets
        first = await manager.acquire("demo", {"value": 1, "transient": True})
        second = await manager.acquire("demo", {"value": 1, "transient": True})
        assert first == second == {"value": 1}
        assert connector.opens == 1
        assert connector.calls == 2

        streamed = []
        async for item in manager.stream("demo", {"values": [1, 2, 3]}):
            streamed.append(item)
        assert streamed == [1, 2, 3]

        await manager.stop("demo")
        assert connector.closes == 1

    asyncio.run(run())


def test_manager_restarts_connector_after_close_hook_fails():
    async def run():
        class FailingCloseConnector(DemoConnector):
            async def close(self):
                self.closes += 1
                if self.closes == 1:
                    raise RuntimeError("close failed")

        connector = FailingCloseConnector()
        manager = ConnectorManager()
        manager.register(connector)
        await manager.start("demo")

        with pytest.raises(RuntimeError, match="close failed"):
            await manager.stop("demo")

        await manager.acquire("demo", {"value": 1})
        assert connector.opens == 2

    asyncio.run(run())


def test_connector_caching_requires_json_compatible_request():
    async def run():
        connector = DemoConnector(cache=MemoryCache())
        with pytest.raises(ValidationError, match="JSON-compatible"):
            await connector.fetch({"value": object()})

    asyncio.run(run())


def test_declared_authentication_schemes_remain_required_by_default():
    async def run():
        class AuthConnector(DemoConnector):
            @property
            def metadata(self):
                return super().metadata.model_copy(
                    update={"authentication_schemes": ("bearer",)}
                )

        connector = AuthConnector()
        with pytest.raises(AuthenticationError, match="requires authentication"):
            await connector.start()
        assert connector.opens == 1
        assert connector.closes == 1

    asyncio.run(run())


def test_connector_logs_redacted_parameters_context_and_cache_hits(caplog):
    async def run():
        connector = DemoConnector(cache=MemoryCache())
        context = {
            "mission_id": "mission-1",
            "trace_id": "trace-1",
            "ignored": "not copied into event",
        }
        with caplog.at_level(logging.INFO, logger="satquery.execution"):
            await connector.fetch(
                {"value": 1, "api_token": "do-not-log"},
                execution_context=context,
            )
            await connector.fetch(
                {"value": 1, "api_token": "do-not-log"},
                execution_context=context,
            )

        events = [record.satquery_fields for record in caplog.records]
        acquisition = next(
            fields for fields in events if fields["event"] == "connector.acquisition"
        )
        cache_hit = next(
            fields for fields in events if fields["event"] == "connector.cache_hit"
        )
        assert acquisition["mission_id"] == "mission-1"
        assert acquisition["trace_id"] == "trace-1"
        assert acquisition["parameters"]["api_token"] == "[REDACTED]"
        assert "ignored" not in acquisition
        assert cache_hit["connector"] == "demo"
        assert "do-not-log" not in caplog.text

    asyncio.run(run())


def test_image_fetcher_adapter_exposes_discovery_and_validates_config():
    from connectors.image_fetcher.connector import ImageFetcherConnector

    connector = ImageFetcherConnector(configuration={"output_dir": "images"})
    assert connector.metadata.connector_id == "image-fetcher"
    assert connector.metadata.datasets[0].dataset_id == "esri-world-imagery"
    assert connector.settings.output_dir == "images"

    with pytest.raises(ValidationError, match="configuration"):
        ImageFetcherConnector(configuration={"not_a_setting": True})
