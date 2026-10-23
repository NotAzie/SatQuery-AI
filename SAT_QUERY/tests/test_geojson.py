from fastapi.testclient import TestClient

from satquery.api import create_app, set_engine
from satquery.config import get_settings
from satquery.orchestrator import SatQueryEngine
from satquery.platform.contracts import EarthObject
from satquery.platform.geojson import earth_objects_to_geojson


def _object(object_id, *, geometry=None, crs=None):
    return EarthObject(
        object_id=object_id,
        object_type="earth:TestFeature",
        source_observation_ids=(f"observation-{object_id}",),
        geometry=geometry,
        crs=crs,
    )


def test_geojson_exports_only_valid_declared_wgs84_geometry():
    point = _object("point-1", geometry={"type": "Point", "coordinates": [12.5, -8.25]}, crs="OGC:CRS84")
    polygon = _object(
        "polygon-1",
        geometry={
            "type": "Polygon",
            "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 10]]],
        },
        crs="EPSG:4326",
    )
    projected = _object("projected", geometry={"type": "Point", "coordinates": [100, 200]}, crs="EPSG:3857")
    unknown = _object("unknown", geometry={"type": "Point", "coordinates": [1, 2]})
    invalid = _object("invalid", geometry={"type": "Point", "coordinates": [181, 2]}, crs="EPSG:4326")

    result = earth_objects_to_geojson((point, polygon, projected, unknown, invalid))

    assert result["type"] == "FeatureCollection"
    assert [item["id"] for item in result["features"]] == ["point-1", "polygon-1"]
    assert result["features"][0]["geometry"] == point.geometry
    assert result["satquery:omitted_objects"] == [
        {"object_id": "projected", "reason": "crs_not_supported_for_geojson"},
        {"object_id": "unknown", "reason": "crs_not_supported_for_geojson"},
        {"object_id": "invalid", "reason": "invalid_geographic_geometry"},
    ]


def test_geojson_export_is_exposed_through_api_with_geojson_media_type():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.earth_objects.put(
        _object("api-point", geometry={"type": "Point", "coordinates": [20, 30]}, crs="EPSG:4326")
    )
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            response = client.get("/api/v1/platform/earth-objects/geojson")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/geo+json")
            assert response.json()["features"][0]["id"] == "api-point"
    finally:
        set_engine(None)

