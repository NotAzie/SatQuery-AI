"""Provider-neutral GeoJSON export for Earth Objects.

RFC 7946 coordinates are longitude/latitude in WGS 84. Earth Object geometries
with missing, projected, or otherwise unsupported CRS are therefore excluded
instead of being silently relabeled or transformed.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from .contracts import EarthObject


_GEOGRAPHIC_CRS = {"EPSG:4326", "OGC:CRS84", "CRS84", "OGC:CRS:84"}
_COORDINATE_DEPTH = {
    "Point": 0,
    "MultiPoint": 1,
    "LineString": 1,
    "MultiLineString": 2,
    "Polygon": 2,
    "MultiPolygon": 3,
}


def _valid_position(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
            for item in value
        )
        and -180 <= value[0] <= 180
        and -90 <= value[1] <= 90
    )


def _valid_coordinates(value: Any, depth: int) -> bool:
    if depth == 0:
        return _valid_position(value)
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and all(_valid_coordinates(item, depth - 1) for item in value)
    )


def _valid_geometry(geometry: Any) -> bool:
    if not isinstance(geometry, dict):
        return False
    geometry_type = geometry.get("type")
    if geometry_type == "GeometryCollection":
        items = geometry.get("geometries")
        return isinstance(items, (list, tuple)) and all(
            _valid_geometry(item) for item in items
        )
    depth = _COORDINATE_DEPTH.get(geometry_type)
    coordinates = geometry.get("coordinates")
    if depth is None or not _valid_coordinates(coordinates, depth):
        return False
    if geometry_type == "LineString":
        return len(coordinates) >= 2
    if geometry_type == "MultiLineString":
        return all(len(line) >= 2 for line in coordinates)
    if geometry_type == "Polygon":
        rings = coordinates
    elif geometry_type == "MultiPolygon":
        rings = [ring for polygon in coordinates for ring in polygon]
    else:
        rings = []
    return all(len(ring) >= 4 and ring[0] == ring[-1] for ring in rings)


def earth_objects_to_geojson(objects: Iterable[EarthObject]) -> dict[str, Any]:
    """Return RFC 7946 features and explicit reasons for omitted objects.

    This operation only serializes already-materialized geometry. It does not
    reproject, repair, simplify, or infer coordinates.
    """

    features: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    for item in objects:
        if item.geometry is None:
            omitted.append({"object_id": item.object_id, "reason": "geometry_unknown"})
            continue
        normalized_crs = item.crs.strip().upper() if item.crs else None
        if normalized_crs not in _GEOGRAPHIC_CRS:
            omitted.append({"object_id": item.object_id, "reason": "crs_not_supported_for_geojson"})
            continue
        if not _valid_geometry(item.geometry):
            omitted.append({"object_id": item.object_id, "reason": "invalid_geographic_geometry"})
            continue
        features.append(
            {
                "type": "Feature",
                "id": item.object_id,
                "geometry": item.geometry,
                "properties": {
                    "object_id": item.object_id,
                    "object_type": item.object_type,
                    "revision": item.revision,
                    "lifecycle": item.lifecycle,
                    "investigation_ids": list(item.investigation_ids),
                    "source_observation_ids": list(item.source_observation_ids),
                    "evidence_ids": list(item.evidence_ids),
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "satquery:omitted_objects": omitted,
        "satquery:geometry_policy": "WGS 84 longitude/latitude only; no reprojection or repair",
    }
