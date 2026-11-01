"""Provider-neutral sampling of explicitly requested raster asset values."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any
from urllib.parse import unquote, urlparse

from .contracts import CanonicalMeasurement, EarthQuery, Observation
from .modalities import EARTH_SENSING_MODALITIES, infer_modalities
from .normalization import SemanticNormalizer
from .ontology import EARTH_VARIABLE_ONTOLOGY


class RasterAssetSamplingError(ValueError):
    """A requested point sample could not be read without guessing."""


class RasterAssetSamplingService:
    """Read point measurements from assets whose band metadata names variables.

    This service does not derive indices, convert units, or estimate uncertainty.
    It reads the pixel containing a query point and applies only explicit raster
    scale/offset metadata. Rasterio is loaded lazily as an optional dependency.
    """

    VERSION = "1.0.0"

    def __init__(self, *, allow_local_files: bool = False) -> None:
        self.allow_local_files = allow_local_files

    def sample(self, observation: Observation, query: EarthQuery) -> tuple[Observation, str]:
        if query.asset_sampling != "point":
            raise ValueError("Raster asset sampling was not requested")
        x, y = _query_point(query)
        requested = _canonical_requested_variables(query.requested_variables)
        candidates: dict[str, list[tuple[str, int, str, dict[str, Any]]]] = {
            name: [] for name in requested
        }
        for asset_key, asset in sorted(observation.assets.items()):
            eo_bands = asset.metadata.get("eo:bands", ())
            raster_bands = asset.metadata.get("raster:bands", ())
            if not isinstance(eo_bands, (list, tuple)):
                eo_bands = ()
            if not isinstance(raster_bands, (list, tuple)):
                raster_bands = ()
            for index in range(1, max(len(eo_bands), len(raster_bands)) + 1):
                band = {}
                if index <= len(eo_bands) and isinstance(eo_bands[index - 1], dict):
                    band.update(eo_bands[index - 1])
                if index <= len(raster_bands) and isinstance(raster_bands[index - 1], dict):
                    band.update(raster_bands[index - 1])
                matching_names = {
                    _canonical_variable(value): value
                    for field in ("name", "common_name", "description")
                    if isinstance((value := band.get(field)), str)
                    and value.strip()
                    and _canonical_variable(value) in candidates
                }
                if len(matching_names) > 1:
                    raise RasterAssetSamplingError(
                        f"Raster asset {asset_key!r} maps one band to conflicting requested variables."
                    )
                for canonical, source_name in matching_names.items():
                    candidates[canonical].append(
                        (asset_key, index, source_name, band)
                    )

        for name, matches in candidates.items():
            unique_matches = {}
            for asset_key, index, source_name, band in matches:
                unique_matches[(asset_key, index, source_name)] = (
                    asset_key, index, source_name, band
                )
            candidates[name] = list(unique_matches.values())
        missing = tuple(name for name, matches in candidates.items() if not matches)
        ambiguous = {
            name: matches for name, matches in candidates.items() if len(matches) > 1
        }
        if ambiguous:
            names = sorted(ambiguous)
            raise RasterAssetSamplingError(
                f"Raster assets have ambiguous bands for requested variables: {names}."
            )
        if all(not matches for matches in candidates.values()):
            return _with_sampling_status(
                observation,
                {"status": "no_matching_bands", "requested_variables": requested},
            ), "no_matching_bands"

        try:
            import rasterio
            from rasterio.windows import Window
        except ImportError as exc:
            raise RasterAssetSamplingError(
                "Point sampling raster assets requires the optional 'raster' dependencies."
            ) from exc

        by_asset: dict[str, list[tuple[str, int, str, dict[str, Any]]]] = {}
        for canonical, matches in candidates.items():
            for match in matches:
                by_asset.setdefault(match[0], []).append((canonical, *match[1:]))

        measurements: dict[str, Any] = dict(observation.measured_variables)
        existing_measurement_names = {
            item.canonical_variable for item in observation.canonical_measurements
        }
        canonical_records = list(observation.canonical_measurements)
        sample_records: list[dict[str, Any]] = []
        for asset_key, matches in sorted(by_asset.items()):
            asset = observation.assets[asset_key]
            uri = _raster_uri(asset.uri, allow_local_files=self.allow_local_files)
            try:
                with rasterio.open(uri) as dataset:
                    if dataset.crs is None:
                        raise RasterAssetSamplingError(
                            f"Raster asset {asset_key!r} has no declared CRS."
                        )
                    from rasterio.warp import transform

                    source_crs = query.crs
                    coordinates = (x, y)
                    if str(dataset.crs) != source_crs:
                        transformed_x, transformed_y = transform(
                            source_crs, dataset.crs, [x], [y]
                        )
                        coordinates = (transformed_x[0], transformed_y[0])
                    row, column = dataset.index(*coordinates)
                    if row < 0 or column < 0 or row >= dataset.height or column >= dataset.width:
                        for canonical, _index, source_name, _band in matches:
                            sample_records.append({
                                "variable": canonical, "source_name": source_name,
                                "asset": asset_key, "status": "outside_asset_extent",
                            })
                        continue
                    unique_indexes = sorted({band_index for _, band_index, _, _ in matches})
                    pixels = dataset.read(
                        unique_indexes,
                        window=Window(column, row, 1, 1),
                        masked=True,
                    )
                    index_offset = {band_index: offset for offset, band_index in enumerate(unique_indexes)}
                    for canonical, band_index, source_name, band_metadata in matches:
                        pixel = pixels[index_offset[band_index], 0, 0]
                        import numpy as np

                        if np.ma.is_masked(pixel):
                            sample_records.append({
                                "variable": canonical, "source_name": source_name,
                                "asset": asset_key, "band_index": band_index,
                                "status": "nodata",
                            })
                            continue
                        raw_value = pixel.item() if hasattr(pixel, "item") else pixel
                        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or not math.isfinite(raw_value):
                            raise RasterAssetSamplingError(
                                f"Raster asset {asset_key!r} returned a non-finite or non-numeric pixel."
                            )
                        scale_value = band_metadata.get("scale")
                        if scale_value is None:
                            scale_value = dataset.scales[band_index - 1]
                        offset_value = band_metadata.get("offset")
                        if offset_value is None:
                            offset_value = dataset.offsets[band_index - 1]
                        scale = _finite_metadata_number(
                            scale_value,
                            "scale", asset_key,
                        )
                        offset = _finite_metadata_number(
                            offset_value,
                            "offset", asset_key,
                        )
                        value = raw_value * scale + offset
                        unit = band_metadata.get("unit") or dataset.units[band_index - 1]
                        unit = unit if isinstance(unit, str) and unit.strip() else None
                        pixel_geometry = _pixel_footprint(
                            dataset, row, column, query.crs
                        )
                        metadata = {
                            "sampling": "pixel_containing_point",
                            "asset_key": asset_key,
                            "asset_checksum": asset.checksum,
                            "band_index": band_index,
                            "band_metadata": band_metadata,
                            "raw_value": raw_value,
                            "scale": scale,
                            "offset": offset,
                            "pixel_row": row,
                            "pixel_column": column,
                            "pixel_support_geometry": pixel_geometry,
                            "pixel_support_crs": query.crs,
                            "raster_crs": str(dataset.crs),
                            "raster_transform": tuple(dataset.transform),
                            "source_query_point": (x, y),
                            "source_query_crs": source_crs,
                        }
                        normalized = SemanticNormalizer().normalize_measurement(
                            source_name, value, unit=unit, metadata=metadata
                        )
                        normalized_name, measurement = next(iter(normalized.items()))
                        if normalized_name in measurements or normalized_name in existing_measurement_names:
                            raise RasterAssetSamplingError(
                                f"Raster measurement {normalized_name!r} would overwrite an existing observation value."
                            )
                        measurements[normalized_name] = measurement
                        variable = EARTH_VARIABLE_ONTOLOGY.resolve_variable(source_name)
                        canonical_records.append(CanonicalMeasurement(
                            canonical_variable=normalized_name,
                            value=value,
                            unit=unit,
                            source_variable=source_name,
                            source_unit=unit,
                            ontology_uri=(
                                variable.ontology_uri or f"urn:satquery:earth-variable:{variable.canonical_name}"
                                if variable is not None else None
                            ),
                            semantic_status="resolved" if variable is not None else "unresolved",
                            source_metadata=metadata,
                            observation_id=observation.observation_id,
                        ))
                        sample_records.append({
                            "variable": normalized_name, "source_name": source_name,
                            "asset": asset_key, "band_index": band_index,
                            "value": value, "unit": unit, "status": "sampled",
                            "asset_checksum": asset.checksum,
                            "scale": scale, "offset": offset,
                            "pixel_row": row, "pixel_column": column,
                            "pixel_support_geometry": pixel_geometry,
                            "pixel_support_crs": query.crs,
                            "raster_crs": str(dataset.crs),
                        })
            except RasterAssetSamplingError:
                raise
            except Exception as exc:
                raise RasterAssetSamplingError(
                    f"Could not sample raster asset {asset_key!r}: {type(exc).__name__}."
                ) from exc

        status = "sampled" if any(item["status"] == "sampled" for item in sample_records) else "no_valid_pixels"
        report = {
            "status": status,
            "requested_variables": requested,
            "missing_variables": missing,
            "samples": tuple(sample_records),
            "uncertainty": "not provided by the source asset",
        }
        provenance = dict(observation.provenance)
        provenance["satquery:asset_sampling"] = report
        reproducibility = dict(observation.reproducibility)
        reproducibility["satquery:asset_sampling"] = {
            "method": "raster_pixel_containing_point",
            "sampler_version": self.VERSION,
            "software": "rasterio/GDAL runtime",
            "query": {"point": (x, y), "crs": query.crs},
            "samples": tuple(sample_records),
        }
        if status != "sampled":
            return _with_sampling_status(observation, report), status

        identity = {
            "parent_observation_id": observation.observation_id,
            "point": (x, y),
            "crs": query.crs,
            "requested_variables": requested,
            "samples": [item for item in sample_records if item["status"] == "sampled"],
        }
        sample_digest = hashlib.sha256(json.dumps(
            identity, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
        sample_observation_id = f"raster-sample:{sample_digest}"
        canonical_records = [
            item.model_copy(update={"observation_id": sample_observation_id})
            if item.source_metadata.get("sampling") == "pixel_containing_point"
            else item
            for item in canonical_records
        ]

        provenance["satquery:asset_sampling"]["parent_observation_id"] = observation.observation_id
        provenance["satquery:asset_sampling"]["source_spatial_support"] = {
            "geometry": observation.geometry,
            "bbox": observation.bbox,
            "crs": observation.crs,
            "provider_confidence": observation.confidence,
            "provider_uncertainty": observation.uncertainty,
            "provider_quality": observation.quality,
        }
        reproducibility["satquery:asset_sampling"]["asset_content_verification"] = (
            "checksum_available"
            if all(
                observation.assets[item["asset"]].checksum
                for item in sample_records if item["status"] == "sampled"
            )
            else "checksum_not_available"
        )
        enriched = observation.model_copy(update={
            "observation_id": sample_observation_id,
            "geometry": {"type": "Point", "coordinates": (x, y)},
            "bbox": None,
            "crs": query.crs,
            "observation_type": "raster_pixel_sample",
            "modalities": tuple(sorted(
                set(EARTH_SENSING_MODALITIES.canonicalize((
                    *observation.modalities,
                    *(
                        observation.dataset.metadata.get("modalities", ())
                        if observation.dataset is not None else ()
                    ),
                    *infer_modalities(query.requested_variables),
                )))
            )),
            "measured_variables": measurements,
            "canonical_measurements": tuple(canonical_records),
            "provenance": provenance,
            "reproducibility": reproducibility,
            "confidence": None,
            "uncertainty": {},
            "quality": {},
            "quality_assessment": None,
        })
        return enriched, status


def _query_point(query: EarthQuery) -> tuple[float, float]:
    if query.point is not None:
        return query.point
    if query.geometry is not None and query.geometry.get("type") == "Point":
        coordinates = query.geometry.get("coordinates", ())
        return float(coordinates[0]), float(coordinates[1])
    raise ValueError("point raster sampling requires a point geometry")


def _canonical_requested_variables(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({_canonical_variable(value) for value in values}))


def _canonical_variable(value: str) -> str:
    variable = EARTH_VARIABLE_ONTOLOGY.resolve_variable(value)
    return variable.canonical_name if variable is not None else value.strip().casefold().replace("-", "_").replace(" ", "_")


def _raster_uri(uri: str, *, allow_local_files: bool) -> str:
    parsed = urlparse(uri)
    if parsed.scheme == "https":
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise RasterAssetSamplingError(
                "Raster asset URL must have a host and no embedded credentials or fragment."
            )
        return f"/vsicurl/{uri}"
    if allow_local_files and parsed.scheme == "file":
        path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        return path
    if allow_local_files and re.match(r"^[A-Za-z]:[\\/]", uri):
        return uri
    if allow_local_files and not parsed.scheme:
        return uri
    raise RasterAssetSamplingError(
        "Raster sampling accepts HTTPS assets; local files require explicit local mode."
    )


def _finite_metadata_number(value: Any, name: str, asset_key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RasterAssetSamplingError(
            f"Raster asset {asset_key!r} has invalid band {name} metadata."
        )
    return float(value)


def _pixel_footprint(dataset, row: int, column: int, target_crs: str) -> dict[str, Any]:
    corners = (
        dataset.transform @ (column, row),
        dataset.transform @ (column + 1, row),
        dataset.transform @ (column + 1, row + 1),
        dataset.transform @ (column, row + 1),
        dataset.transform @ (column, row),
    )
    if str(dataset.crs) != target_crs:
        from rasterio.warp import transform

        longitudes, latitudes = transform(
            dataset.crs,
            target_crs,
            [point[0] for point in corners],
            [point[1] for point in corners],
        )
        corners = tuple(zip(longitudes, latitudes))
    return {
        "type": "Polygon",
        "coordinates": [[tuple(float(value) for value in point) for point in corners]],
    }


def _with_sampling_status(observation: Observation, report: dict[str, Any]) -> Observation:
    provenance = dict(observation.provenance)
    provenance["satquery:asset_sampling"] = report
    return observation.model_copy(update={"provenance": provenance})
