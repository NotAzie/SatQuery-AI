"""Provider-independent grouping and conflict reporting for observations."""

from __future__ import annotations

import hashlib
from importlib import import_module
import json
import math
from typing import Any, Mapping, Optional

from .contracts import Observation, ObservationGroup, TemporalExtent


class ObservationFusion:
    """Groups overlapping observations while retaining every constituent."""

    def __init__(
        self, *, provider_weights: Optional[Mapping[str, float]] = None
    ) -> None:
        self.provider_weights = dict(provider_weights or {})
        if any(not math.isfinite(value) for value in self.provider_weights.values()):
            raise ValueError("provider weights must be finite")

    def group(
        self, observations: tuple[Observation, ...]
    ) -> tuple[ObservationGroup, ...]:
        if not observations:
            return ()
        parent = list(range(len(observations)))

        def root(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        for first in range(len(observations)):
            for second in range(first + 1, len(observations)):
                if _can_group(observations[first], observations[second]):
                    left, right = root(first), root(second)
                    if left != right:
                        parent[right] = left

        clusters: dict[int, list[Observation]] = {}
        for index, observation in enumerate(observations):
            clusters.setdefault(root(index), []).append(observation)
        groups: list[ObservationGroup] = []
        for members in clusters.values():
            ordered = tuple(
                sorted(
                    members,
                    key=lambda observation: _quality_key(
                        observation, self.provider_weights
                    ),
                )
            )
            conflicts = _conflicts(ordered)
            group_id = _group_id(ordered)
            groups.append(
                ObservationGroup(
                    group_id=group_id,
                    observation_ids=tuple(
                        item.observation_id for item in ordered
                    ),
                    primary_observation_id=ordered[0].observation_id,
                    conflicts=conflicts,
                    temporal_overlap=_temporal_intersection(ordered),
                    spatial_overlap=_spatial_intersection(ordered),
                    provider_weights={
                        connector_id: weight
                        for connector_id, weight in sorted(self.provider_weights.items())
                        if any(
                            _connector_id(item) == connector_id for item in ordered
                        )
                    },
                    uncertainty_records={
                        item.observation_id: dict(item.uncertainty)
                        for item in ordered
                        if item.uncertainty
                    },
                    provenance_tree=tuple(
                        {
                            "observation_id": item.observation_id,
                            "source_id": item.source_id,
                            "dataset": (
                                item.dataset.model_dump(mode="json")
                                if item.dataset is not None
                                else None
                            ),
                            "provenance": item.provenance,
                            "reproducibility": item.reproducibility,
                        }
                        for item in ordered
                    ),
                )
            )
        return tuple(sorted(groups, key=lambda item: item.group_id))


def _can_group(first: Observation, second: Observation) -> bool:
    if first.observation_type and second.observation_type:
        if first.observation_type != second.observation_type:
            return False
    if not (
        _semantic_variables(first).intersection(_semantic_variables(second))
        or (
            first.observation_type is not None
            and first.observation_type == second.observation_type
        )
    ):
        return False
    temporal = _temporal_overlap(first.temporal_extent, second.temporal_extent)
    spatial = _spatial_overlap(first, second)
    return temporal is True or spatial is True


def _temporal_overlap(
    first: Optional[TemporalExtent], second: Optional[TemporalExtent]
) -> Optional[bool]:
    if first is None or second is None:
        return None
    if first.end is not None and second.start is not None and first.end < second.start:
        return False
    if second.end is not None and first.start is not None and second.end < first.start:
        return False
    return True


def _temporal_intersection(
    observations: tuple[Observation, ...],
) -> Optional[TemporalExtent]:
    extents = [item.temporal_extent for item in observations]
    if not extents or any(extent is None for extent in extents):
        return None
    concrete = [extent for extent in extents if extent is not None]
    starts = [item.start for item in concrete if item.start is not None]
    ends = [item.end for item in concrete if item.end is not None]
    start = max(starts) if starts else None
    end = min(ends) if ends else None
    if start is not None and end is not None and start > end:
        return None
    return TemporalExtent(start=start, end=end)


def _spatial_overlap(first: Observation, second: Observation) -> Optional[bool]:
    first_geometry = _observation_geometry(first)
    second_geometry = _observation_geometry(second)
    if first_geometry is None or second_geometry is None:
        return None
    if first_geometry == second_geometry and first.crs == second.crs:
        return True
    try:
        shapely_geometry = import_module("shapely.geometry")
        shapely_ops = import_module("shapely.ops")
        pyproj = import_module("pyproj")
    except ImportError:
        return None
    first_shape = shapely_geometry.shape(first_geometry)
    second_shape = shapely_geometry.shape(second_geometry)
    first_crs = pyproj.CRS.from_user_input(first.crs or "OGC:CRS84")
    second_crs = pyproj.CRS.from_user_input(second.crs or "OGC:CRS84")
    if first_crs != second_crs:
        transformer = pyproj.Transformer.from_crs(
            second_crs, first_crs, always_xy=True
        )
        second_shape = shapely_ops.transform(transformer.transform, second_shape)
    return bool(first_shape.intersects(second_shape))


def _observation_geometry(observation: Observation) -> Optional[dict[str, Any]]:
    if observation.geometry is not None:
        return dict(observation.geometry)
    if observation.bbox is not None:
        bounds = observation.bbox
        if len(bounds) == 4:
            minimum_x, minimum_y, maximum_x, maximum_y = bounds
        else:
            minimum_x, minimum_y, maximum_x, maximum_y = (
                bounds[0],
                bounds[1],
                bounds[3],
                bounds[4],
            )
        if minimum_x > maximum_x:
            return None
        return {
            "type": "Polygon",
            "coordinates": [[
                [minimum_x, minimum_y],
                [maximum_x, minimum_y],
                [maximum_x, maximum_y],
                [minimum_x, maximum_y],
                [minimum_x, minimum_y],
            ]],
        }
    return None


def _quality_key(
    observation: Observation,
    provider_weights: Mapping[str, float],
) -> tuple[int, float, float, float, float, float, str]:
    quality = observation.quality_assessment
    confidence = quality.confidence if quality and quality.confidence is not None else -1
    provider_score = (
        quality.provider_quality_score
        if quality and quality.provider_quality_score is not None
        else -1
    )
    completeness = (
        quality.completeness
        if quality and quality.completeness is not None
        else -1
    )
    validation = (
        1
        if quality is None or quality.validation_status == "not_assessed"
        else 0
        if quality.validation_status == "valid"
        else 2
    )
    age = (
        quality.freshness_seconds
        if quality and quality.freshness_seconds is not None
        else float("inf")
    )
    provider_weight = provider_weights.get(_connector_id(observation), 0.0)
    return (
        validation,
        -provider_weight,
        -confidence,
        -provider_score,
        -completeness,
        age,
        observation.observation_id,
    )


def _connector_id(observation: Observation) -> str:
    satquery = observation.provenance.get("satquery")
    if isinstance(satquery, dict):
        record = satquery.get("earth_perception")
        if isinstance(record, dict):
            connector_id = record.get("connector_id")
            if isinstance(connector_id, str):
                return connector_id
    return ""


def _spatial_intersection(
    observations: tuple[Observation, ...],
) -> Optional[dict[str, Any]]:
    geometries: list[dict[str, Any]] = []
    for observation in observations:
        geometry = _observation_geometry(observation)
        if geometry is None:
            return None
        geometries.append(geometry)
    if not geometries:
        return None
    if all(
        geometry == geometries[0]
        and item.crs == observations[0].crs
        for item, geometry in zip(observations, geometries)
    ):
        return geometries[0]
    try:
        shapely_geometry = import_module("shapely.geometry")
        shapely_ops = import_module("shapely.ops")
        pyproj = import_module("pyproj")
    except ImportError:
        return None
    first_crs = pyproj.CRS.from_user_input(observations[0].crs or "OGC:CRS84")
    intersection = shapely_geometry.shape(geometries[0])
    for observation, geometry in zip(observations[1:], geometries[1:]):
        current = shapely_geometry.shape(geometry)
        current_crs = pyproj.CRS.from_user_input(
            observation.crs or "OGC:CRS84"
        )
        if current_crs != first_crs:
            transformer = pyproj.Transformer.from_crs(
                current_crs, first_crs, always_xy=True
            )
            current = shapely_ops.transform(transformer.transform, current)
        intersection = intersection.intersection(current)
        if intersection.is_empty:
            return None
    return dict(shapely_geometry.mapping(intersection))


def _conflicts(
    observations: tuple[Observation, ...],
) -> tuple[dict[str, Any], ...]:
    conflicts = []
    for index, first in enumerate(observations):
        for second in observations[index + 1 :]:
            if (
                _temporal_overlap(first.temporal_extent, second.temporal_extent)
                is False
                or _spatial_overlap(first, second) is False
            ):
                continue
            first_measurements = _measurement_index(first)
            second_measurements = _measurement_index(second)
            for key in sorted(set(first_measurements).intersection(second_measurements)):
                variable = key.partition(":")[2]
                for first_value, first_unit, first_source in first_measurements[key]:
                    for second_value, second_unit, second_source in second_measurements[key]:
                        if first_unit == second_unit and _same_value(first_value, second_value):
                            continue
                        conflicts.append(
                            {
                                "type": (
                                    "incomparable_measurement_units"
                                    if first_unit != second_unit
                                    else "measurement_disagreement"
                                ),
                                "variable": variable,
                                "values": (
                                    {
                                        "observation_id": first.observation_id,
                                        "source_variable": first_source,
                                        "value": first_value,
                                        "unit": first_unit,
                                    },
                                    {
                                        "observation_id": second.observation_id,
                                        "source_variable": second_source,
                                        "value": second_value,
                                        "unit": second_unit,
                                    },
                                ),
                            }
                        )
    return tuple(conflicts)


def _same_value(first: Any, second: Any) -> bool:
    try:
        return json.dumps(first, sort_keys=True, default=str) == json.dumps(
            second, sort_keys=True, default=str
        )
    except (TypeError, ValueError):
        return first == second


def _measurement_value(measurement: Any) -> tuple[Any, Optional[str]]:
    if isinstance(measurement, dict) and "value" in measurement:
        unit = measurement.get("unit")
        return measurement["value"], unit if isinstance(unit, str) else None
    return measurement, None


def _semantic_variables(observation: Observation) -> set[str]:
    variables = {f"source:{name}" for name in observation.measured_variables}
    variables.update(
        f"canonical:{item.canonical_variable}"
        for item in observation.canonical_measurements
        if item.semantic_status == "resolved"
    )
    return variables


def _measurement_index(
    observation: Observation,
) -> dict[str, list[tuple[Any, Optional[str], str]]]:
    resolved_sources = {
        item.source_variable
        for item in observation.canonical_measurements
        if item.semantic_status == "resolved"
    }
    values: dict[str, list[tuple[Any, Optional[str], str]]] = {
        f"source:{name}": [(*_measurement_value(measurement), name)]
        for name, measurement in observation.measured_variables.items()
        if name not in resolved_sources
    }
    for measurement in observation.canonical_measurements:
        if measurement.semantic_status == "resolved":
            values.setdefault(
                f"canonical:{measurement.canonical_variable}", []
            ).append((
                measurement.value,
                measurement.unit,
                measurement.source_variable,
            ))
    return values


def _group_id(observations: tuple[Observation, ...]) -> str:
    identity = "\n".join(sorted(item.observation_id for item in observations))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
