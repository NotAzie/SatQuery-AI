"""Deterministic observation relationship graph construction."""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, TypeGuard

from .contracts import (
    Observation,
    ObservationGraph,
    ObservationRelationship,
    ObservationRelationshipType,
)
from .fusion import ObservationFusion, _can_group
from .temporal import as_utc

_SUPPORTED_RELATIONS: tuple[ObservationRelationshipType, ...] = (
    "derived_from",
    "overlaps",
    "conflicts_with",
    "supersedes",
    "corroborates",
    "spatial_neighbor",
    "temporal_neighbor",
    "same_phenomenon",
)


class ObservationGraphBuilder:
    """Builds descriptive links from declared metadata and geometric relations."""

    def __init__(
        self,
        *,
        temporal_neighbor_gap: timedelta = timedelta(0),
        spatial_neighbor_distance: float = 0,
    ) -> None:
        if temporal_neighbor_gap < timedelta(0):
            raise ValueError("temporal_neighbor_gap must not be negative")
        if spatial_neighbor_distance < 0:
            raise ValueError("spatial_neighbor_distance must not be negative")
        self.temporal_neighbor_gap = temporal_neighbor_gap
        self.spatial_neighbor_distance = spatial_neighbor_distance

    def build(self, observations: Iterable[Observation]) -> ObservationGraph:
        ordered = tuple(
            sorted(observations, key=lambda item: item.observation_id)
        )
        by_id = {item.observation_id: item for item in ordered}
        ids = set(by_id)
        edges: dict[tuple[str, str, str], ObservationRelationship] = {}

        def add(
            source: str,
            target: str,
            relation: ObservationRelationshipType,
            evidence: dict[str, object] | None = None,
        ) -> None:
            if source == target or source not in ids or target not in ids:
                return
            edge = ObservationRelationship(
                source_id=source,
                target_id=target,
                relation=relation,
                evidence=evidence or {},
            )
            edges[(source, target, relation)] = edge

        groups = ObservationFusion().group(ordered)
        for group in groups:
            for index, left in enumerate(group.observation_ids):
                for right in group.observation_ids[index + 1 :]:
                    if not _can_group(by_id[left], by_id[right]):
                        continue
                    add(left, right, "overlaps", {"group_id": group.group_id})
                    add(right, left, "overlaps", {"group_id": group.group_id})
            for conflict in group.conflicts:
                values = conflict.get("values", ())
                if not isinstance(values, (list, tuple)):
                    continue
                related_ids: list[str] = []
                for value in values:
                    if not isinstance(value, dict):
                        continue
                    observation_id = value.get("observation_id")
                    if isinstance(observation_id, str):
                        related_ids.append(observation_id)
                for index, source in enumerate(related_ids):
                    for target in related_ids[index + 1 :]:
                        evidence = {
                            "group_id": group.group_id,
                            "conflict": conflict,
                        }
                        add(source, target, "conflicts_with", evidence)
                        add(target, source, "conflicts_with", evidence)

        for index, first in enumerate(ordered):
            for second in ordered[index + 1 :]:
                shared = set(first.measured_variables).intersection(
                    second.measured_variables
                )
                for variable in sorted(shared):
                    if _same_reported_measurement(
                        first.measured_variables[variable],
                        second.measured_variables[variable],
                    ):
                        add(
                            first.observation_id,
                            second.observation_id,
                            "corroborates",
                            {"matching_reported_variable": variable},
                        )
                        add(
                            second.observation_id,
                            first.observation_id,
                            "corroborates",
                            {"matching_reported_variable": variable},
                        )

        for observation in ordered:
            declarations = observation.provenance.get("relationships", ())
            if not isinstance(declarations, (list, tuple)):
                continue
            for declaration in declarations:
                if not isinstance(declaration, dict):
                    continue
                target = declaration.get("observation_id")
                relation = declaration.get("relation")
                if (
                    isinstance(target, str)
                    and _is_supported_relation(relation)
                ):
                    try:
                        add(
                            observation.observation_id,
                            target,
                            relation,
                            {"declared_by_source": True},
                        )
                    except ValueError:
                        continue

        for index, first in enumerate(ordered):
            for second in ordered[index + 1 :]:
                first_extent = first.temporal_extent
                second_extent = second.temporal_extent
                if (
                    first_extent is not None
                    and second_extent is not None
                    and first_extent.start is not None
                    and first_extent.end is not None
                    and second_extent.start is not None
                    and second_extent.end is not None
                ):
                    a_start, a_end = as_utc(first_extent.start), as_utc(first_extent.end)
                    b_start, b_end = as_utc(second_extent.start), as_utc(second_extent.end)
                    gap = (
                        b_start - a_end
                        if a_end < b_start
                        else a_start - b_end
                        if b_end < a_start
                        else timedelta(0)
                    )
                    if timedelta(0) < gap <= self.temporal_neighbor_gap:
                        add(
                            first.observation_id,
                            second.observation_id,
                            "temporal_neighbor",
                            {"gap_seconds": gap.total_seconds()},
                        )
                        add(
                            second.observation_id,
                            first.observation_id,
                            "temporal_neighbor",
                            {"gap_seconds": gap.total_seconds()},
                        )
                if self.spatial_neighbor_distance > 0:
                    _add_spatial_neighbors(first, second, self.spatial_neighbor_distance, add)

        return ObservationGraph(
            observations=ordered,
            relationships=tuple(
                edges[key]
                for key in sorted(edges)
            ),
        )


def _add_spatial_neighbors(
    first: Observation,
    second: Observation,
    threshold: float,
    add,
) -> None:
    if first.geometry is None or second.geometry is None:
        return
    try:
        from .spatial import geometry_distance

        if first.crs != second.crs or first.crs is None:
            return
        distance = geometry_distance(first.geometry, second.geometry, crs=first.crs)
    except (ValueError, RuntimeError):
        return
    if 0 < distance <= threshold:
        evidence = {"distance": distance, "distance_unit": "crs_axis_unit"}
        add(first.observation_id, second.observation_id, "spatial_neighbor", evidence)
        add(second.observation_id, first.observation_id, "spatial_neighbor", evidence)


def _same_reported_measurement(first: object, second: object) -> bool:
    import json

    if isinstance(first, dict) and isinstance(second, dict):
        first_value, first_unit = first.get("value"), first.get("unit")
        second_value, second_unit = second.get("value"), second.get("unit")
        return first_unit == second_unit and first_value == second_value
    try:
        return json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    except (TypeError, ValueError):
        return first == second


def _is_supported_relation(value: object) -> TypeGuard[ObservationRelationshipType]:
    return isinstance(value, str) and value in _SUPPORTED_RELATIONS
