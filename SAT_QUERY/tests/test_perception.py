import asyncio
import io
import json
from datetime import datetime, timezone

import httpx
import pytest
from connectors.image_fetcher.connector import ImageFetcherConnector
from connectors.stac import StacCatalogConnector
from PIL import Image
from pydantic import ValidationError as PydanticValidationError
from satquery.errors import ConnectorError
from satquery.platform import (
    ConnectorManager,
    ConnectorMetadata,
    DatasetReference,
    EarthQuery,
    MemoryObservationCache,
    Observation,
    ObservationSearchResult,
    PerceptionConnector,
    PerceptionEngine,
    TemporalExtent,
    query_fingerprint,
)


class DemoPerceptionConnector(PerceptionConnector):
    def __init__(
        self,
        connector_id,
        *,
        capabilities=("imagery",),
        priority=0,
        health="healthy",
        available=True,
        regions=(),
        variables=(),
        temporal_start=None,
        temporal_end=None,
        result=None,
        error=None,
    ):
        super().__init__()
        self.connector_id = connector_id
        self._capabilities = capabilities
        self._priority = priority
        self._health = health
        self._available = available
        self._regions = regions
        self._variables = variables
        self._temporal_start = temporal_start
        self._temporal_end = temporal_end
        self.result = result or ObservationSearchResult()
        self.error = error
        self.calls = 0

    @property
    def metadata(self):
        return ConnectorMetadata(
            connector_id=self.connector_id,
            name=self.connector_id,
            version="1",
            capabilities=self._capabilities,
            priority=self._priority,
            health=self._health,
            available=self._available,
            supported_regions=self._regions,
            supported_spatial_types=("bbox", "point", "geometry"),
            supports_temporal_query=True,
            supported_query_fields=(
                "spatial_resolution",
                "filters",
                "asset_preferences",
            ),
            supported_variables=self._variables,
            temporal_start=self._temporal_start,
            temporal_end=self._temporal_end,
            provider_version="provider-v1",
            provider_metadata={"provider": f"provider-{self.connector_id}"},
        )

    async def discover(self):
        return (
            DatasetReference(
                connector_id=self.connector_id,
                dataset_id="dataset",
            ),
        )

    async def acquire(self, request):
        return self.result

    async def observe(self, query):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def make_observation(*, observation_id="one", source_id="source-1"):
    return Observation(
        observation_id=observation_id,
        source_id=source_id,
        observed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        temporal_extent=TemporalExtent(
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ),
        geometry={"type": "Point", "coordinates": [10, 20]},
        crs="OGC:CRS84",
        observation_type="imagery",
        measured_variables={"red": {"unit": "reflectance", "value": 0.2}},
        confidence=None,
        provenance={"satquery": {"source_field": "preserve-me"}},
        reproducibility={"satquery": {"source_record": "preserve-me"}},
        properties={"datetime": "2024-01-01T00:00:00Z"},
        source_document={"source_item": source_id},
    )


def test_earth_query_validates_spatial_temporal_and_unique_selectors():
    with pytest.raises(PydanticValidationError, match="only one"):
        EarthQuery(bbox=[0, 0, 1, 1], point=[0, 0])
    with pytest.raises(PydanticValidationError, match="longitude/latitude"):
        EarthQuery(point=[181, 0])
    with pytest.raises(PydanticValidationError, match="finite numeric"):
        EarthQuery(geometry={"type": "Point", "coordinates": ["10", 20]})
    with pytest.raises(PydanticValidationError, match="temporal_start"):
        EarthQuery(temporal_start=datetime(2024, 1, 1))
    with pytest.raises(PydanticValidationError, match="unique"):
        EarthQuery(requested_variables=("rain", "rain"))
    assert EarthQuery(bbox=[170, -10, -170, 10]).bbox == (170, -10, -170, 10)
    assert EarthQuery(bbox=[100000, 200000, 110000, 210000], crs="EPSG:3857")


def test_query_fingerprint_is_canonical_and_includes_query_semantics():
    first = EarthQuery(
        required_capabilities=("imagery",),
        filters={"cloud_cover": {"lt": 10}, "platform": "sentinel"},
    )
    second = EarthQuery(
        filters={"platform": "sentinel", "cloud_cover": {"lt": 10}},
        required_capabilities=("imagery",),
    )
    equivalent_time = EarthQuery(
        temporal_start=datetime.fromisoformat("2024-01-01T12:00:00+02:00")
    )
    utc_time = EarthQuery(
        temporal_start=datetime.fromisoformat("2024-01-01T10:00:00+00:00")
    )
    changed = first.model_copy(update={"region": "north"})
    assert query_fingerprint(first) == query_fingerprint(second)
    assert query_fingerprint(equivalent_time) == query_fingerprint(utc_time)
    assert query_fingerprint(first) != query_fingerprint(changed)


def test_capability_selection_is_filtered_and_deterministic():
    async def run():
        manager = ConnectorManager()
        lower = DemoPerceptionConnector("z-lower", priority=1)
        high = DemoPerceptionConnector(
            "a-high",
            priority=10,
            regions=("north",),
            variables=("rain",),
            temporal_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            temporal_end=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        degraded = DemoPerceptionConnector(
            "b-degraded", priority=10, health="degraded", regions=("north",),
            variables=("rain",),
        )
        unavailable = DemoPerceptionConnector("unavailable", available=False)
        unhealthy = DemoPerceptionConnector("unhealthy", health="unhealthy")
        for connector in (lower, high, degraded, unavailable, unhealthy):
            manager.register(connector)
        engine = PerceptionEngine(manager)
        query = EarthQuery(
            required_capabilities=("imagery",),
            requested_variables=("rain",),
            region="north",
            temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert [
            connector.connector_id for connector in engine.select_connectors(query)
        ] == ["a-high", "b-degraded"]
        await manager.stop_all()

    asyncio.run(run())


def test_selection_strategy_can_be_replaced_without_platform_changes():
    async def run():
        manager = ConnectorManager()
        manager.register(DemoPerceptionConnector("first"))
        manager.register(DemoPerceptionConnector("second"))

        class SingleSourceSelector:
            def select(self, query, connectors):
                return tuple(sorted(connectors, key=lambda item: item.connector_id)[:1])

        engine = PerceptionEngine(manager, selector=SingleSourceSelector())
        selected = engine.select_connectors(EarthQuery())
        assert [item.connector_id for item in selected] == ["first"]
        await manager.stop_all()

    asyncio.run(run())


def test_source_selection_excludes_unsupported_query_shapes_and_fields():
    async def run():
        manager = ConnectorManager()
        manager.register(
            ImageFetcherConnector(configuration={"output_dir": "images"})
        )
        manager.register(
            StacCatalogConnector(
                configuration={"catalog_url": "https://catalog.example/stac"},
                transport=httpx.MockTransport(lambda request: httpx.Response(500)),
            )
        )
        engine = PerceptionEngine(manager)
        point_imagery = EarthQuery(
            required_capabilities=("imagery",), point=(10, 20)
        )
        bbox_catalog = EarthQuery(
            required_capabilities=("observation-search",), bbox=[10, 20, 11, 21]
        )
        time_filtered_imagery = EarthQuery(
            required_capabilities=("imagery",),
            point=(10, 20),
            temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert [
            item.metadata.connector_id
            for item in engine.select_connectors(point_imagery)
        ] == ["image-fetcher"]
        assert [
            item.metadata.connector_id
            for item in engine.select_connectors(bbox_catalog)
        ] == ["stac-catalog"]
        assert engine.select_connectors(time_filtered_imagery) == ()
        await manager.stop_all()

    asyncio.run(run())


def test_observation_acquisition_preserves_provenance_and_merges_exact_duplicates():
    async def run():
        manager = ConnectorManager()
        first = DemoPerceptionConnector(
            "source-a", result=ObservationSearchResult(observations=(make_observation(),))
        )
        duplicate = DemoPerceptionConnector(
            "source-b",
            result=ObservationSearchResult(
                observations=(make_observation(observation_id="two", source_id="source-2"),)
            ),
        )
        manager.register(first)
        manager.register(duplicate)
        result = await PerceptionEngine(manager).observe(
            EarthQuery(required_capabilities=("imagery",))
        )
        assert result.status == "complete"
        assert len(result.observations) == 1
        assert result.duplicate_count == 1
        merged = result.observations[0]
        assert merged.confidence is None
        assert merged.source_document == {"source_item": "source-1"}
        assert merged.provenance["satquery"]["earth_perception"]["provider"] == (
            "provider-source-a"
        )
        assert merged.provenance["satquery"]["source_field"] == "preserve-me"
        assert merged.reproducibility["satquery"]["earth_perception"]["query_fingerprint"] == (
            result.query_fingerprint
        )
        assert merged.reproducibility["satquery"]["source_record"] == "preserve-me"
        sources = merged.provenance["satquery"]["earth_perception"]["merged_sources"]
        assert [source["source_document"]["source_item"] for source in sources] == [
            "source-1",
            "source-2",
        ]
        await manager.stop_all()

    asyncio.run(run())


def test_perception_cache_uses_canonical_fingerprint_and_marks_hits():
    async def run():
        manager = ConnectorManager()
        connector = DemoPerceptionConnector(
            "cached",
            result=ObservationSearchResult(observations=(make_observation(),)),
        )
        manager.register(connector)
        engine = PerceptionEngine(manager, cache=MemoryObservationCache())
        query = EarthQuery(required_capabilities=("imagery",))
        first = await engine.observe(query)
        second = await engine.observe(query)
        assert not first.cache_hit
        assert second.cache_hit
        assert connector.calls == 1
        assert (
            first.observations[0].provenance["satquery"]["earth_perception"][
                "capability_matrix_revision"
            ]
            == first.plan.capability_matrix_revision
        )

        replacement = DemoPerceptionConnector(
            "cached",
            priority=1,
            result=ObservationSearchResult(observations=(make_observation(),)),
        )
        manager.registry.register("cached", replacement, replace=True)
        refreshed = await engine.observe(query)
        assert not refreshed.cache_hit
        assert replacement.calls == 1
        assert (
            refreshed.plan.capability_matrix_revision
            != first.plan.capability_matrix_revision
        )
        await manager.stop_all()

    asyncio.run(run())


def test_connector_errors_are_returned_as_explicit_partial_failures():
    async def run():
        manager = ConnectorManager()
        working = DemoPerceptionConnector(
            "working",
            result=ObservationSearchResult(observations=(make_observation(),)),
        )
        broken = DemoPerceptionConnector(
            "broken", error=ConnectorError("catalog unavailable", recoverable=True)
        )
        manager.register(working)
        manager.register(broken)
        result = await PerceptionEngine(manager).observe(
            EarthQuery(required_capabilities=("imagery",))
        )
        assert result.status == "partial"
        assert len(result.observations) == 1
        assert result.failures[0].connector_id == "broken"
        assert "catalog unavailable" in result.failures[0].message
        await manager.stop_all()

    asyncio.run(run())


def test_unsupported_capabilities_fail_instead_of_returning_empty_success():
    async def run():
        manager = ConnectorManager()
        manager.register(DemoPerceptionConnector("imagery"))
        engine = PerceptionEngine(manager)
        with pytest.raises(ConnectorError, match="No available perception connector"):
            await engine.observe(
                EarthQuery(required_capabilities=("hydrology",))
            )
        await manager.stop_all()

    asyncio.run(run())


def test_acquisition_parallelism_respects_configured_concurrency():
    async def run():
        active = 0
        maximum_active = 0

        class DelayedConnector(DemoPerceptionConnector):
            async def observe(self, query):
                nonlocal active, maximum_active
                active += 1
                maximum_active = max(maximum_active, active)
                await asyncio.sleep(0.01)
                active -= 1
                return self.result

        manager = ConnectorManager()
        for connector_id in ("first", "second", "third"):
            manager.register(DelayedConnector(connector_id))
        await PerceptionEngine(manager, max_concurrency=1).observe(
            EarthQuery(required_capabilities=("imagery",))
        )
        assert maximum_active == 1
        await manager.stop_all()

    asyncio.run(run())


def test_perception_stream_yields_canonical_observations_with_provenance():
    async def run():
        manager = ConnectorManager()
        connector = DemoPerceptionConnector(
            "streamer",
            result=ObservationSearchResult(
                observations=(make_observation(), make_observation(observation_id="two"))
            ),
        )
        manager.register(connector)
        engine = PerceptionEngine(manager)
        observations = [
            item
            async for item in engine.stream(
                EarthQuery(required_capabilities=("imagery",))
            )
        ]
        assert len(observations) == 2
        assert all(
            item.provenance["satquery"]["earth_perception"]["connector_id"] == "streamer"
            for item in observations
        )
        await manager.stop_all()

    asyncio.run(run())


def test_perception_stream_batches_preserve_order_and_reject_invalid_sizes():
    async def run():
        manager = ConnectorManager()
        connector = DemoPerceptionConnector(
            "batch-streamer",
            result=ObservationSearchResult(
                observations=(
                    make_observation(observation_id="one"),
                    make_observation(observation_id="two"),
                    make_observation(observation_id="three"),
                )
            ),
        )
        manager.register(connector)
        engine = PerceptionEngine(manager)
        batches = [
            batch
            async for batch in engine.stream_batches(
                EarthQuery(required_capabilities=("imagery",)), batch_size=2
            )
        ]
        assert [len(batch) for batch in batches] == [2, 1]
        assert [item.observation_id for batch in batches for item in batch] == [
            "one",
            "two",
            "three",
        ]
        with pytest.raises(ValueError, match="positive integer"):
            async for _ in engine.stream_batches(
                EarthQuery(required_capabilities=("imagery",)), batch_size=1.5
            ):
                pass
        await manager.stop_all()

    asyncio.run(run())


def test_stac_connector_translates_earth_query_to_canonical_observations():
    async def run():
        search_requests = []

        def handler(request):
            if request.url.path == "/catalog/":
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
            if request.url.path == "/catalog/collections":
                return httpx.Response(
                    200,
                    json={"collections": [{"id": "sentinel-2"}], "links": []},
                    request=request,
                )
            search_requests.append(request)
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "item-1",
                            "collection": "sentinel-2",
                            "geometry": None,
                            "bbox": [10, 20, 11, 21],
                            "properties": {
                                "datetime": "2024-01-01T00:00:00Z",
                                "start_datetime": "2024-01-01T00:00:00Z",
                                "end_datetime": "2024-01-01T01:00:00Z",
                            },
                            "assets": {},
                            "links": [],
                        }
                    ],
                    "links": [],
                },
                request=request,
            )

        manager = ConnectorManager()
        manager.register(
            StacCatalogConnector(
                configuration={"catalog_url": "https://catalog.example/catalog"},
                transport=httpx.MockTransport(handler),
            )
        )
        query = EarthQuery(
            required_capabilities=("observation-search",),
            bbox=[10, 20, 11, 21],
            temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            temporal_end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        result = await PerceptionEngine(manager).observe(query)
        observation = result.observations[0]
        assert search_requests[0].method == "POST"
        assert search_requests[0].url.path == "/catalog/search"
        assert json.loads(search_requests[0].content) == {
            "bbox": [10, 20, 11, 21],
            "datetime": "2024-01-01T00:00:00Z/2024-01-02T00:00:00Z",
        }
        assert observation.source_id == "item-1"
        assert observation.temporal_extent is not None
        assert observation.temporal_extent.end == datetime(
            2024, 1, 1, 1, tzinfo=timezone.utc
        )
        assert observation.provenance["protocol"] == "STAC API"
        assert observation.source_document["id"] == "item-1"
        await manager.stop_all()

    asyncio.run(run())


def test_esri_image_fetcher_is_exposed_as_a_point_imagery_observation(
    monkeypatch, tmp_path
):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.payload

    image_buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (50, 100, 150)).save(image_buffer, format="JPEG")
    monkeypatch.setattr(
        "connectors.image_fetcher.satellite_fetcher.urlopen",
        lambda request, timeout: FakeResponse(image_buffer.getvalue()),
    )

    async def run():
        manager = ConnectorManager()
        manager.register(
            ImageFetcherConnector(
                configuration={"output_dir": str(tmp_path), "image_size": 512}
            )
        )
        result = await PerceptionEngine(manager).observe(
            EarthQuery(required_capabilities=("imagery",), point=(72.8656, 19.0896))
        )
        assert result.status == "complete", result.failures
        observation = result.observations[0]
        assert observation.observation_type == "imagery"
        assert observation.observed_at is None
        assert observation.geometry is None
        assert observation.properties["requested_location"] == {
            "type": "Point",
            "coordinates": [72.8656, 19.0896],
        }
        assert observation.assets["image"].uri.startswith("file:///")
        assert observation.provenance["provider"] == "Esri World Imagery"
        assert observation.source_document["metadata"]["path"]
        await manager.stop_all()

    asyncio.run(run())
