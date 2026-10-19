import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from connectors.open_meteo import OpenMeteoConnector, OpenMeteoEndpoint
from satquery.errors import ConnectorError, OperationTimeoutError, ValidationError
from satquery.platform import (
    ConnectorManager,
    ConnectorPolicy,
    EarthQuery,
    PerceptionEngine,
    SpatialFeature,
    SpatialIndex,
    SemanticNormalizer,
    TemporalExtent,
    VariableSemantic,
    as_utc,
    bbox_geometry,
    chronological,
    normalize_geometry,
    overlaps,
    rolling_windows,
    simplify_geometry,
    tile_bbox,
)


def test_forecast_rows_normalize_semantics_and_preserve_source_details():
    requests = []
    payload = {
        "latitude": 40.1,
        "longitude": -73.9,
        "elevation": 12.0,
        "timezone": "GMT",
        "timezone_abbreviation": "GMT",
        "utc_offset_seconds": 0,
        "hourly_units": {"temperature_2m": "°C", "precipitation": "mm"},
        "hourly": {
            "time": ["2024-01-01T00:00", "2024-01-01T01:00"],
            "temperature_2m": [3.5, None],
            "precipitation": [0.0, 1.2],
        },
    }

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = OpenMeteoConnector(
            OpenMeteoEndpoint.WEATHER, client=client
        )
        await connector.start()
        query = EarthQuery(
            point=(-73.8, 40.7),
            requested_variables=("air_temperature_2m", "precipitation_amount"),
        )
        result = await connector.observe(query)
        await connector.stop()
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert len(result.observations) == 2
    first, second = result.observations
    assert first.observation_type == "weather_forecast"
    assert first.measured_variables["air_temperature_2m"] == {
        "value": 3.5,
        "unit": "°C",
        "source_name": "temperature_2m",
        "source_unit": "°C",
        "standard_name": "air_temperature",
        "source_metadata": {"standard_name": "air_temperature"},
    }
    assert first.source_document["provider_values"] == {
        "temperature_2m": 3.5,
        "precipitation": 0.0,
    }
    assert second.quality["missing_values"] == ["air_temperature_2m"]
    assert first.geometry["coordinates"] == [-73.9, 40.1]
    assert first.properties["requested_point"] == [-73.8, 40.7]
    params = dict(requests[0].url.params)
    assert params["timezone"] == "GMT"
    assert params["hourly"] == "temperature_2m,precipitation"
    assert params["forecast_days"] == "7"


@pytest.mark.parametrize(
    ("endpoint", "capability", "dataset", "key", "provider_variable", "value"),
    [
        (
            OpenMeteoEndpoint.CLIMATE,
            "climate",
            "climate-projections",
            "daily",
            "temperature_2m_mean",
            13.2,
        ),
        (
            OpenMeteoEndpoint.HYDROLOGY,
            "hydrology",
            "glofas-river-discharge",
            "daily",
            "river_discharge",
            42.0,
        ),
    ],
)
def test_modeled_products_keep_endpoint_provenance_and_units(
    endpoint, capability, dataset, key, provider_variable, value
):
    response = {
        "latitude": 5,
        "longitude": 7,
        "elevation": 100,
        "timezone": "GMT",
        "models": "source-model",
        f"{key}_units": {provider_variable: "m³/s" if key == "daily" and endpoint == OpenMeteoEndpoint.HYDROLOGY else "°C"},
        key: {
            "time": ["2024-03-01"],
            provider_variable: [value],
        },
    }

    async def handler(_request):
        return httpx.Response(200, json=response)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = OpenMeteoConnector(endpoint, client=client)
        manager = ConnectorManager()
        manager.register(connector)
        await connector.start()
        result = await connector.observe(
            EarthQuery(
                point=(7, 5),
                requested_variables=(
                    ("air_temperature_2m_mean",)
                    if endpoint == OpenMeteoEndpoint.CLIMATE
                    else ("river_discharge",)
                ),
                temporal_start=datetime(2024, 3, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2024, 3, 1, 23, 59, tzinfo=timezone.utc),
            )
        )
        await manager.stop_all()
        await client.aclose()
        return result

    result = asyncio.run(run())
    observation = result.observations[0]
    assert observation.observation_type == "model_output"
    assert observation.dataset.dataset_id == dataset
    assert observation.measured_variables
    assert observation.provider_metadata["models"] == "source-model"
    assert observation.reproducibility["endpoint"] == endpoint.value
    assert observation.source_document["provider_values"] == {
        provider_variable: value
    }
    assert (
        observation.temporal_extent.end - observation.temporal_extent.start
        == timedelta(days=1)
    )
    assert capability in OpenMeteoConnector(endpoint).metadata.capabilities


def test_open_meteo_validates_request_shape_variables_and_time_ranges():
    connector = OpenMeteoConnector(OpenMeteoEndpoint.HISTORICAL_WEATHER)
    with pytest.raises(ValidationError, match="geographic point"):
        connector._build_request(EarthQuery(bbox=[0, 0, 1, 1]))
    with pytest.raises(ValidationError, match="both temporal_start"):
        connector._build_request(
            EarthQuery(
                point=(0, 0),
                temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        )
    with pytest.raises(ValidationError, match="does not provide"):
        connector._build_request(
            EarthQuery(
                point=(0, 0),
                temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2024, 1, 2, tzinfo=timezone.utc),
                requested_variables=("river_discharge",),
            )
        )


def test_open_meteo_retries_recoverable_service_failures():
    attempts = 0

    async def handler(_request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "latitude": 1,
                "longitude": 2,
                "hourly_units": {"temperature_2m": "°C"},
                "hourly": {"time": ["2024-01-01T00:00"], "temperature_2m": [10]},
            },
        )

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = OpenMeteoConnector(
            OpenMeteoEndpoint.WEATHER,
            client=client,
            policy=ConnectorPolicy(
                max_attempts=2, retry_safe=True, retry_delay_seconds=0
            ),
        )
        await connector.start()
        result = await connector.observe(
            EarthQuery(point=(2, 1), requested_variables=("air_temperature_2m",))
        )
        await connector.stop()
        await client.aclose()
        return result

    assert len(asyncio.run(run()).observations) == 1
    assert attempts == 2


def test_open_meteo_is_selected_by_capability_and_returns_canonical_observations():
    async def handler(_request):
        return httpx.Response(
            200,
            json={
                "latitude": 1,
                "longitude": 2,
                "hourly_units": {"temperature_2m": "°C"},
                "hourly": {"time": ["2024-01-01T00:00"], "temperature_2m": [10]},
            },
        )

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = OpenMeteoConnector(OpenMeteoEndpoint.WEATHER, client=client)
        manager = ConnectorManager()
        manager.register(connector)
        engine = PerceptionEngine(manager)
        query = EarthQuery(
            point=(2, 1),
            required_capabilities=("weather",),
            requested_variables=("air_temperature_2m",),
        )
        result = await engine.observe(query)
        await manager.stop_all()
        await client.aclose()
        return result

    result = asyncio.run(run())
    assert result.connector_ids == ("open-meteo.weather",)
    assert result.status == "complete"
    assert result.observations[0].provenance["satquery"]["earth_perception"][
        "connector_id"
    ] == "open-meteo.weather"


def test_open_meteo_does_not_hide_non_recoverable_http_failures():
    async def handler(_request):
        return httpx.Response(400, text="bad request")

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = OpenMeteoConnector(OpenMeteoEndpoint.WEATHER, client=client)
        await connector.start()
        try:
            await connector.observe(EarthQuery(point=(2, 1)))
        finally:
            await connector.stop()
            await client.aclose()

    with pytest.raises(ConnectorError, match="rejected the request"):
        asyncio.run(run())


def test_open_meteo_uses_connector_timeout_policy():
    async def handler(_request):
        await asyncio.sleep(0.02)
        return httpx.Response(200, json={})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = OpenMeteoConnector(
            OpenMeteoEndpoint.WEATHER,
            client=client,
            policy=ConnectorPolicy(timeout_seconds=0.001),
        )
        await connector.start()
        try:
            await connector.observe(EarthQuery(point=(2, 1)))
        finally:
            await connector.stop()
            await client.aclose()

    with pytest.raises(OperationTimeoutError):
        asyncio.run(run())


def test_semantic_normalization_preserves_original_variable_and_unit():
    normalizer = SemanticNormalizer(
        {"rain": VariableSemantic("precipitation_amount", "precipitation_flux")}
    )
    normalized = normalizer.normalize_measurement(
        "Rain", 3.0, unit="mm/day", metadata={"quality": "estimated"}
    )
    assert normalized["precipitation_amount"] == {
        "value": 3.0,
        "unit": "mm/day",
        "source_name": "Rain",
        "source_unit": "mm/day",
        "standard_name": "precipitation_flux",
        "source_metadata": {"quality": "estimated"},
    }


def test_temporal_helpers_handle_utc_windows_overlap_and_chronology():
    start = datetime(2024, 1, 1, tzinfo=timezone(timedelta(hours=2)))
    end = start + timedelta(hours=5)
    windows = rolling_windows(start, end, width=timedelta(hours=2))
    assert len(windows) == 3
    assert windows[0].start == as_utc(start)
    assert overlaps(
        TemporalExtent(start=windows[0].start, end=windows[0].end),
        TemporalExtent(start=windows[1].start, end=windows[1].end),
    )
    values = [{"at": end}, {"at": start}]
    assert chronological(values, timestamp=lambda item: item["at"]) == (
        values[1],
        values[0],
    )
    with pytest.raises(ValueError, match="timezone"):
        as_utc(datetime(2024, 1, 1))


def test_spatial_helpers_reproject_tile_simplify_and_index():
    polygon_3857 = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0]]
        ],
    }
    geographic = normalize_geometry(
        polygon_3857, source_crs="EPSG:3857", target_crs="OGC:CRS84"
    )
    assert geographic["type"] == "Polygon"
    assert geographic["coordinates"][0][1][0] > 0
    assert bbox_geometry((0, 0, 1, 1))["type"] == "Polygon"
    assert tile_bbox((0, 0, 5, 3), tile_width=2, tile_height=2) == (
        (0, 0, 2, 2),
        (2, 0, 4, 2),
        (4, 0, 5, 2),
        (0, 2, 2, 3),
        (2, 2, 4, 3),
        (4, 2, 5, 3),
    )
    simplified = simplify_geometry(geographic, tolerance=0.00001)
    index = SpatialIndex(
        (
            SpatialFeature("inside", geographic, {}),
            SpatialFeature(
                "outside",
                {
                    "type": "Point",
                    "coordinates": [10, 10],
                },
                {},
            ),
        ),
        crs="OGC:CRS84",
    )
    assert simplified["type"] == "Polygon"
    assert [feature.feature_id for feature in index.query(geographic)] == ["inside"]
