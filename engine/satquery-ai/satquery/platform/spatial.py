"""Optional geospatial helpers shared by perception adapters."""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import import_module
from numbers import Integral
from typing import Any, Iterable, Mapping, Optional, Sequence


def _geospatial_modules() -> tuple[Any, Any, Any]:
    try:
        pyproj = import_module("pyproj")
        geometry = import_module("shapely.geometry")
        operations = import_module("shapely.ops")
        validation = import_module("shapely.validation")
    except ImportError as exc:
        raise RuntimeError(
            "Spatial operations require the optional 'geospatial' dependencies"
        ) from exc
    return (
        pyproj.CRS,
        (pyproj.Transformer, operations.transform),
        (
            geometry.box,
            geometry.mapping,
            geometry.shape,
            validation.make_valid,
        ),
    )


def normalize_geometry(
    geometry: Mapping[str, Any], *, source_crs: str, target_crs: str = "OGC:CRS84"
) -> dict[str, Any]:
    """Validate, repair invalid topology, and reproject a GeoJSON geometry."""
    CRS, transform_modules, geometry_modules = _geospatial_modules()
    Transformer, transform = transform_modules
    box, mapping, shape, make_valid = geometry_modules
    del box
    source = CRS.from_user_input(source_crs)
    target = CRS.from_user_input(target_crs)
    parsed = shape(dict(geometry))
    if parsed.is_empty:
        raise ValueError("geometry must not be empty")
    valid = parsed if parsed.is_valid else make_valid(parsed)
    if valid.is_empty:
        raise ValueError("geometry is empty after topology validation")
    if source != target:
        transformer = Transformer.from_crs(source, target, always_xy=True)
        valid = transform(transformer.transform, valid)
    if valid.is_empty or not valid.is_valid:
        raise ValueError("geometry is invalid in the target CRS")
    return dict(mapping(valid))


def bbox_geometry(
    bounds: Sequence[float],
) -> dict[str, Any]:
    """Convert a four-coordinate bbox to a GeoJSON polygon."""
    if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
        raise ValueError("bbox must contain four finite coordinates")
    min_x, min_y, max_x, max_y = bounds
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("bbox minimum coordinates must be less than maximum")
    _, _, (box, mapping, _, _) = _geospatial_modules()
    return dict(mapping(box(min_x, min_y, max_x, max_y)))


def tile_bbox(
    bounds: Sequence[float], *, tile_width: float, tile_height: float
) -> tuple[tuple[float, float, float, float], ...]:
    """Partition a planar bbox into row-major tiles, clipping edge tiles."""
    if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
        raise ValueError("bbox must contain four finite coordinates")
    min_x, min_y, max_x, max_y = bounds
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("bbox minimum coordinates must be less than maximum")
    if not math.isfinite(tile_width) or not math.isfinite(tile_height):
        raise ValueError("tile dimensions must be finite")
    if tile_width <= 0 or tile_height <= 0:
        raise ValueError("tile dimensions must be positive")
    tiles: list[tuple[float, float, float, float]] = []
    y = min_y
    while y < max_y:
        top = min(y + tile_height, max_y)
        if top <= y:
            raise ValueError("tile_height is too small for bbox coordinate magnitude")
        x = min_x
        while x < max_x:
            right = min(x + tile_width, max_x)
            if right <= x:
                raise ValueError(
                    "tile_width is too small for bbox coordinate magnitude"
                )
            tiles.append((x, y, right, top))
            x = right
        y = top
    return tuple(tiles)


@dataclass(frozen=True)
class SpatialFeature:
    feature_id: str
    geometry: Mapping[str, Any]
    properties: Mapping[str, Any]


@dataclass(frozen=True)
class AreaOfInterest:
    geometry: Mapping[str, Any]
    crs: str

    def normalized(self, *, target_crs: str = "OGC:CRS84") -> "AreaOfInterest":
        return AreaOfInterest(
            geometry=normalize_geometry(
                self.geometry, source_crs=self.crs, target_crs=target_crs
            ),
            crs=normalize_crs(target_crs),
        )

    def tiles(
        self, *, tile_width: float, tile_height: float
    ) -> tuple["AreaOfInterest", ...]:
        _, _, (box, mapping, shape, _) = _geospatial_modules()
        geometry = shape(dict(self.geometry))
        bounds = geometry.bounds
        tiles: list[AreaOfInterest] = []
        for min_x, min_y, max_x, max_y in tile_bbox(
            bounds, tile_width=tile_width, tile_height=tile_height
        ):
            intersection = geometry.intersection(box(min_x, min_y, max_x, max_y))
            if not intersection.is_empty:
                tiles.append(
                    AreaOfInterest(
                        geometry=dict(mapping(intersection)),
                        crs=self.crs,
                    )
                )
        return tuple(tiles)


class SpatialIndex:
    """In-memory STRtree-backed index; result order follows input order."""

    def __init__(self, features: Iterable[SpatialFeature], *, crs: str) -> None:
        self.crs = crs
        self.features = tuple(features)
        try:
            geometry = import_module("shapely.geometry")
            STRtree = import_module("shapely.strtree").STRtree
        except ImportError as exc:
            raise RuntimeError(
                "Spatial indexing requires the optional 'geospatial' dependencies"
            ) from exc
        self._geometries = tuple(
            geometry.shape(dict(feature.geometry)) for feature in self.features
        )
        self._tree = STRtree(self._geometries)
        self._indices = {
            (geom.wkb, index) for index, geom in enumerate(self._geometries)
        }
        self._indices_by_wkb: dict[bytes, list[int]] = {}
        for wkb, index in self._indices:
            self._indices_by_wkb.setdefault(wkb, []).append(index)

    def query(self, geometry: Mapping[str, Any]) -> tuple[SpatialFeature, ...]:
        """Return features intersecting a geometry expressed in the index CRS."""
        try:
            shape = import_module("shapely.geometry").shape
        except ImportError as exc:
            raise RuntimeError(
                "Spatial indexing requires the optional 'geospatial' dependencies"
            ) from exc
        candidates = self._tree.query(shape(dict(geometry)))
        indices: set[int] = set()
        for candidate in candidates:
            if isinstance(candidate, Integral):
                indices.add(int(candidate))
            else:
                indices.update(self._indices_by_wkb[candidate.wkb])
        return tuple(self.features[index] for index in sorted(indices))


class SpatialService:
    """Reusable spatial operations shared by platform code and connectors."""

    def normalize_aoi(
        self, geometry: Mapping[str, Any], *, crs: str
    ) -> AreaOfInterest:
        return AreaOfInterest(
            geometry=normalize_geometry(
                geometry, source_crs=crs, target_crs="OGC:CRS84"
            ),
            crs="OGC:CRS84",
        )

    def reproject(
        self, geometry: Mapping[str, Any], *, source_crs: str, target_crs: str
    ) -> dict[str, Any]:
        return transform_geometry(
            geometry, source_crs=source_crs, target_crs=target_crs
        )

    def buffer(
        self,
        geometry: Mapping[str, Any],
        *,
        distance: float,
        crs: str,
        distance_unit: Optional[str] = None,
    ) -> dict[str, Any]:
        return buffer_geometry(
            geometry, distance=distance, crs=crs, distance_unit=distance_unit
        )

    def intersects(
        self, first: Mapping[str, Any], second: Mapping[str, Any]
    ) -> bool:
        return geometry_intersects(first, second)

    def contains(
        self, container: Mapping[str, Any], candidate: Mapping[str, Any]
    ) -> bool:
        return geometry_contains(container, candidate)

    def distance(
        self, first: Mapping[str, Any], second: Mapping[str, Any], *, crs: str
    ) -> float:
        return geometry_distance(first, second, crs=crs)


def simplify_geometry(
    geometry: Mapping[str, Any], *, tolerance: float, preserve_topology: bool = True
) -> dict[str, Any]:
    """Simplify a geometry in its current CRS without changing its CRS."""
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("simplification tolerance must be finite and non-negative")
    try:
        shapely_geometry = import_module("shapely.geometry")
    except ImportError as exc:
        raise RuntimeError(
            "Geometry simplification requires the optional 'geospatial' dependencies"
        ) from exc
    simplified = shapely_geometry.shape(dict(geometry)).simplify(
        tolerance, preserve_topology=preserve_topology
    )
    if simplified.is_empty:
        raise ValueError("geometry is empty after simplification")
    return dict(shapely_geometry.mapping(simplified))


def query_intersects_coverage(
    query: Any, coverage: Mapping[str, Any], *, coverage_crs: str
) -> bool:
    """Test an EarthQuery AOI against GeoJSON coverage in its declared CRS."""
    try:
        geometry_module = import_module("shapely.geometry")
        operations = import_module("shapely.ops")
        pyproj = import_module("pyproj")
    except ImportError as exc:
        raise RuntimeError(
            "Dataset spatial coverage checks require the optional 'geospatial' dependencies"
        ) from exc
    if query.point is not None:
        aoi = geometry_module.Point(query.point)
    elif query.bbox is not None:
        min_x, min_y = query.bbox[:2]
        max_x, max_y = (
            query.bbox[2:4] if len(query.bbox) == 4 else query.bbox[3:5]
        )
        if min_x > max_x and query.crs.casefold() in {
            "crs84",
            "ogc:crs84",
            "epsg:4326",
            "urn:ogc:def:crs:ogc:1.3:crs84",
        }:
            aoi = geometry_module.MultiPolygon(
                (
                    geometry_module.box(min_x, min_y, 180, max_y),
                    geometry_module.box(-180, min_y, max_x, max_y),
                )
            )
        else:
            aoi = geometry_module.box(min_x, min_y, max_x, max_y)
    elif query.geometry is not None:
        aoi = geometry_module.shape(dict(query.geometry))
    else:
        return True
    coverage_geometry = geometry_module.shape(dict(coverage))
    source = pyproj.CRS.from_user_input(query.crs)
    target = pyproj.CRS.from_user_input(coverage_crs)
    if source != target:
        transformer = pyproj.Transformer.from_crs(source, target, always_xy=True)
        aoi = operations.transform(transformer.transform, aoi)
    return bool(aoi.intersects(coverage_geometry))


def normalize_crs(crs: str) -> str:
    """Return an authority identifier where available, otherwise WKT2."""
    try:
        pyproj = import_module("pyproj")
    except ImportError as exc:
        raise RuntimeError("CRS normalization requires the optional pyproj dependency") from exc
    resolved = pyproj.CRS.from_user_input(crs)
    authority = resolved.to_authority()
    if authority is not None:
        return f"{authority[0]}:{authority[1]}"
    return resolved.to_wkt("WKT2_2019")


def transform_geometry(
    geometry: Mapping[str, Any], *, source_crs: str, target_crs: str
) -> dict[str, Any]:
    """Reproject a geometry between declared coordinate reference systems."""
    normalized = normalize_geometry(
        geometry, source_crs=source_crs, target_crs=target_crs
    )
    return normalized


def buffer_geometry(
    geometry: Mapping[str, Any],
    *,
    distance: float,
    crs: str,
    distance_unit: Optional[str] = None,
) -> dict[str, Any]:
    """Buffer geometry in a projected CRS; geographic degrees are rejected."""
    if not math.isfinite(distance) or distance < 0:
        raise ValueError("buffer distance must be finite and non-negative")
    CRS, _, (box, mapping, shape, _) = _geospatial_modules()
    del box
    source = CRS.from_user_input(crs)
    if source.is_geographic and distance != 0:
        raise ValueError("metric buffering requires a projected CRS")
    if distance_unit is not None and source.axis_info:
        axis_unit = source.axis_info[0].unit_name.casefold()
        if distance_unit.casefold() not in {
            axis_unit,
            "m" if axis_unit in {"metre", "meter", "metres", "meters"} else axis_unit,
        }:
            raise ValueError("buffer distance unit must match the CRS axis unit")
    buffered = shape(dict(geometry)).buffer(distance)
    if buffered.is_empty or not buffered.is_valid:
        raise ValueError("buffer operation produced invalid geometry")
    return dict(mapping(buffered))


def geometry_distance(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    crs: str,
) -> float:
    """Return planar geometry distance in the supplied CRS coordinate units."""
    CRS, _, (box, _, shape, _) = _geospatial_modules()
    del box
    resolved = CRS.from_user_input(crs)
    if resolved.is_geographic:
        raise ValueError("planar distance requires a projected CRS")
    return float(shape(dict(first)).distance(shape(dict(second))))


def geometry_intersects(
    first: Mapping[str, Any], second: Mapping[str, Any]
) -> bool:
    """Return whether two geometries in the same CRS intersect."""
    _, _, (box, _, shape, _) = _geospatial_modules()
    del box
    return bool(shape(dict(first)).intersects(shape(dict(second))))


def geometry_contains(
    container: Mapping[str, Any], candidate: Mapping[str, Any]
) -> bool:
    """Return whether one geometry wholly contains another in the same CRS."""
    _, _, (box, _, shape, _) = _geospatial_modules()
    del box
    return bool(shape(dict(container)).contains(shape(dict(candidate))))
