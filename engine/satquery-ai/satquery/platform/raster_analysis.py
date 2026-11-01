"""Bounded, provider-neutral descriptive analysis of raster assets."""

from __future__ import annotations

import hashlib
import json
import math
import platform
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

from .contracts import (
    EarthQuery,
    Observation,
    RasterAnalysisProduct,
    RasterBandStatistics,
)
from .ontology import EARTH_VARIABLE_ONTOLOGY
from .raster import RasterAssetSamplingError, _canonical_variable, _raster_uri


class RasterAnalysisService:
    """Compute explicitly requested zonal descriptive statistics.

    The service uses the raster's native grid and never resamples. Cell
    selection is explicit in the query. Statistics are cell-weighted; they are
    not area-weighted and are not scientific inference. Categorical ontology
    variables receive code frequencies instead of numeric moments. Source
    uncertainty metadata is preserved but not propagated.
    """

    VERSION = "1.1.0"

    def __init__(
        self, *, allow_local_files: bool = False, maximum_window_pixels: int = 4_000_000
    ) -> None:
        if (
            isinstance(maximum_window_pixels, bool)
            or not isinstance(maximum_window_pixels, int)
            or maximum_window_pixels < 1
        ):
            raise ValueError("maximum_window_pixels must be a positive integer")
        self.allow_local_files = allow_local_files
        self.maximum_window_pixels = maximum_window_pixels

    def analyze(
        self, observation: Observation, query: EarthQuery
    ) -> tuple[Observation, str]:
        if query.raster_analysis != "zonal_descriptive":
            raise ValueError("Zonal raster analysis was not requested")
        if query.geometry is None or query.raster_pixel_selection is None:
            raise ValueError(
                "Zonal analysis requires geometry and pixel-selection method"
            )
        _validate_polygon_coordinates(query.geometry, query.crs)

        candidates = _resolve_bands(observation, query.requested_variables)
        missing = tuple(name for name, matches in candidates.items() if not matches)
        if all(not matches for matches in candidates.values()):
            product = _empty_observation_product(observation, query, missing)
            return observation.model_copy(
                update={
                    "raster_analysis_products": (
                        *observation.raster_analysis_products,
                        product,
                    )
                }
            ), "no_matching_bands"
        ambiguous = [name for name, matches in candidates.items() if len(matches) > 1]
        if ambiguous:
            raise RasterAssetSamplingError(
                f"Raster assets have ambiguous bands for requested variables: {ambiguous}."
            )

        try:
            import numpy as np
            import rasterio
            from rasterio.errors import WindowError
            from rasterio.features import geometry_mask, geometry_window
            from rasterio.warp import transform_geom
        except ImportError as exc:
            raise RasterAssetSamplingError(
                "Zonal raster analysis requires the optional 'raster' dependencies."
            ) from exc
        if query.raster_weighting == "geodesic_cell_area":
            try:
                import pyproj
                from pyproj import CRS
            except ImportError as exc:
                raise RasterAssetSamplingError(
                    "Geodesic area weighting requires the optional 'geospatial' dependencies."
                ) from exc

        products: list[RasterAnalysisProduct] = []
        for asset_key, matches in _group_bands(candidates).items():
            asset = observation.assets[asset_key]
            uri = _raster_uri(asset.uri, allow_local_files=self.allow_local_files)
            try:
                with rasterio.open(uri) as dataset:
                    if dataset.crs is None:
                        raise RasterAssetSamplingError(
                            f"Raster asset {asset_key!r} has no declared CRS."
                        )
                    raster_geometry = transform_geom(
                        query.crs,
                        dataset.crs,
                        query.geometry,
                        antimeridian_cutting=True,
                        precision=-1,
                    )
                    try:
                        window = geometry_window(dataset, [raster_geometry])
                    except WindowError:
                        products.append(
                            _empty_product(
                                observation,
                                query,
                                asset_key,
                                asset.checksum,
                                0,
                                missing,
                                "analysis geometry does not overlap raster extent",
                                status="no_overlap",
                            )
                        )
                        continue
                    width, height = int(window.width), int(window.height)
                    window_pixels = width * height
                    if window_pixels > self.maximum_window_pixels:
                        raise RasterAssetSamplingError(
                            f"Raster analysis window contains {window_pixels} cells; "
                            f"configured maximum is {self.maximum_window_pixels}."
                        )
                    weighting_method = query.raster_weighting or "equal_cell"
                    row_areas = None
                    if weighting_method == "geodesic_cell_area":
                        row_areas = _geodesic_row_areas(
                            dataset, window, CRS.from_user_input(dataset.crs)
                        )
                    inclusion = query.raster_pixel_selection == "all_touched"
                    selected = ~geometry_mask(
                        [raster_geometry],
                        out_shape=(height, width),
                        transform=dataset.window_transform(window),
                        all_touched=inclusion,
                    )
                    selected_count = int(np.count_nonzero(selected))
                    if selected_count == 0:
                        products.append(
                            _empty_product(
                                observation,
                                query,
                                asset_key,
                                asset.checksum,
                                selected_count,
                                missing,
                                "geometry selects no cells in this asset",
                                status="no_selected_cells",
                            )
                        )
                        continue

                    indexes = sorted({band_index for _, band_index, _, _ in matches})
                    statistics = []
                    for variable, band_index, source_name, metadata in matches:
                        pixel_sampling = metadata.get(
                            "sampling", metadata.get("raster:sampling")
                        )
                        if (
                            pixel_sampling == "point"
                            and query.raster_pixel_selection == "all_touched"
                        ):
                            raise RasterAssetSamplingError(
                                f"Band {source_name!r} declares point sampling and cannot use all_touched selection."
                            )
                        band = dataset.read(band_index, window=window, masked=True)
                        valid = selected & ~np.ma.getmaskarray(band)
                        raw_values = np.asarray(band.data[valid], dtype=np.float64)
                        if raw_values.size and not np.isfinite(raw_values).all():
                            raise RasterAssetSamplingError(
                                f"Raster asset {asset_key!r} contains non-finite valid cells."
                            )
                        scale_value = metadata.get("scale")
                        if scale_value is None:
                            scale_value = dataset.scales[band_index - 1]
                        offset_value = metadata.get("offset")
                        if offset_value is None:
                            offset_value = dataset.offsets[band_index - 1]
                        scale = _finite_scale(scale_value, "scale", asset_key)
                        offset = _finite_scale(offset_value, "offset", asset_key)
                        scaled = raw_values * scale + offset
                        if not np.isfinite(scaled).all():
                            raise RasterAssetSamplingError(
                                f"Raster asset {asset_key!r} scale/offset produced non-finite values."
                            )
                        unit = metadata.get("unit") or dataset.units[band_index - 1]
                        unit = unit if isinstance(unit, str) and unit.strip() else None
                        ontology_variable = EARTH_VARIABLE_ONTOLOGY.resolve_variable(
                            source_name
                        )
                        declared_kind = metadata.get("measurement_kind")
                        if declared_kind not in (None, "numeric", "categorical"):
                            raise RasterAssetSamplingError(
                                f"Raster band {source_name!r} has an unsupported measurement_kind."
                            )
                        ontology_kind = (
                            "categorical"
                            if ontology_variable is not None
                            and ontology_variable.unit_dimension == "categorical"
                            else "numeric"
                            if ontology_variable is not None
                            and ontology_variable.unit_dimension is not None
                            else None
                        )
                        if (
                            declared_kind
                            and ontology_kind
                            and declared_kind != ontology_kind
                        ):
                            raise RasterAssetSamplingError(
                                f"Raster band {source_name!r} measurement kind conflicts with the Earth variable ontology."
                            )
                        query_kinds = {
                            kind
                            for name, kind in query.raster_semantics.items()
                            if _canonical_variable(name) == variable
                        }
                        if len(query_kinds) > 1:
                            raise RasterAssetSamplingError(
                                f"Raster semantic overrides conflict for {variable!r}."
                            )
                        query_kind = next(iter(query_kinds), None)
                        if query_kind and ontology_kind and query_kind != ontology_kind:
                            raise RasterAssetSamplingError(
                                f"Raster semantic override for {variable!r} conflicts with the Earth variable ontology."
                            )
                        if query_kind and declared_kind and query_kind != declared_kind:
                            raise RasterAssetSamplingError(
                                f"Raster semantic override for {variable!r} conflicts with source band metadata."
                            )
                        measurement_kind = declared_kind or ontology_kind or query_kind
                        if measurement_kind is None:
                            raise RasterAssetSamplingError(
                                f"Raster band {source_name!r} lacks declared numeric/categorical semantics."
                            )
                        is_categorical = measurement_kind == "categorical"
                        if is_categorical and (scale != 1.0 or offset != 0.0):
                            raise RasterAssetSamplingError(
                                f"Categorical band {source_name!r} declares non-identity scale/offset; "
                                "class codes will not be transformed."
                            )
                        valid_area = None
                        weighted_mean = None
                        weighted_std = None
                        valid_weights = None
                        if row_areas is not None:
                            valid_weights = np.broadcast_to(
                                row_areas[:, None], valid.shape
                            )[valid]
                            valid_area = float(np.sum(valid_weights, dtype=np.float64))
                            if not math.isfinite(valid_area) or valid_area < 0:
                                raise RasterAssetSamplingError(
                                    f"Raster asset {asset_key!r} has invalid geodesic cell areas."
                                )
                            if not is_categorical and scaled.size and valid_area > 0:
                                weighted_mean = float(
                                    np.average(scaled, weights=valid_weights)
                                )
                                weighted_std = float(
                                    np.sqrt(
                                        np.average(
                                            np.square(scaled - weighted_mean),
                                            weights=valid_weights,
                                        )
                                    )
                                )
                        category_counts = ()
                        if is_categorical and scaled.size:
                            unique_values, counts = np.unique(
                                scaled, return_counts=True
                            )
                            category_areas = (
                                np.asarray(
                                    [
                                        np.sum(
                                            valid_weights[scaled == value],
                                            dtype=np.float64,
                                        )
                                        for value in unique_values
                                    ],
                                    dtype=np.float64,
                                )
                                if valid_weights is not None
                                else None
                            )
                            category_counts = tuple(
                                {
                                    "code": value.item()
                                    if hasattr(value, "item")
                                    else value,
                                    "count": int(count),
                                    "fraction_of_valid_cells": float(
                                        count / scaled.size
                                    ),
                                    **(
                                        {
                                            "area_square_metres": float(area),
                                            "fraction_of_valid_area": float(
                                                area / valid_area
                                            ),
                                        }
                                        if category_areas is not None
                                        else {}
                                    ),
                                }
                                for value, count, area in zip(
                                    unique_values,
                                    counts,
                                    category_areas
                                    if category_areas is not None
                                    else (None for _ in unique_values),
                                    strict=True,
                                )
                            )
                        statistics.append(
                            RasterBandStatistics(
                                variable=variable,
                                source_band=source_name,
                                measurement_kind=measurement_kind,
                                unit=unit,
                                source_metadata=metadata,
                                selected_pixel_count=selected_count,
                                valid_pixel_count=int(scaled.size),
                                minimum=float(np.min(scaled))
                                if scaled.size and not is_categorical
                                else None,
                                maximum=float(np.max(scaled))
                                if scaled.size and not is_categorical
                                else None,
                                cell_weighted_mean=float(
                                    np.mean(scaled, dtype=np.float64)
                                )
                                if scaled.size and not is_categorical
                                else None,
                                population_standard_deviation=float(
                                    np.std(scaled, dtype=np.float64, ddof=0)
                                )
                                if scaled.size and not is_categorical
                                else None,
                                geodesic_area_weighted_mean=weighted_mean,
                                geodesic_area_weighted_population_standard_deviation=weighted_std,
                                valid_area_square_metres=valid_area,
                                category_value_counts=category_counts,
                            )
                        )

                    input_identity = {
                        "method_version": self.VERSION,
                        "source_observation_id": observation.observation_id,
                        "asset_key": asset_key,
                        "asset_checksum": asset.checksum,
                        "requested_variables": query.requested_variables,
                        "geometry": query.geometry,
                        "geometry_crs": query.crs,
                        "pixel_selection": query.raster_pixel_selection,
                        "weighting_method": weighting_method,
                        "semantic_overrides": query.raster_semantics,
                        "raster_transform": tuple(dataset.transform),
                        "raster_crs": str(dataset.crs),
                        "statistics": [
                            item.model_dump(mode="json") for item in statistics
                        ],
                    }
                    product_id = (
                        "raster-analysis:"
                        + hashlib.sha256(
                            json.dumps(
                                input_identity,
                                sort_keys=True,
                                separators=(",", ":"),
                                allow_nan=False,
                            ).encode()
                        ).hexdigest()
                    )
                    product_status = (
                        "no_valid_pixels"
                        if not any(item.valid_pixel_count for item in statistics)
                        else "computed_partial"
                        if missing
                        else "computed"
                    )
                    products.append(
                        RasterAnalysisProduct(
                            product_id=product_id,
                            operation="zonal_descriptive",
                            status=product_status,
                            method_version=self.VERSION,
                            source_observation_id=observation.observation_id,
                            source_dataset=observation.dataset,
                            analysis_geometry=query.geometry,
                            geometry_crs=query.crs,
                            pixel_selection=query.raster_pixel_selection,
                            weighting_method=weighting_method,
                            missing_variables=missing,
                            statistics=tuple(statistics),
                            assets=(
                                {
                                    "asset_key": asset_key,
                                    "uri": _redact_uri(asset.uri),
                                    "checksum": asset.checksum,
                                    "query_parameters_redacted": bool(
                                        urlparse(asset.uri).query
                                    ),
                                    "band_indexes": tuple(indexes),
                                },
                            ),
                            selected_pixel_count=selected_count,
                            reproducibility={
                                "software": {
                                    "python": platform.python_version(),
                                    "rasterio": rasterio.__version__,
                                    "gdal": rasterio.__gdal_version__,
                                    "numpy": np.__version__,
                                    **(
                                        {"pyproj": pyproj.__version__}
                                        if row_areas is not None
                                        else {}
                                    ),
                                },
                                "analysis_crs": str(dataset.crs),
                                "raster_transform": tuple(dataset.transform),
                                "window": tuple(window.flatten()),
                                "maximum_window_pixels": self.maximum_window_pixels,
                                "pixel_selection": query.raster_pixel_selection,
                                "weighting_method": weighting_method,
                                "semantic_overrides": query.raster_semantics,
                                "mean_weighting": "one equal weight per valid selected cell",
                                "geodesic_area_weighting": (
                                    "exact ellipsoidal longitude-latitude cell area from the CRS ellipsoid; edge pixels are not fractionally clipped"
                                    if row_areas is not None
                                    else "not requested"
                                ),
                                "standard_deviation": "population; ddof=0",
                                "nodata_policy": "exclude masked and nodata cells",
                                "scale_offset_applied": True,
                                "asset_access_query_parameters": "redacted from exported URI"
                                if urlparse(asset.uri).query
                                else "none",
                                "asset_checksum_verification": "not_performed",
                                "query_temporal_start": query.temporal_start,
                                "query_temporal_end": query.temporal_end,
                                "uncertainty_propagation": "not_performed",
                            },
                            uncertainty={
                                "status": "not_propagated",
                                "source_observation_uncertainty": observation.uncertainty,
                                "reason": "Raster statistical uncertainty propagation is not implemented.",
                            },
                            limitations=(
                                "Descriptive statistics only; no scientific inference is performed.",
                                (
                                    "Cells receive equal weight; these statistics are not area-weighted."
                                    if row_areas is None
                                    else "Area weighting uses ellipsoidal full-cell areas; boundary pixels are not fractionally clipped."
                                ),
                                "No resampling, reprojection of pixel values, or cross-scene fusion is performed.",
                                "No-data cells are excluded and reported through valid_pixel_count.",
                                "Categorical ontology variables are reported as raw code frequencies; class labels are not inferred.",
                                "Unknown variable semantics require explicit band measurement_kind or declared units before statistics are computed.",
                                *(
                                    (
                                        "Geodesic areas are calculated for full selected cells on north-up geographic grids; boundary cells are not fractionally clipped.",
                                    )
                                    if row_areas is not None
                                    else ()
                                ),
                            ),
                        )
                    )
            except RasterAssetSamplingError:
                raise
            except Exception as exc:
                raise RasterAssetSamplingError(
                    f"Could not analyze raster asset {asset_key!r}: {type(exc).__name__}."
                ) from exc

        report = tuple(products)
        status = (
            "analyzed"
            if any(product.selected_pixel_count for product in report)
            else "no_selected_pixels"
        )
        return observation.model_copy(
            update={
                "raster_analysis_products": (
                    *observation.raster_analysis_products,
                    *report,
                ),
            }
        ), status


def _resolve_bands(observation: Observation, requested: tuple[str, ...]):
    candidates = {_canonical_variable(name): [] for name in requested}
    for asset_key, asset in sorted(observation.assets.items()):
        eo_bands = asset.metadata.get("eo:bands", ())
        raster_bands = asset.metadata.get("raster:bands", ())
        if not isinstance(eo_bands, (list, tuple)):
            eo_bands = ()
        if not isinstance(raster_bands, (list, tuple)):
            raster_bands = ()
        for index in range(1, max(len(eo_bands), len(raster_bands)) + 1):
            metadata = {}
            if index <= len(eo_bands) and isinstance(eo_bands[index - 1], dict):
                metadata.update(eo_bands[index - 1])
            if index <= len(raster_bands) and isinstance(raster_bands[index - 1], dict):
                metadata.update(raster_bands[index - 1])
            names = {
                _canonical_variable(value): value
                for key in ("name", "common_name", "description")
                if isinstance((value := metadata.get(key)), str)
                and value.strip()
                and _canonical_variable(value) in candidates
            }
            if len(names) > 1:
                raise RasterAssetSamplingError(
                    f"Raster asset {asset_key!r} maps one band to conflicting requested variables."
                )
            for variable, source_name in names.items():
                candidates[variable].append((asset_key, index, source_name, metadata))
    return candidates


def _group_bands(candidates):
    grouped = {}
    for variable, matches in candidates.items():
        unique = {(item[0], item[1]): item for item in matches}
        if len(unique) > 1:
            raise RasterAssetSamplingError(
                f"Raster assets have ambiguous bands for requested variables: {[variable]}."
            )
        for item in unique.values():
            grouped.setdefault(item[0], []).append((variable, *item[1:]))
    return dict(sorted(grouped.items()))


def _finite_scale(value: Any, name: str, asset_key: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise RasterAssetSamplingError(
            f"Raster asset {asset_key!r} has invalid band {name} metadata."
        )
    return float(value)


def _redact_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme in {"http", "https"}:
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    if parsed.scheme == "file":
        return unquote(parsed.path)
    return uri


def _empty_product(
    observation, query, asset_key, checksum, count, missing, reason, *, status
):
    identity = {
        "method_version": RasterAnalysisService.VERSION,
        "source_observation_id": observation.observation_id,
        "asset_key": asset_key,
        "asset_checksum": checksum,
        "geometry": query.geometry,
        "geometry_crs": query.crs,
        "requested_variables": query.requested_variables,
        "pixel_selection": query.raster_pixel_selection,
        "weighting_method": query.raster_weighting or "equal_cell",
        "semantic_overrides": query.raster_semantics,
        "reason": reason,
    }
    product_id = (
        "raster-analysis-empty:"
        + hashlib.sha256(
            json.dumps(
                identity, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
    )
    return RasterAnalysisProduct(
        product_id=product_id,
        operation="zonal_descriptive",
        status=status,
        method_version=RasterAnalysisService.VERSION,
        source_observation_id=observation.observation_id,
        source_dataset=observation.dataset,
        analysis_geometry=query.geometry,
        geometry_crs=query.crs,
        pixel_selection=query.raster_pixel_selection,
        weighting_method=query.raster_weighting or "equal_cell",
        missing_variables=missing,
        assets=({"asset_key": asset_key, "checksum": checksum},),
        selected_pixel_count=count,
        reproducibility={"status": "not_computed", "reason": reason},
        uncertainty={
            "status": "not_propagated",
            "source_observation_uncertainty": observation.uncertainty,
            "reason": "Raster statistical uncertainty propagation is not implemented.",
        },
        limitations=(
            reason,
            *tuple(f"requested variable unavailable: {name}" for name in missing),
        ),
    )


def _empty_observation_product(observation, query, missing):
    identity = {
        "method_version": RasterAnalysisService.VERSION,
        "source_observation_id": observation.observation_id,
        "geometry": query.geometry,
        "geometry_crs": query.crs,
        "requested_variables": query.requested_variables,
        "pixel_selection": query.raster_pixel_selection,
        "weighting_method": query.raster_weighting or "equal_cell",
        "semantic_overrides": query.raster_semantics,
        "reason": "no_matching_bands",
    }
    product_id = (
        "raster-analysis-empty:"
        + hashlib.sha256(
            json.dumps(
                identity, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
    )
    return RasterAnalysisProduct(
        product_id=product_id,
        operation="zonal_descriptive",
        status="no_matching_bands",
        method_version=RasterAnalysisService.VERSION,
        source_observation_id=observation.observation_id,
        source_dataset=observation.dataset,
        analysis_geometry=query.geometry,
        geometry_crs=query.crs,
        pixel_selection=query.raster_pixel_selection,
        weighting_method=query.raster_weighting or "equal_cell",
        missing_variables=missing,
        selected_pixel_count=0,
        reproducibility={
            "status": "not_computed",
            "reason": "no requested bands were declared",
        },
        uncertainty={
            "status": "not_propagated",
            "source_observation_uncertainty": observation.uncertainty,
            "reason": "Raster statistical uncertainty propagation is not implemented.",
        },
        limitations=("No asset band metadata matched the requested variables.",),
    )


def _geodesic_row_areas(dataset, window, crs):
    """Return exact ellipsoidal areas for cells in a geographic lat/lon grid."""
    import numpy as np

    if not crs.is_geographic:
        raise RasterAssetSamplingError(
            "geodesic_cell_area weighting currently requires a geographic raster CRS."
        )
    transform = dataset.window_transform(window)
    if transform.b != 0 or transform.d != 0 or transform.a == 0 or transform.e == 0:
        raise RasterAssetSamplingError(
            "geodesic_cell_area weighting requires an unrotated geographic grid."
        )
    geod = crs.get_geod()
    flattening = geod.f
    eccentricity_squared = flattening * (2.0 - flattening)
    semi_major_axis = geod.a
    rows = int(window.height)
    areas = np.empty(rows, dtype=np.float64)
    longitude_width = abs(math.radians(transform.a))
    if longitude_width <= 0 or longitude_width > 2 * math.pi:
        raise RasterAssetSamplingError(
            "geodesic cell area requires a longitude cell width no greater than 360 degrees."
        )

    def latitude_integral(latitude_degrees: float) -> float:
        latitude = math.radians(latitude_degrees)
        sine = math.sin(latitude)
        if eccentricity_squared == 0:
            return sine
        eccentricity = math.sqrt(eccentricity_squared)
        return 0.5 * (
            sine / (1.0 - eccentricity_squared * sine * sine)
            + math.atanh(eccentricity * sine) / eccentricity
        )

    for row in range(rows):
        top = transform.f + row * transform.e
        bottom = top + transform.e
        if min(top, bottom) < -90 or max(top, bottom) > 90:
            raise RasterAssetSamplingError(
                "geodesic cell area encountered a latitude outside [-90, 90]."
            )
        latitude_integral_delta = abs(
            latitude_integral(top) - latitude_integral(bottom)
        )
        areas[row] = (
            longitude_width
            * semi_major_axis**2
            * (1.0 - eccentricity_squared)
            * latitude_integral_delta
        )
    if not np.isfinite(areas).all() or np.any(areas <= 0):
        raise RasterAssetSamplingError(
            "geodesic cell areas could not be calculated for the source grid."
        )
    return areas


def _validate_polygon_coordinates(geometry: dict[str, Any], crs: str) -> None:
    import math

    polygons = (
        (geometry["coordinates"],)
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    if not isinstance(polygons, (list, tuple)) or not polygons:
        raise ValueError(
            "raster analysis geometry must contain at least one polygon ring"
        )
    for polygon in polygons:
        if not isinstance(polygon, (list, tuple)) or not polygon:
            raise ValueError(
                "raster analysis polygon must contain at least one linear ring"
            )
        for ring in polygon:
            if not isinstance(ring, (list, tuple)) or len(ring) < 4:
                raise ValueError(
                    "raster analysis linear rings require at least four positions"
                )
            positions = []
            for position in ring:
                if not isinstance(position, (list, tuple)) or len(position) < 2:
                    raise ValueError(
                        "raster analysis positions require x and y coordinates"
                    )
                x, y = position[:2]
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in (x, y)
                ):
                    raise ValueError(
                        "raster analysis coordinates must be finite numbers"
                    )
                if crs.casefold() in {
                    "crs84",
                    "ogc:crs84",
                    "epsg:4326",
                    "urn:ogc:def:crs:ogc:1.3:crs84",
                } and not (-180 <= x <= 180 and -90 <= y <= 90):
                    raise ValueError(
                        "raster analysis coordinates must be within geographic bounds"
                    )
                positions.append((x, y))
            if positions[0] != positions[-1]:
                raise ValueError("raster analysis linear rings must be closed")
