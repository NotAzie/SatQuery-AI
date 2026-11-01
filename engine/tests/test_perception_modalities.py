import asyncio

from satquery.platform import (
    EARTH_VARIABLE_ONTOLOGY,
    ConnectorManager,
    ConnectorMetadata,
    DatasetMetadata,
    EarthConcept,
    EarthQuery,
    EarthVariable,
    EarthVariableOntology,
    InMemoryDatasetRegistry,
    Observation,
    ObservationSearchResult,
    PerceptionConnector,
    PerceptionEngine,
    SensingModality,
    SensingModalityRegistry,
    infer_modalities,
)


class DomainImplementation(PerceptionConnector):
    def __init__(self, implementation_id, variable, modality, observations=()):
        super().__init__()
        self.implementation_id = implementation_id
        self.variable = variable
        self.modality = modality
        self.observations = tuple(observations)
        self.received_queries = []

    @property
    def metadata(self):
        return ConnectorMetadata(
            connector_id=self.implementation_id,
            name=self.implementation_id,
            version="1",
            modalities=(self.modality,),
            supported_variables=(self.variable,),
            supported_spatial_types=("point",),
            supports_temporal_query=True,
            supported_query_fields=("requested_dataset_ids",),
            health="healthy",
        )

    async def discover(self):
        return ()

    async def acquire(self, _request):
        return {}

    async def observe(self, query):
        self.received_queries.append(query)
        return ObservationSearchResult(observations=self.observations)


class CatalogBackedImplementation(DomainImplementation):
    @property
    def metadata(self):
        return ConnectorMetadata(
            connector_id=self.implementation_id,
            name=self.implementation_id,
            version="1",
            supported_spatial_types=("point",),
            supports_temporal_query=True,
            supported_query_fields=("requested_dataset_ids",),
            health="healthy",
        )


def test_variable_domains_infer_from_earth_ontology_without_provider_names():
    assert infer_modalities(("air_temperature_2m", "elevation")) == (
        "atmospheric",
        "geological",
    )


def test_modality_registry_supports_extensions_and_ambiguous_aliases():
    registry = SensingModalityRegistry(
        (
            SensingModality("first", "First", "first domain", aliases=("shared",)),
            SensingModality("second", "Second", "second domain", aliases=("shared",)),
        )
    )
    assert registry.resolve_id("FIRST") == "first"
    assert registry.resolve_id("shared") is None


def test_modality_registry_supports_an_extended_science_ontology():
    ontology = EarthVariableOntology(
        (
            *EARTH_VARIABLE_ONTOLOGY.concepts,
            EarthConcept("permafrost_research", "Permafrost research"),
        ),
        (
            *EARTH_VARIABLE_ONTOLOGY.variables,
            EarthVariable(
                "active_layer_depth",
                "permafrost_research",
                "Active layer depth",
                aliases=("active_layer_depth",),
            ),
        ),
    )
    registry = SensingModalityRegistry(
        (
            SensingModality(
                "permafrost",
                "Permafrost",
                "Frozen-ground observations",
                ontology_concepts=("permafrost_research",),
            ),
        ),
        ontology=ontology,
    )
    assert infer_modalities(("active_layer_depth",), registry) == ("permafrost",)


def test_engine_accepts_an_injected_modality_registry():
    registry = SensingModalityRegistry(
        (
            SensingModality(
                "atmospheric_custom",
                "Atmospheric custom",
                "project-specific atmospheric grouping",
                ontology_concepts=("weather",),
            ),
        )
    )
    manager = ConnectorManager()
    manager.register(
        DomainImplementation("custom-weather", "air_temperature", "atmospheric_custom")
    )
    plan = PerceptionEngine(manager, modality_registry=registry).plan(
        EarthQuery(requested_variables=("air_temperature",))
    )
    assert plan.requested_modalities == ("atmospheric_custom",)
    assert plan.selected_modalities == ("atmospheric_custom",)


def test_perception_plans_across_implementations_and_reports_unavailable_domains():
    async def run():
        manager = ConnectorManager()
        atmosphere = DomainImplementation(
            "weather-source", "air_temperature", "atmospheric"
        )
        terrain = DomainImplementation("terrain-source", "elevation", "geological")
        manager.register(atmosphere)
        manager.register(terrain)
        engine = PerceptionEngine(manager)
        query = EarthQuery(
            point=(10, 20),
            requested_variables=("air_temperature", "elevation"),
            requested_modalities=("weather", "terrain", "ocean"),
        )
        plan = engine.plan(query)
        result = await engine.observe(query)
        await manager.stop_all()
        return plan, result, atmosphere, terrain

    plan, result, atmosphere, terrain = asyncio.run(run())
    assert plan.implementation_ids == ("terrain-source", "weather-source")
    assert plan.requested_modalities == ("atmospheric", "geological", "oceanic")
    assert plan.selected_modalities == ("atmospheric", "geological")
    assert plan.unavailable_modalities == ("oceanic",)
    assert plan.selected_variables == ("air_temperature", "elevation")
    assert plan.unavailable_variables == ()
    assert result.plan == plan
    assert result.status == "partial"
    assert atmosphere.received_queries[0].requested_variables == ("air_temperature",)
    assert terrain.received_queries[0].requested_variables == ("elevation",)


def test_dataset_discovery_plan_finds_multiple_implementations_for_one_request():
    registry = InMemoryDatasetRegistry(
        (
            DatasetMetadata(
                connector_id="weather-impl",
                dataset_id="weather-data",
                provider="source-a",
                variables=("air_temperature",),
            ),
            DatasetMetadata(
                connector_id="terrain-impl",
                dataset_id="terrain-data",
                provider="source-b",
                variables=("elevation",),
            ),
        )
    )
    plan = registry.plan(
        EarthQuery(requested_variables=("air_temperature", "elevation"))
    )
    assert {dataset.dataset_id for dataset in plan.datasets} == {
        "weather-data",
        "terrain-data",
    }
    assert plan.available_modalities == ("atmospheric", "geological")
    assert plan.unavailable_variables == ()
    scoped = registry.plan(
        EarthQuery(requested_dataset_ids=("weather-impl:weather-data",))
    )
    assert [dataset.dataset_id for dataset in scoped.datasets] == ["weather-data"]


def test_registered_datasets_drive_modality_selection_and_scoped_queries():
    async def run():
        manager = ConnectorManager()
        weather = CatalogBackedImplementation("weather-impl", "unused", "unused")
        terrain = CatalogBackedImplementation("terrain-impl", "unused", "unused")
        manager.register(weather)
        manager.register(terrain)
        manager.dataset_registry.register(
            DatasetMetadata(
                connector_id="weather-impl",
                dataset_id="weather-observations",
                provider="source-a",
                variables=("air_temperature",),
            )
        )
        manager.dataset_registry.register(
            DatasetMetadata(
                connector_id="terrain-impl",
                dataset_id="elevation-observations",
                provider="source-b",
                variables=("elevation",),
            )
        )
        engine = PerceptionEngine(manager)
        query = EarthQuery(
            requested_variables=("air_temperature", "elevation")
        )
        plan = engine.plan(query)
        result = await engine.observe(query)
        await manager.stop_all()
        return plan, result, weather, terrain

    plan, result, weather, terrain = asyncio.run(run())
    assert plan.implementation_ids == ("terrain-impl", "weather-impl")
    assert plan.dataset_ids == (
        "terrain-impl:elevation-observations",
        "weather-impl:weather-observations",
    )
    assert weather.received_queries[0].requested_variables == ("air_temperature",)
    assert terrain.received_queries[0].requested_variables == ("elevation",)
    assert weather.received_queries[0].requested_dataset_ids == (
        "weather-observations",
    )
    assert terrain.received_queries[0].requested_dataset_ids == (
        "elevation-observations",
    )
    assert result.plan == plan


def test_point_asset_sampling_requires_dataset_level_band_capability():
    class RasterImplementation(CatalogBackedImplementation):
        @property
        def metadata(self):
            return ConnectorMetadata(
                connector_id=self.implementation_id,
                name=self.implementation_id,
                version="1",
                capabilities=("raster_point_sampling",),
                supported_variables=("red",),
                modalities=("visual",),
                supported_spatial_types=("point",),
                supported_query_fields=("asset_sampling", "requested_dataset_ids"),
                health="healthy",
            )

    query = EarthQuery(
        point=(1, 2),
        requested_variables=("red",),
        asset_sampling="point",
    )
    plans = []
    for capabilities in ((), ("raster_point_sampling",)):
        manager = ConnectorManager()
        connector = RasterImplementation("raster", "red", "visual")
        manager.register(connector)
        manager.dataset_registry.register(
            DatasetMetadata(
                connector_id="raster",
                dataset_id="reflectance",
                provider="example",
                variables=("red",),
                modalities=("visual",),
                capabilities=capabilities,
            )
        )
        plans.append(PerceptionEngine(manager).plan(query))
    assert plans[0].implementation_ids == ()
    assert plans[1].implementation_ids == ("raster",)


def test_visual_modality_requires_an_explicit_imaging_implementation():
    async def run():
        manager = ConnectorManager()
        image = DomainImplementation(
            "image-source", "image_asset", "visual", (Observation(),)
        )
        manager.register(image)
        engine = PerceptionEngine(manager)
        query = EarthQuery(point=(10, 20), requested_modalities=("imagery",))
        plan = engine.plan(query)
        result = await engine.observe(query)
        await manager.stop_all()
        return plan, result

    plan, result = asyncio.run(run())
    assert plan.requested_modalities == ("visual",)
    assert plan.selected_modalities == ("visual",)
    assert plan.unavailable_modalities == ()
    assert result.observations[0].modalities == ("visual",)
