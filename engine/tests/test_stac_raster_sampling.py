from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from connectors.stac import StacCatalogConnector
from satquery.platform.contracts import (
    DatasetReference,
    DatasetMetadata,
    EarthQuery,
    Observation,
    ObservationAsset,
    ObservationSearchResult,
)
from satquery.platform.raster import (
    RasterAssetSamplingError,
    RasterAssetSamplingService,
)
from satquery.platform import (
    ConnectorManager,
    InMemoryDatasetRegistry,
    PerceptionEngine,
)
from satquery.platform.raster_analysis import RasterAnalysisService


@pytest.fixture
def raster_path():
    rasterio = pytest.importorskip("rasterio")
    from affine import Affine

    path = Path(__file__).resolve().parent / f".raster-sample-{uuid4().hex}.tif"
    try:
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=2,
            dtype="float32",
            crs="EPSG:4326",
            transform=Affine(1, 0, -1, 0, -1, 1),
            nodata=-9999,
        ) as raster:
            raster.write(np.array([[10, 20], [-9999, 40]], dtype="float32"), 1)
            raster.write(np.array([[100, 200], [300, 400]], dtype="float32"), 2)
            raster.scales = (1.0, 1.0)
            raster.offsets = (0.0, 0.0)
            raster.set_band_description(1, "red")
            raster.set_band_description(2, "near_infrared")
        yield path
    finally:
        if path.exists():
            path.unlink()


def _observation(path: Path) -> Observation:
    return Observation(
        observation_id="stac-item-1",
        source_id="item-1",
        dataset=DatasetReference(
            connector_id="catalog",
            dataset_id="surface-reflectance",
            metadata={"modalities": ["visual"]},
        ),
        assets={
            "data": ObservationAsset(
                uri=str(path),
                media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                roles=("data",),
                metadata={
                    "eo:bands": [
                        {"name": "red", "common_name": "red", "unit": "1"},
                        {"name": "near_infrared", "common_name": "near_infrared", "unit": "1"},
                    ],
                    "raster:bands": [
                        {"scale": 0.01, "offset": 0.0, "measurement_kind": "numeric"},
                        {"scale": 0.1, "offset": 2.0, "measurement_kind": "numeric"},
                    ],
                },
            )
        },
        provenance={"provider": "example catalog", "item_id": "item-1"},
        uncertainty={"source_uncertainty": {"kind": "provided_by_fixture"}},
        confidence=0.9,
    )


def _query(**overrides) -> EarthQuery:
    values = dict(
        point=(0.2, 0.2),
        requested_variables=("red", "near_infrared"),
        asset_sampling="point",
    )
    values.update(overrides)
    return EarthQuery(**values)


def test_raster_sampling_reads_declared_bands_and_preserves_uncertainty(raster_path):
    observation = _observation(raster_path)
    sampled, status = RasterAssetSamplingService(allow_local_files=True).sample(
        observation, _query()
    )

    assert status == "sampled"
    assert sampled.measured_variables["red"]["value"] == pytest.approx(0.2)
    assert sampled.measured_variables["near_infrared"]["value"] == pytest.approx(22.0)
    assert sampled.measured_variables["red"]["source_metadata"]["raw_value"] == 20
    assert sampled.measured_variables["red"]["source_metadata"]["pixel_row"] == 0
    assert sampled.measured_variables["red"]["source_metadata"]["pixel_column"] == 1
    assert sampled.measured_variables["red"]["source_metadata"][
        "pixel_support_geometry"
    ]["coordinates"][0][0] == (0.0, 1.0)
    assert len(sampled.canonical_measurements) == 2
    assert all(
        item.observation_id == sampled.observation_id
        for item in sampled.canonical_measurements
    )
    repeated, _ = RasterAssetSamplingService(allow_local_files=True).sample(
        observation, _query()
    )
    assert repeated.observation_id == sampled.observation_id
    assert sampled.uncertainty == {}
    assert sampled.confidence is None
    assert sampled.modalities == ("visual",)
    assert sampled.provenance["provider"] == "example catalog"
    assert sampled.provenance["satquery:asset_sampling"]["uncertainty"] == (
        "not provided by the source asset"
    )
    assert sampled.provenance["satquery:asset_sampling"]["source_spatial_support"][
        "provider_confidence"
    ] == 0.9
    assert sampled.provenance["satquery:asset_sampling"]["source_spatial_support"][
        "provider_uncertainty"
    ] == {"source_uncertainty": {"kind": "provided_by_fixture"}}


def test_raster_sampling_rejects_ambiguous_band_mapping(raster_path):
    observation = _observation(raster_path).model_copy(update={
        "assets": {
            **_observation(raster_path).assets,
            "duplicate": _observation(raster_path).assets["data"].model_copy(
                update={"uri": str(raster_path)}
            ),
        }
    })
    with pytest.raises(RasterAssetSamplingError, match="ambiguous"):
        RasterAssetSamplingService(allow_local_files=True).sample(observation, _query())


def test_raster_nodata_remains_missing_while_other_band_is_reported(raster_path):
    observation = _observation(raster_path)
    sampled, status = RasterAssetSamplingService(allow_local_files=True).sample(
        observation, _query(point=(-0.5, -0.5))
    )
    assert status == "sampled"
    assert "red" not in sampled.measured_variables
    assert sampled.measured_variables["near_infrared"]["value"] == pytest.approx(32.0)
    samples = sampled.provenance["satquery:asset_sampling"]["samples"]
    red = next(item for item in samples if item["variable"] == "red")
    assert red["status"] == "nodata"


def test_unmapped_bands_remain_unknown_and_preserve_the_catalog_observation(raster_path):
    observation = _observation(raster_path)
    query = _query(requested_variables=("snow_cover_fraction",))
    result, status = RasterAssetSamplingService(allow_local_files=True).sample(
        observation, query
    )
    assert status == "no_matching_bands"
    assert result.observation_id == observation.observation_id
    assert result.measured_variables == {}
    assert result.provenance["satquery:asset_sampling"]["status"] == "no_matching_bands"


class _FixtureStacConnector(StacCatalogConnector):
    def __init__(self, observation: Observation | tuple[Observation, ...]):
        super().__init__(configuration={
            "catalog_url": "https://catalog.example/stac/",
            "connector_id": "fixture-stac",
        })
        self.observation_fixture = (
            observation if isinstance(observation, tuple) else (observation,)
        )

    async def fetch(self, _request):
        return ObservationSearchResult(observations=self.observation_fixture)


def _observe_through_platform(connector, query):
    registry = InMemoryDatasetRegistry()
    registry.register(DatasetMetadata(
        connector_id="fixture-stac",
        dataset_id="surface-reflectance",
        provider="fixture-provider",
        variables=("red", "near_infrared"),
        modalities=("visual",),
        capabilities=("raster_point_sampling", "raster_zonal_analysis"),
    ))
    manager = ConnectorManager(dataset_registry=registry)
    manager.register(connector)
    engine = PerceptionEngine(
        manager,
        raster_asset_sampler=RasterAssetSamplingService(allow_local_files=True),
        raster_analysis_service=RasterAnalysisService(allow_local_files=True),
    )

    async def run():
        try:
            return await engine.observe(query)
        finally:
            await manager.stop_all()

    import asyncio

    return asyncio.run(run())


def test_stac_query_can_opt_in_to_measurement_extraction(raster_path):
    connector = _FixtureStacConnector(_observation(raster_path))
    result = _observe_through_platform(connector, _query())

    assert result.status == "complete"
    assert not result.processing_failures
    assert result.observations[0].measured_variables["red"]["value"] == pytest.approx(0.2)
    assert result.observations[0].geometry == {
        "type": "Point", "coordinates": (0.2, 0.2)
    }
    assert result.observations[0].observation_id.startswith("raster-sample:")
    assert result.observations[0].provenance["satquery:asset_sampling"][
        "parent_observation_id"
    ] == "stac-item-1"


def test_multitemporal_stac_samples_keep_each_source_time(raster_path):
    from datetime import datetime, timezone

    base = _observation(raster_path)
    observations = tuple(
        base.model_copy(update={
            "observation_id": f"item-{year}",
            "source_id": f"source-{year}",
            "observed_at": datetime(year, 6, 1, tzinfo=timezone.utc),
        })
        for year in (2024, 2025)
    )
    connector = _FixtureStacConnector(observations)
    result = _observe_through_platform(connector, _query())

    assert [item.observed_at.year for item in result.observations] == [2024, 2025]
    assert len({item.observation_id for item in result.observations}) == 2
    assert all(item.measured_variables["red"]["value"] == pytest.approx(0.2)
               for item in result.observations)
    red_stack = next(
        stack for stack in result.observation_stacks
        if stack.members[0].source_variable == "red"
    )
    assert red_stack.canonical_variable is None
    assert red_stack.variable_key == "source:catalog:surface-reflectance:red"
    assert [member.observed_at.year for member in red_stack.members] == [2024, 2025]
    assert all(
        member.provenance["satquery:asset_sampling"]["source_spatial_support"][
            "provider_uncertainty"
        ] == {"source_uncertainty": {"kind": "provided_by_fixture"}}
        for member in red_stack.members
    )


def test_multiscene_zonal_analysis_is_attached_per_source_scene(raster_path):
    from datetime import datetime, timezone

    base = _observation(raster_path)
    observations = tuple(
        base.model_copy(update={
            "observation_id": f"zonal-item-{year}",
            "source_id": f"zonal-source-{year}",
            "observed_at": datetime(year, 6, 1, tzinfo=timezone.utc),
        })
        for year in (2024, 2025)
    )
    query = EarthQuery(
        geometry={
            "type": "Polygon",
            "coordinates": [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
        },
        requested_variables=("red",),
        raster_analysis="zonal_descriptive",
        raster_pixel_selection="all_touched",
    )
    result = _observe_through_platform(_FixtureStacConnector(observations), query)

    assert result.status == "complete"
    assert not result.processing_failures
    assert len(result.observations) == 2
    products = [item.raster_analysis_products[0] for item in result.observations]
    assert {item.source_observation_id for item in products} == {
        "zonal-item-2024", "zonal-item-2025"
    }
    assert all(item.status == "computed" for item in products)
    assert all(item.statistics[0].valid_pixel_count == 3 for item in products)
    assert all("No resampling" in " ".join(item.limitations) for item in products)


def test_raster_processing_failure_is_reported_without_dropping_source_observation(
    raster_path,
):
    missing_path = raster_path.with_name("missing-raster-source.tif")
    source = _observation(raster_path)
    broken = source.model_copy(update={
        "assets": {
            "data": source.assets["data"].model_copy(update={"uri": str(missing_path)})
        }
    })
    result = _observe_through_platform(
        _FixtureStacConnector(broken), _query()
    )

    assert result.status == "partial"
    assert len(result.processing_failures) == 1
    failure = result.processing_failures[0]
    assert failure.observation_id == source.observation_id
    assert failure.stage == "raster_asset_sampling"
    assert result.observations[0].observation_id == source.observation_id
    assert result.observations[0].raster_analysis_products == ()


def test_requested_raster_bands_missing_from_scene_make_result_partial(raster_path):
    source = _observation(raster_path)
    asset = source.assets["data"]
    metadata = dict(asset.metadata)
    metadata["eo:bands"] = [{"name": "blue", "common_name": "blue"}]
    source = source.model_copy(update={
        "assets": {"data": asset.model_copy(update={"metadata": metadata})}
    })

    result = _observe_through_platform(_FixtureStacConnector(source), _query())

    assert result.status == "partial"
    assert len(result.processing_failures) == 1
    assert result.processing_failures[0].error_type == "NoCompatibleRasterBands"
    assert result.observations[0].observation_id == source.observation_id
    assert result.observations[0].provenance["satquery:asset_sampling"]["status"] == (
        "no_matching_bands"
    )


@pytest.mark.parametrize(
    "query, message",
    [
        ({"requested_variables": ("red",)}, "point query"),
        ({"point": (0, 0)}, "requested variables"),
    ],
)
def test_asset_sampling_contract_requires_explicit_point_and_variables(query, message):
    with pytest.raises(ValueError, match=message):
        EarthQuery(asset_sampling="point", **query)


def test_network_raster_sampling_rejects_local_files_by_default(raster_path):
    observation = _observation(raster_path)
    with pytest.raises(RasterAssetSamplingError, match="HTTPS assets"):
        RasterAssetSamplingService().sample(observation, _query())
