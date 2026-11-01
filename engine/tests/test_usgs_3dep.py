import asyncio

import httpx
import pytest

from satquery.errors import ValidationError
from satquery.platform.contracts import EarthQuery
from satquery.platform.connectors import ConnectorManager
from satquery.platform.perception import PerceptionEngine
from connectors.usgs_3dep import UsgsEpqsConnector


def test_usgs_epqs_normalizes_point_elevation_and_preserves_source_payload():
    source_response = {
        "value": "123.4",
        "units": "Meters",
        "dataSource": "3DEP 1/3 arc-second",
        "resolution": "1/3 arc-second",
        "dataDate": "2025-10-23",
    }
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=source_response)

    async def run():
        connector = UsgsEpqsConnector(
            transport=httpx.MockTransport(handler),
        )
        await connector.start()
        result = await connector.observe(
            EarthQuery(point=(-105.27, 40.015), requested_variables=("elevation",))
        )
        await connector.stop()

        assert len(requests) == 1
        assert requests[0].url.params["x"] == "-105.27"
        assert requests[0].url.params["y"] == "40.015"
        assert requests[0].url.params["wkid"] == "4326"
        assert requests[0].url.params["units"] == "Meters"
        observation = result.observations[0]
        assert observation.measured_variables["elevation"] == {
            "value": 123.4,
            "unit": "m",
            "source_unit": "Meters",
        }
        assert observation.geometry == {
            "type": "Point",
            "coordinates": [-105.27, 40.015],
        }
        assert observation.observed_at is None
        assert observation.confidence is None
        assert observation.uncertainty == {}
        assert observation.source_document == source_response
        assert result.source_document["response"] == source_response

    asyncio.run(run())


def test_usgs_epqs_rejects_unsupported_query_constraints():
    connector = UsgsEpqsConnector()

    with pytest.raises(ValidationError, match="temporal queries"):
        connector._request_from_query(
            EarthQuery(
                point=(-105.27, 40.015),
                temporal_start="2024-01-01T00:00:00Z",
                temporal_end="2024-01-02T00:00:00Z",
            )
        )

    with pytest.raises(ValidationError, match="single point"):
        connector._request_from_query(EarthQuery(bbox=(-106, 39, -105, 40)))


def test_usgs_epqs_discovery_declares_only_verified_point_coverage():
    async def run():
        connector = UsgsEpqsConnector()
        datasets = await connector.discover()
        assert len(datasets) == 1
        assert datasets[0].dataset_id == "usgs-3dep-epqs"
        assert datasets[0].metadata["variables"] == ["elevation"]
        assert "temporal_coverage" not in datasets[0].metadata

    asyncio.run(run())


def test_usgs_epqs_runs_through_provider_neutral_perception_pipeline():
    async def handler(_request):
        return httpx.Response(
            200,
            json={"value": "123.4", "units": "Meters", "dataSource": "3DEP"},
        )

    async def run():
        connector = UsgsEpqsConnector(transport=httpx.MockTransport(handler))
        manager = ConnectorManager()
        manager.register(connector)
        engine = PerceptionEngine(manager)
        result = await engine.observe(
            EarthQuery(
                point=(-105.27, 40.015),
                requested_variables=("dem",),
                required_capabilities=("terrain",),
            )
        )
        await manager.stop_all()

        assert result.status == "complete"
        assert result.connector_ids == ("usgs-3dep-epqs",)
        assert result.observations[0].provenance["satquery"]["earth_perception"][
            "connector_id"
        ] == "usgs-3dep-epqs"
        assert result.observations[0].quality_assessment.completeness == 1.0

    asyncio.run(run())
