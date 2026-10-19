import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from connectors import (
    CopernicusDataSpaceConnector,
    NasaEarthdataConnector,
    OverpassConnector,
    PlanetaryComputerConnector,
    UsGSLandsatConnector,
)
from satquery.errors import AuthenticationError, NetworkError, ValidationError
from satquery.platform import (
    ConnectorManager,
    DatasetMetadata,
    EarthQuery,
    InMemoryDatasetRegistry,
    PerceptionEngine,
    SemanticNormalizer,
)
from satquery.platform.ontology import EARTH_VARIABLE_ONTOLOGY


STAC_ADAPTERS = (
    (PlanetaryComputerConnector, "Microsoft Planetary Computer", "imagery"),
    (CopernicusDataSpaceConnector, "Copernicus Data Space Ecosystem", "imagery"),
    (UsGSLandsatConnector, "USGS LandsatLook", "landsat"),
)


def _stac_transport(collection_id, authorization=None):
    def handler(request):
        if request.url.path.endswith("/stac/"):
            return httpx.Response(
                200,
                json={
                    "type": "Catalog",
                    "links": [
                        {"rel": "search", "href": "search", "method": "POST"},
                        {"rel": "data", "href": "collections"},
                    ],
                },
                request=request,
            )
        if request.url.path.endswith("/collections"):
            return httpx.Response(
                200,
                json={
                    "collections": [
                        {
                            "id": collection_id,
                            "title": "Verified Earth collection",
                            "description": "Test metadata",
                            "license": "CC-BY-4.0",
                            "keywords": ["imagery", "satellite", "NDVI"],
                            "sci:doi": "10.1234/example",
                            "summaries": {"gsd": [10, 20]},
                            "extent": {
                                "spatial": {"bbox": [[-180, -90, 180, 90]]},
                                "temporal": {
                                    "interval": [["2000-01-01T00:00:00Z", None]]
                                },
                            },
                        }
                    ],
                    "links": [],
                },
                request=request,
            )
        if request.url.path.endswith("/search"):
            assert request.headers.get("Authorization") == authorization
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "context": {"matched": 1},
                    "features": [
                        {
                            "type": "Feature",
                            "id": "product-1",
                            "collection": collection_id,
                            "geometry": {
                                "type": "Point",
                                "coordinates": [12, 45],
                            },
                            "bbox": [12, 45, 12, 45],
                            "properties": {
                                "datetime": "2024-01-01T00:00:00Z",
                                "platform": "source-mission",
                            },
                            "assets": {
                                "data": {
                                    "href": "https://assets.example/product.tif",
                                    "type": "image/tiff",
                                    "roles": ["data"],
                                },
                                "metadata": {
                                    "href": "https://assets.example/product.json",
                                    "type": "application/json",
                                    "roles": ["metadata"],
                                },
                            },
                        }
                    ],
                    "links": [],
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(("connector_class", "provider", "capability"), STAC_ADAPTERS)
def test_public_stac_provider_adapters_register_catalog_metadata_and_assets(
    connector_class, provider, capability
):
    async def run():
        connector = connector_class(
            configuration={
                "catalog_url": "https://provider.test/stac/",
                "connector_id": "provider-test",
            },
            transport=_stac_transport("collection-1"),
        )
        manager = ConnectorManager()
        manager.register(connector)
        references = await manager.discover("provider-test")
        registry = manager.dataset_registry
        dataset = registry.get("provider-test", "collection-1")
        result = await PerceptionEngine(manager).observe(
            EarthQuery(
                point=(12, 45),
                required_capabilities=(capability,),
                requested_variables=("ndvi",),
            )
        )
        await manager.stop_all()
        return connector, references, dataset, result

    connector, references, dataset, result = asyncio.run(run())
    assert connector.metadata.provider_metadata["provider"] == provider
    assert references[0].dataset_id == "collection-1"
    assert "ndvi" in connector.metadata.supported_variables
    assert dataset.provider == provider
    assert dataset.metadata["title"] == "Verified Earth collection"
    assert dataset.keywords == ("imagery", "satellite", "NDVI")
    assert dataset.crs == "OGC:CRS84"
    assert dataset.temporal_coverage.start.year == 2000
    assert dataset.variables == ("ndvi",)
    assert dataset.categories == ("vegetation",)
    assert dataset.spatial_resolution is None
    assert dataset.metadata["spatial_resolutions"] == [10.0, 20.0]
    assert dataset.citation == "10.1234/example"
    assert "NDVI" in dataset.metadata["source_variable_terms"]
    assert result.status == "complete", result.failures
    item = result.observations[0]
    assert item.dataset.dataset_id == "collection-1"
    assert set(item.assets) == {"data", "metadata"}
    assert item.quality_assessment is not None
    assert item.quality_assessment.confidence is None
    assert item.provenance["satquery"]["earth_perception"]["provider"] == provider
    assert item.source_document["properties"]["platform"] == "source-mission"


def test_copernicus_bearer_authentication_is_applied_when_configured():
    async def run():
        connector = CopernicusDataSpaceConnector(
            configuration={
                "catalog_url": "https://provider.test/stac/",
                "connector_id": "cdse-auth",
                "authentication_required": True,
            },
            transport=_stac_transport(
                "sentinel-2-l2a", authorization="Bearer access-token"
            ),
        )
        manager = ConnectorManager()
        manager.register(connector)
        with pytest.raises(AuthenticationError):
            await manager.start("cdse-auth")
        await manager.start("cdse-auth", {"token": "access-token"})
        await manager.discover("cdse-auth")
        await manager.acquire(
            "cdse-auth",
            {"collections": ["sentinel-2-l2a"]},
        )
        await manager.stop_all()

    asyncio.run(run())


@pytest.mark.parametrize(
    "connector_class",
    tuple(connector_class for connector_class, _, _ in STAC_ADAPTERS),
)
def test_stac_provider_services_report_unavailability(connector_class):
    async def handler(request):
        return httpx.Response(503, request=request)

    async def run():
        connector = connector_class(
            configuration={"catalog_url": "https://provider.test/stac/"},
            transport=httpx.MockTransport(handler),
        )
        manager = ConnectorManager()
        manager.register(connector)
        with pytest.raises(NetworkError):
            await manager.discover(connector.metadata.connector_id)
        await manager.stop_all()

    asyncio.run(run())


def test_stac_health_probe_records_availability_and_latency():
    async def run():
        connector = PlanetaryComputerConnector(
            configuration={"catalog_url": "https://provider.test/stac/"},
            transport=_stac_transport("collection-1"),
        )
        manager = ConnectorManager()
        manager.register(connector)
        await manager.start(connector.metadata.connector_id)
        snapshot = (await manager.health_snapshot(active=True))[0]
        await manager.stop_all()
        return snapshot

    snapshot = asyncio.run(run())
    assert snapshot.health == "healthy"
    assert snapshot.availability_ratio == 1
    assert snapshot.health_probe_count == 1
    assert snapshot.last_health_probe_duration_seconds is not None


def test_stac_health_probe_records_service_failure():
    async def handler(request):
        return httpx.Response(503, request=request)

    async def run():
        connector = PlanetaryComputerConnector(
            configuration={"catalog_url": "https://provider.test/stac/"},
            transport=httpx.MockTransport(handler),
        )
        manager = ConnectorManager()
        manager.register(connector)
        await manager.start(connector.metadata.connector_id)
        snapshot = (await manager.health_snapshot(active=True))[0]
        await manager.stop_all()
        return snapshot

    snapshot = asyncio.run(run())
    assert snapshot.health == "unhealthy"
    assert snapshot.availability_ratio == 0
    assert snapshot.health_probe_count == 1
    assert snapshot.metadata["active_probe"] == "failed"


def test_nasa_cmr_discovers_collections_and_returns_canonical_granule_assets():
    async def handler(request):
        if request.url.path.endswith("/collections.json"):
            assert request.url.params["scroll"] == "true"
            if request.headers.get("CMR-Search-After") == "cursor-1":
                return httpx.Response(
                    200,
                    json={
                        "feed": {
                            "hits": 2,
                            "entry": [
                                {
                                    "id": "C124-PROVIDER",
                                    "short_name": "MOD13Q1",
                                    "version_id": "061",
                                    "time_start": "2000-02-18T00:00:00Z",
                                    "time_end": "2026-12-31T00:00:00Z",
                                }
                            ],
                        },
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                headers={"CMR-Search-After": "cursor-1"},
                json={
                    "feed": {
                        "hits": 2,
                        "entry": [
                            {
                                "id": "C123-PROVIDER",
                                "short_name": "MOD13Q1",
                                "version_id": "061",
                                "summary": "Vegetation indices",
                                "science_keywords": [{"topic": "Vegetation"}],
                                "time_start": "2000-02-18T00:00:00Z",
                                "time_end": "2026-12-31T00:00:00Z",
                                "boxes": ["-90 -180 90 180"],
                            }
                        ],
                    }
                },
                request=request,
            )
        assert request.url.path.endswith("/granules.json")
        assert request.url.params["collection_concept_id"] == "C123-PROVIDER"
        assert request.url.params["point"] == "12.0,45.0"
        return httpx.Response(
            200,
            json={
                "feed": {
                    "hits": 1,
                    "entry": [
                        {
                            "id": "G123-PROVIDER",
                            "collection_concept_id": "C123-PROVIDER",
                            "time_start": "2024-01-01T00:00:00Z",
                            "time_end": "2024-01-17T23:59:59Z",
                            "polygons": [
                                "40 -70 41 -70 41 -69 40 -70"
                            ],
                            "links": [
                                {
                                    "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                                    "href": "https://data.example/granule.hdf",
                                    "type": "application/x-hdf",
                                },
                                {
                                    "rel": "http://esipfed.org/ns/fedsearch/1.1/browse#",
                                    "href": "https://data.example/preview.jpg",
                                    "type": "image/jpeg",
                                },
                            ],
                        }
                    ],
                }
            },
            request=request,
        )

    async def run():
        connector = NasaEarthdataConnector(
            configuration={"collection_concept_ids": ["C123-PROVIDER"]},
            transport=httpx.MockTransport(handler),
        )
        manager = ConnectorManager()
        manager.register(connector)
        references = await manager.discover("nasa-earthdata")
        result = await PerceptionEngine(manager).observe(
            EarthQuery(
                point=(12, 45),
                temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                temporal_end=datetime(2024, 1, 31, tzinfo=timezone.utc),
                required_capabilities=("earth_observation_catalog",),
            )
        )
        dataset = manager.dataset_registry.get(
            "nasa-earthdata", "C123-PROVIDER"
        )
        await manager.stop_all()
        return references, dataset, result

    references, dataset, result = asyncio.run(run())
    assert {reference.dataset_id for reference in references} == {
        "C123-PROVIDER",
        "C124-PROVIDER",
    }
    assert dataset.provider == "NASA Earthdata"
    assert dataset.keywords == ("Vegetation",)
    assert result.status == "complete", result.failures
    granule = result.observations[0]
    assert granule.source_id == "G123-PROVIDER"
    assert granule.geometry["type"] == "Polygon"
    assert granule.assets["data-0"].uri.endswith(".hdf")
    assert granule.assets["preview-1"].roles == ("preview",)
    assert granule.confidence is None
    assert granule.quality_assessment.confidence is None
    assert granule.source_document["id"] == "G123-PROVIDER"


def test_nasa_earthdata_authentication_and_unavailable_service_are_explicit():
    seen = []

    async def handler(request):
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(503, request=request)

    async def run():
        connector = NasaEarthdataConnector(
            configuration={"authentication_required": True},
            transport=httpx.MockTransport(handler),
        )
        manager = ConnectorManager()
        manager.register(connector)
        with pytest.raises(AuthenticationError):
            await manager.start("nasa-earthdata")
        await manager.start("nasa-earthdata", {"token": "earthdata-token"})
        with pytest.raises(NetworkError):
            await manager.discover("nasa-earthdata")
        await manager.stop_all()

    asyncio.run(run())
    assert seen == ["Bearer earthdata-token"]


def test_overpass_generates_provider_query_and_canonical_vector_observations():
    requests = []

    async def handler(request):
        requests.append(parse_qs(request.content.decode())["data"][0])
        return httpx.Response(
            200,
            json={
                "version": 0.6,
                "osm3s": {"timestamp_osm_base": "2025-02-01T10:00:00Z"},
                "elements": [
                    {
                        "type": "node",
                        "id": 123,
                        "lat": 40.1,
                        "lon": -73.9,
                        "version": 7,
                        "timestamp": "2025-01-31T00:00:00Z",
                        "tags": {"highway": "traffic_signals"},
                    },
                    {
                        "type": "way",
                        "id": 456,
                        "version": 3,
                        "geometry": [
                            {"lat": 40.0, "lon": -74.0},
                            {"lat": 40.1, "lon": -73.9},
                        ],
                        "tags": {"highway": "primary", "name": "Main Street"},
                    },
                ],
            },
            request=request,
        )

    async def run():
        connector = OverpassConnector(
            transport=httpx.MockTransport(handler)
        )
        manager = ConnectorManager()
        manager.register(connector)
        references = await manager.discover("openstreetmap-overpass")
        result = await PerceptionEngine(manager).observe(
            EarthQuery(
                bbox=(-74, 40, -73, 41),
                required_capabilities=("vector",),
                filters={"osm_tags": {"highway": ["primary", "traffic_signals"]}},
            )
        )
        dataset = manager.dataset_registry.get(
            "openstreetmap-overpass", "osm-map-features"
        )
        await manager.stop_all()
        return references, dataset, result

    references, dataset, result = asyncio.run(run())
    assert references[0].dataset_id == "osm-map-features"
    assert dataset.provider == "OpenStreetMap"
    assert result.status == "complete", result.failures
    assert len(result.observations) == 2
    assert "way(40.00000000,-74.00000000,41.00000000,-73.00000000)" in requests[0]
    assert '["highway"="primary"]' in requests[0]
    assert result.observations[0].geometry["type"] == "Point"
    assert result.observations[1].geometry["type"] == "LineString"
    assert result.observations[1].properties["tags"]["name"] == "Main Street"
    assert result.observations[0].assets["metadata"].uri.endswith("/node/123")
    assert result.observations[0].quality_assessment.confidence is None


def test_overpass_unavailable_service_and_unrepresentable_query_fail():
    async def handler(request):
        return httpx.Response(503, request=request)

    async def run():
        connector = OverpassConnector(transport=httpx.MockTransport(handler))
        manager = ConnectorManager()
        manager.register(connector)
        with pytest.raises(ValidationError):
            connector._build_query(
                EarthQuery(
                    geometry={
                        "type": "Polygon",
                        "coordinates": [
                            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
                            [[0.2, 0.2], [0.3, 0.2], [0.3, 0.3], [0.2, 0.2]],
                        ],
                    }
                )
            )
        await manager.start("openstreetmap-overpass")
        with pytest.raises(NetworkError):
            await connector.observe(
                EarthQuery(bbox=(-1, -1, 1, 1))
            )
        await manager.stop_all()

    asyncio.run(run())


def test_earth_variable_ontology_resolves_known_aliases_and_refuses_ambiguous_term():
    assert EARTH_VARIABLE_ONTOLOGY.resolve_variable("T2M").canonical_name == (
        "air_temperature"
    )
    assert EARTH_VARIABLE_ONTOLOGY.resolve_variable(
        "surface_temperature"
    ).canonical_name == "land_surface_temperature"
    assert len(EARTH_VARIABLE_ONTOLOGY.variable_aliases("temperature")) == 2
    assert EARTH_VARIABLE_ONTOLOGY.resolve_variable("temperature") is None
    normalized = SemanticNormalizer().normalize_measurement(
        "TMP", 280, unit="K"
    )
    assert normalized["air_temperature"]["value"] == 280
    assert normalized["air_temperature"]["source_name"] == "TMP"
    assert normalized["air_temperature"]["ontology_uri"].startswith("https://")
    assert "atmosphere" in {
        concept.concept_id for concept in EARTH_VARIABLE_ONTOLOGY.concepts
    }
    for concept_id in (
        "agriculture",
        "geology",
        "biodiversity",
        "transportation",
        "energy",
    ):
        metadata = EARTH_VARIABLE_ONTOLOGY.concept_metadata(concept_id)
        assert metadata is not None
        assert metadata["canonical_variables"]
    # Phenomenon classes do not imply a unique measured variable. Keep those
    # mappings explicitly empty until a versioned scientific mapping is supplied.
    for phenomenon in (
        "cyclone",
        "drought",
        "earthquake",
        "flood",
        "heatwave",
        "landslide",
        "marine_heatwave",
        "storm",
        "volcanic_activity",
    ):
        assert EARTH_VARIABLE_ONTOLOGY.concept_metadata(phenomenon)[
            "canonical_variables"
        ] == ()
    assert (
        EARTH_VARIABLE_ONTOLOGY.resolve_variable("population_density").concept_id
        == "human_geography"
    )


def test_dataset_search_uses_unambiguous_ontology_aliases_only():
    registry = InMemoryDatasetRegistry(
        (
            DatasetMetadata(
                connector_id="test",
                dataset_id="air-temperature",
                provider="Test",
                variables=("air_temperature",),
            ),
        )
    )
    assert len(
        registry.search(EarthQuery(requested_variables=("t2m",)))
    ) == 1
    assert registry.search(EarthQuery(requested_variables=("temperature",))) == ()
