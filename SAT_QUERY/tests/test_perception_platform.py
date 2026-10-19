import asyncio
import importlib.metadata
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from satquery.errors import ConnectorError
from satquery.platform import (
    AreaOfInterest,
    AssetCatalog,
    AssetQuery,
    AuthenticationProvider,
    ConnectorManager,
    ConnectorMetadata,
    ConnectorPolicy,
    DatasetReference,
    DatasetMetadata,
    EarthQuery,
    InMemoryDatasetRegistry,
    MemoryObservationCache,
    Observation,
    ObservationAsset,
    ObservationFusion,
    ObservationGraphBuilder,
    ObservationSearchResult,
    PerceptionConnector,
    PerceptionEngine,
    PerceptionResult,
    PlatformRuntime,
    ObservationQualityService,
    QualityQuery,
    SemanticNormalizer,
    SpatialService,
    assess_observation,
    forecast_window,
    TemporalExtent,
    group_by_temporal_windows,
    group_temporal_events,
    historical_window,
    seasonal_windows,
)


class SourceConnector(PerceptionConnector):
    def __init__(
        self,
        connector_id,
        observations=(),
        *,
        priority=0,
        error=None,
        fallback_for=(),
        provider_metadata=None,
        policy=None,
        authentication_schemes=(),
    ):
        super().__init__(policy=policy)
        self.connector_id = connector_id
        self.observations = tuple(observations)
        self.priority = priority
        self.error = error
        self.fallback_for = fallback_for
        self.calls = 0
        self.provider_metadata = provider_metadata or {}
        self.datasets: tuple[DatasetReference, ...] = ()
        self.authentication_schemes = tuple(authentication_schemes)
        self.received_credentials = None

    @property
    def metadata(self):
        return ConnectorMetadata(
            connector_id=self.connector_id,
            name=self.connector_id,
            version="1",
            capabilities=("environmental",),
            priority=self.priority,
            health="healthy",
            supported_spatial_types=("point",),
            supports_temporal_query=True,
            supported_variables=("temperature", "rain"),
            provider_metadata=self.provider_metadata,
            fallback_for=self.fallback_for,
            authentication_schemes=self.authentication_schemes,
            authentication_required=bool(self.authentication_schemes),
        )

    async def _authenticate(self, credentials):
        self.received_credentials = dict(credentials)

    async def discover(self):
        return self.datasets

    async def acquire(self, _request):
        return {}

    async def observe(self, _query):
        self.calls += 1
        if self.error:
            if isinstance(self.error, list):
                raise self.error.pop(0)
            raise self.error
        return ObservationSearchResult(observations=self.observations)


def observation(
    observation_id,
    *,
    source_id=None,
    value=10,
    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end=datetime(2024, 1, 2, tzinfo=timezone.utc),
    confidence=None,
):
    return Observation(
        observation_id=observation_id,
        source_id=source_id or observation_id,
        observation_type="weather",
        measured_variables={"temperature": {"value": value, "unit": "K"}},
        temporal_extent=TemporalExtent(start=start, end=end),
        geometry={"type": "Point", "coordinates": [10, 20]},
        crs="OGC:CRS84",
        confidence=confidence,
        reproducibility={"request": {"id": observation_id}},
    )


def test_engine_acquires_multiple_providers_and_keeps_generic_contracts():
    async def run():
        manager = ConnectorManager()
        first = SourceConnector(
            "source-a",
            (observation("a", value=10, confidence=0.7),),
            provider_metadata={"provider": "vendor-specific-name"},
        )
        second = SourceConnector(
            "source-b",
            (observation("b", value=12, confidence=0.9),),
            provider_metadata={"api_payload_type": "vendor-specific-shape"},
        )
        manager.register(first)
        manager.register(second)
        engine = PerceptionEngine(manager)
        result = await engine.observe(
            EarthQuery(
                point=(10, 20),
                required_capabilities=("environmental",),
                requested_variables=("temperature",),
            )
        )
        await manager.stop_all()
        return result

    result = asyncio.run(run())
    assert result.status == "complete"
    assert result.connector_ids == ("source-a", "source-b")
    assert len(result.observations) == 2
    assert len(result.observation_groups) == 1
    group = result.observation_groups[0]
    assert group.primary_observation_id == "b"
    assert len(group.conflicts) == 1
    assert result.conflicts == group.conflicts
    assert group.temporal_overlap == TemporalExtent(
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    assert group.spatial_overlap == {
        "type": "Point",
        "coordinates": [10.0, 20.0],
    }
    for item in result.observations:
        assert item.quality_assessment is not None
        assert item.quality_assessment.completeness == 1
        assert item.quality_assessment.confidence == item.confidence
        assert item.quality_assessment.reproducibility == "available"
        assert item.provenance["satquery"]["earth_perception"].get("provider") in {
            None,
            "vendor-specific-name",
        }


def test_fusion_groups_spatial_overlap_without_false_temporal_conflicts():
    first = observation("first", value=1)
    disjoint = observation(
        "disjoint",
        value=2,
        start=datetime(2024, 2, 1, tzinfo=timezone.utc),
        end=datetime(2024, 2, 2, tzinfo=timezone.utc),
    )
    separate_location = observation("separate-location").model_copy(
        update={"geometry": {"type": "Point", "coordinates": [50, 50]}}
    )
    pair_group = ObservationFusion().group((first, disjoint))[0]
    groups = ObservationFusion().group((first, disjoint, separate_location))
    assert any(
        {"first", "disjoint"}.issubset(group.observation_ids) for group in groups
    )
    assert pair_group.temporal_overlap is None
    assert pair_group.spatial_overlap is not None
    assert pair_group.conflicts == ()
    assert len(groups) == 1
    graph = ObservationGraphBuilder().build((first, disjoint, separate_location))
    assert any(
        edge.relation == "overlaps"
        and {edge.source_id, edge.target_id} == {"first", "disjoint"}
        for edge in graph.relationships
    )
    assert not any(
        edge.relation == "overlaps"
        and {edge.source_id, edge.target_id} == {"disjoint", "separate-location"}
        for edge in graph.relationships
    )
    assert not any(edge.relation == "conflicts_with" for edge in graph.relationships)


def test_quality_assessment_does_not_invent_completeness_confidence_or_validation():
    item = observation("known-source").model_copy(
        update={
            "confidence": None,
            "quality": {"normalized_score": 0.8, "flag": "source-reported"},
        }
    )
    assessment = assess_observation(item)
    assert assessment.completeness is None
    assert assessment.confidence is None
    assert assessment.provider_quality_score == 0.8
    assert assessment.quality_score == 0.8
    assert assessment.provider_quality["flag"] == "source-reported"
    assert assessment.validation_status == "valid"

    malformed = Observation(
        observation_id="malformed",
        bbox=(0, 0, float("inf"), 1),
    )
    assert assess_observation(malformed).validation_status == "invalid"


def test_fallback_connector_runs_only_after_declared_primary_failure():
    async def run():
        manager = ConnectorManager()
        primary = SourceConnector(
            "primary",
            error=ConnectorError("primary unavailable", recoverable=True),
        )
        fallback = SourceConnector(
            "fallback",
            (observation("fallback-observation"),),
            priority=1,
            fallback_for=("primary",),
        )
        manager.register(primary)
        manager.register(fallback)
        engine = PerceptionEngine(manager)
        result = await engine.observe(
            EarthQuery(point=(10, 20), required_capabilities=("environmental",))
        )
        await manager.stop_all()
        return result, primary, fallback

    result, primary, fallback = asyncio.run(run())
    assert primary.calls == 1
    assert fallback.calls == 1
    assert result.status == "partial"
    assert result.failures[0].connector_id == "primary"
    assert [item.observation_id for item in result.observations] == [
        "fallback-observation"
    ]


def test_fallback_is_not_called_when_primary_succeeds():
    async def run():
        manager = ConnectorManager()
        manager.register(SourceConnector("primary", (observation("primary-result"),)))
        fallback = SourceConnector(
            "fallback",
            (observation("fallback-result"),),
            fallback_for=("primary",),
        )
        manager.register(fallback)
        result = await PerceptionEngine(manager).observe(
            EarthQuery(point=(10, 20), required_capabilities=("environmental",))
        )
        await manager.stop_all()
        return result, fallback

    result, fallback = asyncio.run(run())
    assert fallback.calls == 0
    assert [item.observation_id for item in result.observations] == ["primary-result"]


def test_cache_supports_connector_invalidation_expiry_and_statistics():
    async def run():
        cache = MemoryObservationCache()
        result = PerceptionResult(
            query_fingerprint="query",
            observations=(),
            connector_ids=("connector-a",),
            connector_versions=("connector-a:1",),
        )
        await cache.set("query", result, ttl_seconds=1)
        before = await cache.stats()
        invalidated = await cache.invalidate_connector("connector-a")
        assert invalidated == 1
        assert await cache.get("query") == (False, None)
        await cache.set("stale", result, ttl_seconds=0.01)
        await asyncio.sleep(0.02)
        assert await cache.get("stale") == (False, None)
        stats = await cache.stats()
        return before, stats

    before, stats = asyncio.run(run())
    assert before.entries == 1
    assert stats.stale_expirations == 1
    assert stats.misses >= 2


def test_dataset_registry_filters_metadata_before_connector_acquisition():
    registry = InMemoryDatasetRegistry(
        (
            DatasetMetadata(
                connector_id="connector",
                dataset_id="daily-weather",
                provider="Example Agency",
                variables=("temperature", "rain"),
                capabilities=("weather", "environmental"),
                temporal_coverage=TemporalExtent(
                    start=datetime(2000, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2030, 1, 1, tzinfo=timezone.utc),
                ),
                spatial_coverage={
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
                },
                crs="OGC:CRS84",
                spatial_resolution=1000,
                resolution_unit="m",
                update_frequency="daily",
                uncertainty_characteristics={"measurement": "provider reported"},
                licensing="CC-BY",
                citation="Example Agency (2024)",
            ),
        )
    )
    matches = registry.search(
        EarthQuery(
            requested_variables=("temperature",),
            required_capabilities=("weather",),
            temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
    )
    assert [dataset.dataset_id for dataset in matches] == ["daily-weather"]
    assert registry.search(
        EarthQuery(requested_variables=("elevation",))
    ) == ()
    assert registry.get("connector", "daily-weather").licensing == "CC-BY"


def test_asset_catalog_searches_unified_asset_references_without_opening_them():
    dataset = DatasetMetadata(
        connector_id="connector",
        dataset_id="elevation",
        provider="Example Agency",
        assets={
            "metadata": ObservationAsset(
                uri="https://example.test/elevation.json",
                media_type="application/json",
                roles=("metadata",),
                title="Elevation metadata",
            )
        },
    )
    observation_with_asset = observation("asset-observation").model_copy(
        update={
            "dataset": DatasetReference(
                connector_id="connector",
                dataset_id="elevation",
            ),
            "assets": {
                "preview": ObservationAsset(
                    uri="https://example.test/preview.png",
                    media_type="image/png",
                    roles=("thumbnail", "preview"),
                    title="Elevation preview",
                )
            },
        }
    )
    result = AssetCatalog().search(
        AssetQuery(dataset_id="elevation", roles=("preview",)),
        observations=(observation_with_asset,),
        datasets=(dataset,),
    )
    assert result.matched == 1
    assert result.assets[0].uri.endswith("preview.png")
    assert result.source_ids == ("asset-observation",)


def test_temporal_seasons_and_grouping_cover_historical_and_future_ranges():
    windows = seasonal_windows(
        datetime(2024, 11, 1, tzinfo=timezone.utc),
        datetime(2025, 4, 1, tzinfo=timezone.utc),
        start_month=12,
        duration_months=3,
    )
    assert len(windows) == 1
    assert windows[0].start == datetime(2024, 12, 1, tzinfo=timezone.utc)
    assert windows[0].end == datetime(2025, 3, 1, tzinfo=timezone.utc)
    assert historical_window(
        duration=timedelta(days=2),
        now=datetime(2025, 1, 2, tzinfo=timezone.utc),
    ).start == datetime(2024, 12, 31, tzinfo=timezone.utc)
    assert forecast_window(
        duration=timedelta(days=2),
        now=datetime(2025, 1, 2, tzinfo=timezone.utc),
    ).end == datetime(2025, 1, 4, tzinfo=timezone.utc)
    grouped = group_temporal_events(
        (
            observation(
                "event-a",
                start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end=datetime(2025, 1, 2, tzinfo=timezone.utc),
            ),
            observation(
                "event-b",
                start=datetime(2025, 1, 3, tzinfo=timezone.utc),
                end=datetime(2025, 1, 4, tzinfo=timezone.utc),
            ),
        ),
        maximum_gap=timedelta(days=1),
    )
    assert [len(group) for group in grouped] == [2]


def test_connector_manifest_capability_discovery_diagnostics_and_auto_registration():
    async def run():
        registry = InMemoryDatasetRegistry()
        manager = ConnectorManager(dataset_registry=registry)
        connector = SourceConnector("self-describing")
        connector.datasets = (
            DatasetReference(
                connector_id="self-describing",
                dataset_id="daily-observations",
                version="2",
                uri="https://example.test/data",
                metadata={
                    "variables": ["temperature"],
                    "capabilities": ["environmental"],
                    "tags": ["daily"],
                    "aliases": ["daily temperatures"],
                },
            ),
        )
        manager.register(connector)
        manifest = manager.describe("self-describing")
        discovered = await manager.discover("self-describing")
        dataset = registry.get("self-describing", "daily-observations")
        diagnostic = manager.diagnostics()[0]
        await manager.stop_all()
        return manager, manifest, discovered, dataset, diagnostic

    manager, manifest, discovered, dataset, diagnostic = asyncio.run(run())
    assert manifest.metadata.connector_id == "self-describing"
    assert "environmental" in manager.discover_capabilities()
    assert discovered[0].dataset_id == dataset.dataset_id
    assert dataset.version == "2"
    assert dataset.metadata["registration_source"] == "automatic"
    assert diagnostic.state == "running"


def test_canonical_runtime_applies_retry_timeout_metrics_and_cancellation():
    async def run():
        manager = ConnectorManager()
        connector = SourceConnector(
            "retry-source",
            (observation("retried"),),
            error=[
                ConnectorError("temporary", recoverable=True),
            ],
            policy=ConnectorPolicy(
                max_attempts=2,
                retry_safe=True,
                retry_delay_seconds=0,
            ),
        )
        manager.register(connector)
        result = await PerceptionEngine(manager).observe(
            EarthQuery(point=(10, 20), required_capabilities=("environmental",))
        )
        diagnostics = connector.diagnostics
        await manager.stop_all()
        return result, diagnostics

    result, diagnostics = asyncio.run(run())
    assert result.status == "complete"
    assert diagnostics.calls == 2
    assert diagnostics.failures == 1
    assert diagnostics.retries == 1
    assert diagnostics.health == "healthy"
    assert diagnostics.last_error is None


def test_connector_manager_resolves_authentication_and_reports_health():
    class Credentials:
        async def credentials_for(self, connector_id, schemes):
            assert connector_id == "secured"
            assert schemes == ("token",)
            return {"token": "resolved"}

    async def run():
        connector = SourceConnector("secured", authentication_schemes=("token",))
        authentication_provider: AuthenticationProvider = Credentials()
        manager = ConnectorManager(
            authentication_provider=authentication_provider
        )
        manager.register(connector)
        await manager.start("secured")
        snapshots = await manager.health_snapshot()
        await manager.stop_all()
        return connector, snapshots

    connector, snapshots = asyncio.run(run())
    assert connector.received_credentials == {"token": "resolved"}
    assert snapshots[0].health == "healthy"


def test_nested_fetch_does_not_apply_the_same_rate_limit_twice():
    class CountingLimiter:
        def __init__(self):
            self.calls = 0

        async def acquire(self):
            self.calls += 1

    class FetchBackedConnector(SourceConnector):
        async def acquire(self, _request):
            return ObservationSearchResult(
                observations=(observation("fetch-backed"),)
            )

        async def observe(self, _query):
            return await self.fetch({})

    async def run():
        connector = FetchBackedConnector("fetch-backed")
        limiter = CountingLimiter()
        connector._rate_limiter = limiter
        manager = ConnectorManager()
        manager.register(connector)
        result = await PerceptionEngine(manager).observe(
            EarthQuery(point=(10, 20), required_capabilities=("environmental",))
        )
        await manager.stop_all()
        return result, limiter

    result, limiter = asyncio.run(run())
    assert result.status == "complete"
    assert limiter.calls == 1


def test_canonical_acquisition_timeout_is_reported_and_counted():
    class SlowConnector(SourceConnector):
        async def observe(self, _query):
            await asyncio.sleep(0.02)
            return ObservationSearchResult(observations=(observation("late"),))

    async def run():
        connector = SlowConnector(
            "slow-source",
            policy=ConnectorPolicy(timeout_seconds=0.001),
        )
        manager = ConnectorManager()
        manager.register(connector)
        result = await PerceptionEngine(manager).observe(
            EarthQuery(point=(10, 20), required_capabilities=("environmental",))
        )
        diagnostic = connector.diagnostics
        await manager.stop_all()
        return result, diagnostic

    result, diagnostic = asyncio.run(run())
    assert result.status == "failed"
    assert result.failures[0].error_type == "OperationTimeoutError"
    assert diagnostic.failures == 1
    assert diagnostic.last_error_type == "OperationTimeoutError"


def test_connector_plugins_use_the_declared_entry_point_group(monkeypatch):
    entry_point = SimpleNamespace(
        name="plugin-source", load=lambda: SourceConnector
    )
    selected_groups = []
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda: SimpleNamespace(
            select=lambda **kwargs: (
                selected_groups.append(kwargs["group"]) or (entry_point,)
            )
        ),
    )
    manager = ConnectorManager()
    discovered = manager.discover_plugins(
        lambda connector_type: connector_type("plugin-source")
    )
    assert selected_groups == ["satquery.connectors"]
    assert discovered == ("plugin-source",)
    assert manager.capabilities()["plugin-source"] == ("environmental",)


def test_dataset_registry_semantic_search_aliases_versions_and_deprecation():
    registry = InMemoryDatasetRegistry(
        (
            DatasetMetadata(
                connector_id="agency",
                dataset_id="forest-cover",
                provider="Agency",
                version="1",
                variables=("tree_cover",),
                capabilities=("land_cover",),
                aliases=("forest map",),
                keywords=("canopy", "vegetation"),
            ),
            DatasetMetadata(
                connector_id="agency",
                dataset_id="forest-cover",
                provider="Agency",
                version="2",
                variables=("tree_cover", "canopy_density"),
                capabilities=("land_cover",),
                aliases=("forest map",),
                keywords=("canopy", "vegetation"),
            ),
            DatasetMetadata(
                connector_id="agency",
                dataset_id="old-forest-map",
                provider="Agency",
                deprecated=True,
                keywords=("canopy", "forest"),
            ),
        )
    )
    assert len(registry.list()) == 3
    assert registry.get("agency", "forest-cover", "1").version == "1"
    assert registry.get("agency", "forest-cover").version == "2"
    assert registry.resolve_alias("forest map")[0].version == "2"
    assert registry.semantic_search("canopy vegetation")[0].dataset_id == "forest-cover"
    assert registry.search(EarthQuery(point=(10, 20))) == ()
    assert registry.search(
        EarthQuery(temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc))
    ) == ()
    assert [
        item.dataset_id
        for item in registry.search_capabilities(("land_cover",))
    ] == ["forest-cover"]


def test_semantic_harmonization_preserves_source_values_and_metadata():
    normalizer = SemanticNormalizer(
        {
            "t2m": {
                "canonical_name": "air_temperature",
                "standard_name": "air_temperature",
                "ontology_uri": "https://example.test/ontology/temperature",
                "unit_dimension": "temperature",
                "aliases": ("temperature_2m",),
            }
        },
        observation_types={"meteo": "weather"},
        categories={"land_cover": {"trees": "forest"}},
        dataset_vocabulary={"t2m": "air_temperature"},
    )
    original = Observation(
        observation_id="semantic",
        observation_type="meteo",
        crs="EPSG:4326",
        measured_variables={"t2m": {"value": 280, "unit": "K"}},
    )
    normalized = normalizer.harmonize_observation(original)
    measurement = normalized.measured_variables["air_temperature"]
    assert normalized.observation_type == "weather"
    assert measurement["value"] == 280
    assert measurement["source_name"] == "t2m"
    assert measurement["source_unit"] == "K"
    assert measurement["ontology_uri"].endswith("temperature")
    assert normalized.crs == "EPSG:4326"
    assert normalized.properties["source_crs"] == "EPSG:4326"
    assert original.measured_variables["t2m"]["value"] == 280
    assert normalizer.normalize_category("land_cover", "Trees") == {
        "value": "forest",
        "source_value": "Trees",
        "normalized": True,
    }
    dataset = DatasetMetadata(
        connector_id="c",
        dataset_id="d",
        provider="p",
        variables=("t2m",),
    )
    assert normalizer.harmonize_dataset(dataset).variables == ("air_temperature",)


def test_perception_adds_canonical_measurements_for_quality_and_fusion():
    async def run():
        first = Observation(
            observation_id="temperature-source-a",
            observation_type="weather",
            measured_variables={"t2m": {"value": 280.0, "unit": "K"}},
            temporal_extent=TemporalExtent(
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 1, 2, tzinfo=timezone.utc),
            ),
            geometry={"type": "Point", "coordinates": [10, 20]},
            crs="OGC:CRS84",
        )
        second = first.model_copy(update={
            "observation_id": "temperature-source-b",
            "measured_variables": {
                "air_temperature_2m": {"value": 281.0, "unit": "K"}
            },
        })
        manager = ConnectorManager()
        manager.register(SourceConnector("source-a", (first,)))
        manager.register(SourceConnector("source-b", (second,)))
        result = await PerceptionEngine(manager).observe(
            EarthQuery(point=(10, 20), required_capabilities=("environmental",))
        )
        await manager.stop_all()
        return result

    result = asyncio.run(run())
    by_id = {item.observation_id: item for item in result.observations}
    assert by_id["temperature-source-a"].measured_variables == {
        "t2m": {"value": 280.0, "unit": "K"}
    }
    assert by_id["temperature-source-a"].canonical_measurements[0].canonical_variable == "air_temperature"
    assert by_id["temperature-source-a"].canonical_measurements[0].source_variable == "t2m"
    normalization = by_id["temperature-source-a"].provenance["satquery"]["earth_perception"]
    assert normalization["normalizer_version"] == SemanticNormalizer.VERSION
    assert normalization["normalizer_revision"]
    assert by_id["temperature-source-a"].quality_assessment.completeness is None
    assert len(result.observation_groups) == 1
    conflict = result.observation_groups[0].conflicts[0]
    assert conflict["variable"] == "air_temperature"
    assert conflict["type"] == "measurement_disagreement"
    assert conflict["values"][0]["source_variable"] == "t2m"


def test_quality_completeness_uses_resolved_canonical_measurements():
    normalized = SemanticNormalizer().canonicalize_observation(
        Observation(
            observation_id="quality-canonical",
            measured_variables={"t2m": {"value": 280, "unit": "K"}},
        )
    )
    assessment = assess_observation(
        normalized, expected_variables=("air_temperature",)
    )
    assert assessment.completeness == 1.0


def test_streaming_path_uses_the_same_additive_canonicalization():
    async def run():
        manager = ConnectorManager()
        manager.register(SourceConnector(
            "stream-semantic-source",
            (Observation(
                observation_id="stream-semantic-observation",
                measured_variables={"t2m": {"value": 280, "unit": "K"}},
            ),),
        ))
        engine = PerceptionEngine(manager)
        observations = [
            item async for item in engine.stream(
                EarthQuery(point=(10, 20), required_capabilities=("environmental",))
            )
        ]
        await manager.stop_all()
        return observations

    observations = asyncio.run(run())
    assert observations[0].measured_variables == {"t2m": {"value": 280, "unit": "K"}}
    assert observations[0].canonical_measurements[0].canonical_variable == "air_temperature"
    assert observations[0].provenance["satquery"]["earth_perception"]["normalizer_revision"]


def test_observation_cache_is_scoped_to_normalizer_revision():
    async def run():
        shared_cache = MemoryObservationCache()
        manager = ConnectorManager()
        manager.register(SourceConnector(
            "semantic-cache-source",
            (Observation(
                observation_id="semantic-cache-observation",
                measured_variables={"raw_signal": {"value": 7, "unit": "count"}},
            ),),
        ))
        query = EarthQuery(point=(10, 20), required_capabilities=("environmental",))
        first_engine = PerceptionEngine(
            manager,
            cache=shared_cache,
            normalizer=SemanticNormalizer({"raw_signal": "earth:signal_alpha"}),
        )
        first = await first_engine.observe(query)
        second_engine = PerceptionEngine(
            manager,
            cache=shared_cache,
            normalizer=SemanticNormalizer({"raw_signal": "earth:signal_beta"}),
        )
        second = await second_engine.observe(query)
        await manager.stop_all()
        return first, second

    first, second = asyncio.run(run())
    assert first.observations[0].canonical_measurements[0].canonical_variable == "earth:signal_alpha"
    assert second.observations[0].canonical_measurements[0].canonical_variable == "earth:signal_beta"


def test_capability_matrix_uses_normalized_dataset_variables_and_retains_source_terms():
    registry = InMemoryDatasetRegistry()
    registry.register(DatasetMetadata(
        connector_id="declared-source",
        dataset_id="declared-dataset",
        provider="provider-neutral-test",
        variables=("provider_temp",),
    ))
    manager = ConnectorManager(dataset_registry=registry)
    manager.register(SourceConnector("declared-source"))
    engine = PerceptionEngine(
        manager,
        normalizer=SemanticNormalizer(
            dataset_vocabulary={"provider_temp": "earth:temperature-example"}
        ),
    )
    dataset = engine.build_capability_matrix().datasets[0]
    assert dataset.variables == ("earth:temperature-example",)
    assert dataset.metadata["source_variables"] == ("provider_temp",)


def test_platform_runtime_composes_an_injected_semantic_normalizer():
    normalizer = SemanticNormalizer({"provider_temp": "earth:temperature-example"})
    runtime = PlatformRuntime(semantic_normalizer=normalizer)
    assert runtime.perception_engine.normalizer is normalizer
    asyncio.run(runtime.close())


def test_observation_graph_records_explicit_and_descriptive_relationships():
    first = observation("graph-a", value=10)
    second = observation("graph-b", value=10)
    declared = observation("graph-c").model_copy(
        update={
            "provenance": {
                "relationships": [
                    {"observation_id": "graph-a", "relation": "derived_from"}
                ]
            }
        }
    )
    graph = ObservationGraphBuilder().build((declared, second, first))
    relations = {
        (edge.source_id, edge.target_id, edge.relation)
        for edge in graph.relationships
    }
    assert ("graph-a", "graph-b", "overlaps") in relations
    assert ("graph-a", "graph-b", "corroborates") in relations
    assert ("graph-c", "graph-a", "derived_from") in relations
    assert graph.observations[0].observation_id == "graph-a"


def test_quality_service_filters_assessments_independently_of_observation_storage():
    item = observation("quality", confidence=0.9).model_copy(
        update={
            "quality": {"normalized_score": 0.8},
            "reproducibility": {"request": "recorded"},
        }
    )
    service = ObservationQualityService()
    record = service.assess(
        item,
        expected_variables=("temperature", "rain"),
        now=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    assert record.assessment.completeness == 0.5
    assert record.assessment.quality_score == 0.8
    assert len(
        service.filter(
            (record,),
            QualityQuery(
                minimum_quality_score=0.7,
                minimum_confidence=0.8,
                validation_status="valid",
            ),
        )
    ) == 1
    assert service.filter(
        (record,),
        QualityQuery(minimum_quality_score=0.9),
    ) == ()


def test_spatial_services_normalize_buffer_and_clip_aoi_tiles():
    service = SpatialService()
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [0, 0],
            [1000, 0],
            [1000, 1000],
            [0, 1000],
            [0, 0],
        ]],
    }
    buffered = service.buffer(
        {"type": "Point", "coordinates": [500, 500]},
        distance=100,
        crs="EPSG:3857",
        distance_unit="m",
    )
    assert buffered["type"] == "Polygon"
    assert service.contains(
        geometry,
        {"type": "Point", "coordinates": [500, 500]},
    )
    aoi = AreaOfInterest(geometry=geometry, crs="EPSG:3857")
    tiles = aoi.tiles(tile_width=600, tile_height=600)
    assert len(tiles) == 4
    assert all(tile.geometry["type"] in {"Polygon", "MultiPolygon"} for tile in tiles)
    with pytest.raises(ValueError, match="projected CRS"):
        service.buffer(
            {"type": "Point", "coordinates": [0, 0]},
            distance=100,
            crs="OGC:CRS84",
        )


def test_temporal_grouping_matches_observations_to_requested_windows():
    windows = seasonal_windows(
        datetime(2024, 11, 1, tzinfo=timezone.utc),
        datetime(2025, 4, 1, tzinfo=timezone.utc),
        start_month=12,
        duration_months=3,
    )
    future_observation = observation(
        "future",
        start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )
    groups = group_by_temporal_windows((future_observation,), windows)
    assert [len(items) for _, items in groups] == [1]
