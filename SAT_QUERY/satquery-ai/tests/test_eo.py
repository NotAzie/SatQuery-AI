from __future__ import annotations

import json

import numpy as np
import pytest
from rasterio.transform import from_origin

from satquery.config import Settings
from satquery.eo.data import from_array, load_eo_raster
from satquery.eo.discovery import DiscoveryQuery, ImageryCandidate, StacDiscoveryProvider
from satquery.eo.raster import calculate_area, raster_statistics, safe_expression
from satquery.eo.spectral import calculate_index
from satquery.orchestrator import SatQueryEngine


def write_geotiff(path, data, *, crs="EPSG:3857", transform=None, nodata=-9999):
    import rasterio

    transform = transform or from_origin(0, 100, 10, 10)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[2],
        height=data.shape[1],
        count=data.shape[0],
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(data.astype("float32"))
        for index, name in enumerate(("red", "green", "blue", "nir", "swir", "swir2"), 1):
            if index <= data.shape[0]:
                dataset.set_band_description(index, name)


def test_geotiff_metadata_and_nodata_are_preserved(tmp_path):
    data = np.stack([np.ones((4, 5)), np.full((4, 5), 2.0)])
    data[0, 0, 0] = -9999
    path = tmp_path / "scene.tif"
    write_geotiff(path, data)

    raster = load_eo_raster(path)

    assert raster.is_georeferenced
    assert raster.crs == "EPSG:3857"
    assert raster.shape == (2, 4, 5)
    assert raster.band_names[:2] == ("red", "green")
    assert raster.nodata == -9999
    assert raster.valid_mask.sum() == 19


def test_rgb_fallback_is_explicitly_non_georeferenced(tmp_path):
    from PIL import Image

    path = tmp_path / "rgb.png"
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(path)

    raster = load_eo_raster(path)

    assert raster.is_georeferenced is False
    assert any(warning.code == "non_georeferenced_fallback" for warning in raster.warnings)


def test_safe_expression_rejects_python_execution():
    bands = {"red": np.ones((2, 2)), "nir": np.full((2, 2), 3.0)}
    assert np.allclose(safe_expression("(nir - red) / (nir + red)", bands), 0.5)
    with pytest.raises(ValueError):
        safe_expression("__import__('os').system('x')", bands)


def test_area_requires_georeferencing_and_uses_projected_resolution():
    mask = np.array([[True, False], [True, True]])
    projected = from_array(
        np.zeros((1, 2, 2)),
        crs="EPSG:3857",
        transform=tuple(from_origin(0, 20, 10, 10)),
        bounds=(0, 0, 20, 20),
    )
    area = calculate_area(mask, projected)
    assert area["area_available"] is True
    assert area["area_m2"] == pytest.approx(300.0)

    fallback = from_array(np.zeros((1, 2, 2)))
    unavailable = calculate_area(mask, fallback)
    assert unavailable["area_available"] is False
    assert unavailable["area_m2"] is None


def test_indices_use_named_bands_and_fail_explicitly_when_missing():
    raster = from_array(
        np.stack([np.full((2, 2), 0.2), np.full((2, 2), 0.8)]),
        band_names=("red", "nir"),
    )
    result = calculate_index(raster, "ndvi")
    assert np.allclose(result.values, 0.6 / 1.0)
    assert result.provenance["parameters"]["formula"]

    with pytest.raises(ValueError, match="requires bands"):
        calculate_index(raster, "ndwi")


def test_discovery_filtering_is_provider_neutral():
    candidates = [
        ImageryCandidate("cloudy", "test", "c", "2024-01-01", None, None, {}, {"eo:cloud_cover": 80}),
        ImageryCandidate("clear", "test", "c", "2024-01-02", None, None, {}, {"eo:cloud_cover": 5}),
    ]
    ranked = StacDiscoveryProvider._filter_and_rank(candidates, DiscoveryQuery(max_cloud_cover=20))
    assert [candidate.item_id for candidate in ranked] == ["clear"]
    assert all(candidate.state == "DISCOVERED" for candidate in ranked)


def test_scientific_tool_runs_without_vision_backend(tmp_path):
    data = np.stack([
        np.full((32, 32), 0.2),
        np.full((32, 32), 0.1),
        np.full((32, 32), 0.8),
        np.full((32, 32), 0.8),
    ])
    path = tmp_path / "ndvi.tif"
    write_geotiff(path, data)
    settings = Settings(image_root=str(tmp_path), router_mode="rules", max_image_pixels=384)
    engine = SatQueryEngine(settings)

    response = engine.answer("calculate NDVI", image_paths=[str(path)])

    assert response.intent.value == "SPECTRAL_INDEX"
    assert response.results[0].data["index"] == "NDVI"
    assert response.results[0].backend.value == "none"
