import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from connectors.nasa_firms import NasaFirmsConnector
from satquery.connector_bootstrap import DEFAULT_CONNECTOR_FACTORIES
from satquery.errors import AuthenticationError, ConnectorError, ValidationError
from satquery.platform.connectors import ConnectorManager, ConnectorPolicy
from satquery.platform.contracts import EarthQuery
from satquery.platform.earth_objects import (
    EarthObjectExtractionPipeline,
    EarthObjectMaterializer,
)
from satquery.platform.perception import PerceptionEngine


def test_firms_bbox_detection_observations_preserve_source_without_claims():
    seen_urls: list[str] = []
    csv_response = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
        "satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        "37.5,-122.2,340.1,0.4,0.3,2025-01-01,2359,N21,VIIRS,n,"
        "2.0NRT,302.3,4.5,D\n"
        "37.6,-122.3,350.2,0.4,0.3,2025-01-02,0001,N21,VIIRS,h,"
        "2.0NRT,305.4,7.2,N\n"
        "37.7,-122.4,360.0,0.4,0.3,2025-01-02,0100,N21,VIIRS,h,"
        "2.0NRT,310.0,8.0,N\n"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=csv_response)

    async def run():
        connector = NasaFirmsConnector(
            configuration={"map_key": "secret-test-key"},
            transport=httpx.MockTransport(handler),
        )
        manager = ConnectorManager()
        manager.register(connector)
        engine = PerceptionEngine(manager)
        result = await engine.observe(
            EarthQuery(
                bbox=(-123, 37, -121, 38),
                temporal_start=datetime(2025, 1, 1, 23, tzinfo=timezone.utc),
                temporal_end=datetime(2025, 1, 2, 0, 30, tzinfo=timezone.utc),
                requested_modalities=("disaster",),
                requested_variables=("active_fire",),
            )
        )
        await manager.stop_all()
        return result

    result = asyncio.run(run())

    assert result.status == "complete", result.failures
    assert result.plan.selected_modalities == ("disaster",)
    assert result.plan.capability_matrix_revision
    assert len(seen_urls) == 1
    assert "/VIIRS_NOAA21_NRT/-123,37,-121,38/2/2025-01-01" in seen_urls[0]
    assert "secret-test-key" in seen_urls[0]
    assert len(result.observations) == 2
    first = result.observations[0]
    assert first.modalities == ("disaster",)
    assert first.observation_type == "satellite_thermal_anomaly"
    assert first.observation_id.startswith("nasa-firms:VIIRS_NOAA21_NRT:")
    assert first.earth_object_candidate is not None
    assert first.earth_object_candidate.object_type == "earth:ThermalAnomalyDetection"
    assert first.earth_object_candidate.provenance["source_attributes"] == first.source_document
    assert first.measured_variables["active_fire"]["value"] == "detected"
    assert first.measured_variables["fire_radiative_power"] == {
        "value": 4.5,
        "unit": "MW",
        "source_unit": "MW",
        "source_name": "frp",
    }
    assert first.measured_variables["brightness_temperature_ti4"]["unit"] == "K"
    assert first.provider_metadata["confidence"] == "n"
    assert first.confidence is None
    assert first.uncertainty == {}
    assert first.source_document["version"] == "2.0NRT"
    assert result.observations[1].observed_at == datetime(
        2025, 1, 2, 0, 1, tzinfo=timezone.utc
    )
    batch = EarthObjectExtractionPipeline().extract(result.observations)
    assert len(batch.declarations) == 2
    extracted = EarthObjectMaterializer().materialize(
        batch.declarations[0],
        tuple(
            observation
            for observation in result.observations
            if observation.observation_id in batch.declarations[0].observation_ids
        ),
    )
    source_observation = next(
        observation
        for observation in result.observations
        if observation.observation_id in batch.declarations[0].observation_ids
    )
    assert extracted.object_type == "earth:ThermalAnomalyDetection"
    assert extracted.geometry == source_observation.geometry
    assert extracted.source_attributes
    assert all(item.uncertainty == {} for item in extracted.source_attributes)
    assert extracted.provenance["declared_provenance"]["extraction_pipeline"][
        "validation_status"
    ] == "not_independently_validated"
    assert extracted.lifecycle == "unknown"


def test_firms_requires_credentials_bounded_geographic_query_and_known_sensor():
    with pytest.raises(AuthenticationError, match="requires a MAP_KEY"):
        asyncio.run(NasaFirmsConnector().authenticate(None))

    connector = NasaFirmsConnector(configuration={"map_key": "test-key"})
    with pytest.raises(ValidationError, match="2D geographic bbox"):
        connector._request_from_query(
            EarthQuery(
                point=(-122, 37),
                temporal_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
            )
        )
    with pytest.raises(ValidationError, match="at most 5 calendar days"):
        connector._request_from_query(
            EarthQuery(
                bbox=(-123, 37, -121, 38),
                temporal_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2025, 1, 6, tzinfo=timezone.utc),
            )
        )
    with pytest.raises(ValidationError, match="allowlist"):
        NasaFirmsConnector(
            configuration={"map_key": "test-key", "source": "UNKNOWN_SENSOR"}
        )


def test_firms_provider_errors_do_not_echo_api_key():
    secret = "secret-test-key"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="provider failure")

    async def run():
        connector = NasaFirmsConnector(
            configuration={"map_key": secret},
            transport=httpx.MockTransport(handler),
        )
        await connector.open()
        try:
            await connector.acquire(
                {
                    "bbox": (-123, 37, -121, 38),
                    "day_count": 1,
                    "start_date": "2025-01-01",
                }
            )
        finally:
            await connector.close()

    with pytest.raises(ConnectorError) as error:
        asyncio.run(run())

    assert secret not in str(error.value)
    assert secret not in str(error.value.context)


def test_firms_is_explicitly_bootstrappable_from_secret_environment(monkeypatch):
    monkeypatch.setenv("SATQUERY_NASA_FIRMS_MAP_KEY", "environment-test-key")
    factory = DEFAULT_CONNECTOR_FACTORIES.get("nasa_firms")

    connector = factory(
        {"implementation": "nasa_firms", "configuration": {}}, ConnectorPolicy()
    )

    assert isinstance(connector, NasaFirmsConnector)
    assert connector.metadata.authentication_required is True
    assert connector.metadata.configuration_schema["map_key"]["secret"] is True
