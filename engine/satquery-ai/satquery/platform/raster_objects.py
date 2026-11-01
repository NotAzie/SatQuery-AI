"""Deterministic polygonization of caller-labeled categorical raster cells.

This module does not classify pixels. It converts exact class values declared
by an investigation request into connected component geometries, preserving
the source raster window and all processing choices for audit and replay.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .contracts import EarthQuery, Observation, RasterComponentExtractionSpec
from .raster import RasterAssetSamplingError, _raster_uri


class RasterComponentExtractionError(ValueError):
    """A bounded extraction failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RasterCategoricalComponentExtractor:
    """Polygonize configured raster classes without assigning new semantics.

    ``allow_local_files`` is disabled by default, matching other raster readers.
    The maximum window size bounds memory use; requests exceeding the bound fail
    as a whole instead of returning a silently truncated component set.
    """

    operator_id = "satquery.raster-categorical-component-polygonizer"
    version = "1.0.0"

    def __init__(
        self,
        *,
        allow_local_files: bool = False,
        maximum_window_pixels: int = 4_000_000,
    ) -> None:
        if (
            isinstance(maximum_window_pixels, bool)
            or not isinstance(maximum_window_pixels, int)
            or maximum_window_pixels < 1
        ):
            raise ValueError("maximum_window_pixels must be a positive integer")
        self.allow_local_files = allow_local_files
        self.maximum_window_pixels = maximum_window_pixels

    def extract(
        self,
        observation: Observation,
        query: EarthQuery,
        specification: RasterComponentExtractionSpec,
    ) -> tuple[dict[str, Any], ...]:
        asset = observation.assets.get(specification.asset_key)
        if asset is None:
            raise RasterComponentExtractionError(
                "raster_asset_missing",
                f"Observation {observation.observation_id!r} has no raster asset "
                f"{specification.asset_key!r}.",
            )
        try:
            uri = _raster_uri(asset.uri, allow_local_files=self.allow_local_files)
        except RasterAssetSamplingError as exc:
            raise RasterComponentExtractionError(
                "raster_asset_missing", str(exc)
            ) from exc

        try:
            import numpy as np
            import rasterio
            from rasterio.errors import WindowError
            from rasterio.features import geometry_mask, geometry_window, shapes
            from rasterio.warp import transform_geom
            from shapely import make_valid
            from shapely.geometry import mapping, shape
        except ImportError as exc:
            raise RasterComponentExtractionError(
                "raster_processing_failed",
                "Categorical raster object extraction requires the optional raster dependencies.",
            ) from exc

        aoi = _query_geometry(query)
        try:
            with rasterio.open(uri) as dataset:
                if specification.band_index > dataset.count:
                    raise RasterComponentExtractionError(
                        "raster_band_invalid",
                        f"Band {specification.band_index} is outside asset band count {dataset.count}.",
                    )
                band_metadata = _band_metadata(asset.metadata, specification.band_index)
                names = {
                    value.strip().casefold()
                    for key in ("name", "common_name", "description")
                    if isinstance((value := band_metadata.get(key)), str)
                    and value.strip()
                }
                if specification.source_variable.strip().casefold() not in names:
                    raise RasterComponentExtractionError(
                        "raster_band_invalid",
                        "The selected asset band metadata does not explicitly declare "
                        f"source variable {specification.source_variable!r}.",
                    )
                if dataset.crs is None:
                    raise RasterComponentExtractionError(
                        "raster_crs_missing",
                        "Categorical raster asset has no declared CRS.",
                    )
                raster_aoi = transform_geom(
                    query.crs,
                    dataset.crs,
                    aoi,
                    antimeridian_cutting=True,
                    precision=-1,
                )
                try:
                    window = geometry_window(dataset, [raster_aoi])
                except WindowError as exc:
                    raise RasterComponentExtractionError(
                        "raster_no_matching_class",
                        "The requested area does not overlap the raster asset.",
                    ) from exc
                width, height = int(window.width), int(window.height)
                pixel_count = width * height
                if pixel_count > self.maximum_window_pixels:
                    raise RasterComponentExtractionError(
                        "raster_processing_failed",
                        f"Raster extraction window contains {pixel_count} cells; "
                        f"the configured limit is {self.maximum_window_pixels}.",
                    )

                band = dataset.read(
                    specification.band_index, window=window, masked=True
                )
                values = np.asarray(band.data)
                invalid = np.ma.getmaskarray(band)
                if np.issubdtype(values.dtype, np.floating):
                    invalid = invalid | ~np.isfinite(values)
                selected = ~geometry_mask(
                    [raster_aoi],
                    out_shape=(height, width),
                    transform=dataset.window_transform(window),
                    all_touched=specification.pixel_selection == "all_touched",
                )
                source_window_digest = _window_digest(
                    values,
                    invalid,
                    selected,
                    observation=observation,
                    specification=specification,
                    window=(int(window.row_off), int(window.col_off), height, width),
                    crs=str(dataset.crs),
                    transform=tuple(dataset.window_transform(window))[:6],
                )
                pixel_area = abs(
                    dataset.transform.a * dataset.transform.e
                    - dataset.transform.b * dataset.transform.d
                )
                if not math.isfinite(pixel_area) or pixel_area <= 0:
                    raise RasterComponentExtractionError(
                        "raster_processing_failed",
                        "Raster affine transform has no finite positive pixel area.",
                    )

                output: list[dict[str, Any]] = []
                requested_component_total = 0
                for class_mapping in specification.class_mappings:
                    class_mask = selected & ~invalid & (
                        values == class_mapping.class_value
                    )
                    if not np.any(class_mask):
                        continue
                    for geometry, class_value in shapes(
                        values,
                        mask=class_mask,
                        transform=dataset.window_transform(window),
                        connectivity=specification.connectivity,
                    ):
                        if class_value != class_mapping.class_value:
                            continue
                        polygon = shape(geometry)
                        geometry_repaired = not polygon.is_valid
                        if geometry_repaired:
                            polygon = make_valid(polygon)
                            if (
                                polygon.is_empty
                                or polygon.geom_type not in {"Polygon", "MultiPolygon"}
                                or not polygon.is_valid
                            ):
                                raise RasterComponentExtractionError(
                                    "raster_processing_failed",
                                    "Topology repair did not produce a valid polygonal component.",
                                )
                            geometry = mapping(polygon)
                        component_pixels = _geometry_area(geometry) / pixel_area
                        rounded_pixels = round(component_pixels)
                        if not math.isclose(
                            component_pixels,
                            rounded_pixels,
                            rel_tol=1e-7,
                            abs_tol=1e-6,
                        ) or rounded_pixels < 1:
                            raise RasterComponentExtractionError(
                                "raster_processing_failed",
                                "Polygonized component area did not resolve to an integral pixel count.",
                            )
                        if rounded_pixels < specification.minimum_component_pixels:
                            continue
                        geometry_digest = _digest(geometry)
                        identity_payload = {
                            "observation_id": observation.observation_id,
                            "dataset_id": (
                                observation.dataset.dataset_id
                                if observation.dataset
                                else None
                            ),
                            "asset_key": specification.asset_key,
                            "asset_checksum": asset.checksum,
                            "source_window_sha256": source_window_digest,
                            "band_index": specification.band_index,
                            "class_value": class_mapping.class_value,
                            "geometry_sha256": geometry_digest,
                            "connectivity": specification.connectivity,
                            "pixel_selection": specification.pixel_selection,
                        }
                        identity = _digest(identity_payload)
                        output.append(
                            {
                                "component_identity": identity,
                                "class_value": class_mapping.class_value,
                                "object_type": class_mapping.object_type,
                                "pixel_count": rounded_pixels,
                                "geometry": geometry,
                                "crs": str(dataset.crs),
                                "operator_id": self.operator_id,
                                "operator_version": self.version,
                                "source": {
                                    "observation_id": observation.observation_id,
                                    "dataset": (
                                        observation.dataset.model_dump(mode="json")
                                        if observation.dataset
                                        else None
                                    ),
                                    "asset_key": specification.asset_key,
                                    "asset_uri": asset.uri,
                                    "asset_checksum": asset.checksum,
                                    "asset_checksum_verified": False,
                                    "band_index": specification.band_index,
                                    "source_variable": specification.source_variable,
                                    "band_metadata": band_metadata,
                                },
                                "processing": {
                                    "source_window_sha256": source_window_digest,
                                    "window_row_col_height_width": (
                                        int(window.row_off),
                                        int(window.col_off),
                                        height,
                                        width,
                                    ),
                                    "window_transform": tuple(
                                        dataset.window_transform(window)
                                    )[:6],
                                    "connectivity": specification.connectivity,
                                    "pixel_selection": specification.pixel_selection,
                                    "minimum_component_pixels": specification.minimum_component_pixels,
                                    "component_geometry_sha256": geometry_digest,
                                    "geometry_topology_repaired": geometry_repaired,
                                    "geometry_repair_method": (
                                        "shapely.make_valid" if geometry_repaired else None
                                    ),
                                    "class_mapping_origin": "explicit_query_configuration",
                                    "rasterio_version": rasterio.__version__,
                                    "gdal_version": rasterio.__gdal_version__,
                                    "numpy_version": np.__version__,
                                },
                            }
                        )
                        requested_component_total += 1
                        if requested_component_total > specification.maximum_components:
                            raise RasterComponentExtractionError(
                                "raster_component_limit_exceeded",
                                "Matching components exceed maximum_components; no partial component set was returned.",
                            )
        except RasterComponentExtractionError:
            raise
        except Exception as exc:
            raise RasterComponentExtractionError(
                "raster_processing_failed",
                f"Raster component extraction failed ({type(exc).__name__}); "
                "source-specific exception details were omitted.",
            ) from exc

        if not output:
            raise RasterComponentExtractionError(
                "raster_no_matching_class",
                "No configured class values were present in the selected raster area.",
            )
        return tuple(
            sorted(
                output,
                key=lambda item: (
                    float(item["class_value"]),
                    item["component_identity"],
                ),
            )
        )


def _query_geometry(query: EarthQuery) -> dict[str, Any]:
    if query.geometry is not None:
        if query.geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise RasterComponentExtractionError(
                "raster_processing_failed",
                "Categorical raster extraction requires a polygon AOI.",
            )
        return query.geometry
    if query.bbox is not None:
        min_x, min_y, max_x, max_y = query.bbox[:4]
        return {
            "type": "Polygon",
            "coordinates": [[
                [min_x, min_y],
                [max_x, min_y],
                [max_x, max_y],
                [min_x, max_y],
                [min_x, min_y],
            ]],
        }
    raise RasterComponentExtractionError(
        "raster_processing_failed",
        "Categorical raster extraction requires a polygon AOI or bbox.",
    )


def _band_metadata(asset_metadata: dict[str, Any], band_index: int) -> dict[str, Any]:
    records = []
    for field in ("eo:bands", "raster:bands"):
        value = asset_metadata.get(field, ())
        if isinstance(value, (list, tuple)) and band_index <= len(value):
            record = value[band_index - 1]
            if isinstance(record, dict):
                records.append(record)
    if not records:
        raise RasterComponentExtractionError(
            "raster_band_invalid",
            "The selected asset does not contain declared per-band metadata.",
        )
    merged: dict[str, Any] = {}
    for record in records:
        merged.update(record)
    return merged


def _geometry_area(geometry: dict[str, Any]) -> float:
    geometry_type = geometry.get("type")
    if geometry_type == "Polygon":
        polygons = (geometry.get("coordinates", ()),)
    elif geometry_type == "MultiPolygon":
        polygons = geometry.get("coordinates", ())
    else:
        raise RasterComponentExtractionError(
            "raster_processing_failed",
            f"Unsupported polygonized geometry type {geometry_type!r}.",
        )
    total = 0.0
    for rings in polygons:
        ring_areas = []
        for ring in rings:
            area = 0.0
            for left, right in zip(ring, (*ring[1:], ring[0])):
                area += left[0] * right[1] - right[0] * left[1]
            ring_areas.append(abs(area) / 2.0)
        if ring_areas:
            total += ring_areas[0] - sum(ring_areas[1:])
    return total


def _window_digest(
    values,
    invalid,
    selected,
    *,
    observation: Observation,
    specification: RasterComponentExtractionSpec,
    window: tuple[int, int, int, int],
    crs: str,
    transform: tuple[float, ...],
) -> str:
    import numpy as np

    array = np.asarray(values)
    little_endian = array.astype(array.dtype.newbyteorder("<"), copy=False)
    digest = hashlib.sha256()
    metadata = {
        "observation_id": observation.observation_id,
        "asset_key": specification.asset_key,
        "band_index": specification.band_index,
        "window": window,
        "crs": crs,
        "transform": transform,
        "dtype": little_endian.dtype.str,
        "shape": little_endian.shape,
        "specification": specification.model_dump(mode="json"),
    }
    digest.update(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    digest.update(np.ascontiguousarray(little_endian).tobytes())
    digest.update(np.ascontiguousarray(invalid, dtype=np.uint8).tobytes())
    digest.update(np.ascontiguousarray(selected, dtype=np.uint8).tobytes())
    return digest.hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
