import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from connectors.noaa_coops import NoaaCoopsConnector
from fastapi.testclient import TestClient
from satquery.api import create_app, set_engine
from satquery.config import get_settings
from satquery.errors import ValidationError
from satquery.orchestrator import SatQueryEngine
from satquery.platform.connectors import ConnectorManager
from satquery.platform.contracts import EarthQuery, EarthStationSearchResult
from satquery.platform.earth_objects import (
    EarthObjectExtractionPipeline,
    EarthObjectMaterializer,
)
from satquery.platform.perception import PerceptionEngine


def test_noaa_coops_returns_station_level_ocean_observations_with_source_flags():
    requests = []

    async def handler(request: httpx.Request):
        requests.append(request)
        if request.url.path.endswith("/stations/9414290.json"):
            return httpx.Response(
                200,
                json={
                    "stations": [
                        {
                            "id": "9414290",
                            "name": "San Francisco",
                            "lat": "37.8063",
                            "lng": "-122.4659",
                            "state": "California",
                        }
                    ]
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "metadata": {"id": "9414290", "name": "San Francisco"},
                "units": "metric",
                "data": [
                    {
                        "t": "2025-03-01 00:00",
                        "v": "1.24",
                        "s": "0.03",
                        "f": "",
                        "q": "v",
                    },
                    {"t": "2025-03-01 00:06", "v": "-", "s": "-", "f": "R", "q": "p"},
                ],
            },
            request=request,
        )

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = NoaaCoopsConnector(client=client)
        manager = ConnectorManager()
        manager.register(connector)
        engine = PerceptionEngine(manager)
        result = await engine.observe(
            EarthQuery(
                temporal_start=datetime(2025, 3, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2025, 3, 1, 0, 12, tzinfo=timezone.utc),
                requested_variables=("water_level",),
                filters={"station_id": "9414290"},
            )
        )
        await manager.stop_all()
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result.status == "complete", result.failures
    assert result.plan.selected_modalities == ("oceanic",)
    assert result.plan.capability_matrix_revision
    assert len(result.observations) == 2
    observed, missing = result.observations
    assert observed.measured_variables["coastal_water_level"] == {
        "value": 1.24,
        "unit": "m",
        "source_unit": "m",
        "source_units_system": "metric",
        "source_name": "v",
        "datum": "MLLW",
        "source_sigma": {
            "value": 0.03,
            "unit": "m",
            "definition": (
                "Provider-reported standard deviation of one-second samples "
                "used to compute this water-level height."
            ),
        },
    }
    assert observed.geometry == {
        "type": "Point",
        "coordinates": [-122.4659, 37.8063],
    }
    assert observed.observed_at == datetime(2025, 3, 1, tzinfo=timezone.utc)
    assert observed.quality["provider_qa_qc_level"] == "v"
    assert observed.earth_object_candidate is not None
    assert observed.earth_object_candidate.object_type == "earth:CoastalWaterLevelStation"
    assert observed.earth_object_candidate.identity_value == "9414290"
    assert observed.observation_id.startswith("noaa-coops:9414290:")
    assert observed.earth_object_candidate.provenance["source_attributes"]["name"] == "San Francisco"
    assert observed.confidence is None
    assert observed.uncertainty == {}
    assert missing.measured_variables["coastal_water_level"]["value"] is None
    assert missing.quality["provider_data_flags"] == "R"
    assert missing.quality_assessment.completeness == 0
    assert missing.earth_object_candidate is not None
    assert missing.earth_object_candidate.identity_value == observed.earth_object_candidate.identity_value
    assert missing.observation_id != observed.observation_id
    batch = EarthObjectExtractionPipeline().extract(result.observations)
    assert len(batch.declarations) == 1
    declaration = batch.declarations[0]
    station_object = EarthObjectMaterializer().materialize(
        declaration, result.observations
    )
    assert station_object.object_type == "earth:CoastalWaterLevelStation"
    assert station_object.source_observation_ids == tuple(
        sorted(item.observation_id for item in result.observations)
    )
    assert len(station_object.measurements) == 2
    assert station_object.measurements[1].value is None or any(
        item.value is None for item in station_object.measurements
    )
    assert station_object.temporal_validity is None
    data_request = next(
        request for request in requests if request.url.path.endswith("/datagetter")
    )
    assert data_request.url.params["product"] == "water_level"
    assert data_request.url.params["datum"] == "MLLW"
    assert data_request.url.params["time_zone"] == "gmt"
    assert data_request.url.params["units"] == "metric"
    assert data_request.url.params["format"] == "json"


def test_noaa_coops_requires_explicit_station_and_bounded_aware_interval():
    connector = NoaaCoopsConnector()
    with pytest.raises(ValidationError, match="explicit station_id"):
        connector._request_from_query(
            EarthQuery(
                temporal_start=datetime(2025, 3, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2025, 3, 2, tzinfo=timezone.utc),
            )
        )
    with pytest.raises(ValidationError, match="station based"):
        connector._request_from_query(
            EarthQuery(
                point=(1, 2),
                temporal_start=datetime(2025, 3, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2025, 3, 2, tzinfo=timezone.utc),
                filters={"station_id": "9414290"},
            )
        )
    with pytest.raises(ValidationError, match="30 days"):
        connector._request_from_query(
            EarthQuery(
                temporal_start=datetime(2025, 3, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2025, 4, 5, tzinfo=timezone.utc),
                filters={"station_id": "9414290"},
            )
        )


def test_noaa_station_search_returns_bbox_candidates_via_platform_api(monkeypatch):
    requests = []

    async def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "count": 3,
                "stations": [
                    {
                        "id": "9414290",
                        "name": "San Francisco",
                        "lat": "37.8063",
                        "lng": "-122.4659",
                        "state": "California",
                    },
                    {
                        "id": "9414291",
                        "name": "Outside",
                        "lat": "34.0",
                        "lng": "-119.0",
                        "state": "California",
                    },
                    {
                        "id": "1611400",
                        "name": "Nawiliwili",
                        "lat": "21.9544",
                        "lng": "-159.3561",
                        "state": "Hawaii",
                    },
                ],
            },
            request=request,
        )

    monkeypatch.delenv("SATQUERY_CONNECTORS_CONFIG", raising=False)
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(
        NoaaCoopsConnector(transport=httpx.MockTransport(handler))
    )
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            response = client.post(
                "/api/v1/platform/connectors/noaa-coops-water-level/stations/search",
                json={"bbox": [-123, 36, -121, 38]},
            )
            invalid = client.post(
                "/api/v1/platform/connectors/noaa-coops-water-level/stations/search",
                json={"bbox": [-121, 38, -123, 36]},
            )
            unsupported = client.post(
                "/api/v1/platform/connectors/not-registered/stations/search",
                json={"bbox": [-123, 36, -121, 38]},
            )
        assert response.status_code == 200
        result = EarthStationSearchResult.model_validate(response.json())
        assert result.source_record_count == 3
        assert len(result.stations) == 1
        assert result.stations[0].station_id == "9414290"
        assert result.stations[0].longitude == -122.4659
        assert result.stations[0].latitude == 37.8063
        assert result.stations[0].source_metadata["state"] == "California"
        assert "nearest-station choice" in result.limitations[0]
        assert len(requests) == 1
        assert requests[0].url.path.endswith("/stations.json")
        assert requests[0].url.params["type"] == "waterlevels"
        assert invalid.status_code == 422
        assert unsupported.status_code == 422
    finally:
        set_engine(None)
        asyncio.run(engine.close())
