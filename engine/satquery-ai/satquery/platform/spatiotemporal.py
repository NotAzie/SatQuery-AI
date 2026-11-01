"""Conservative spatial-temporal organization of canonical observations."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any

from .contracts import (
    Observation,
    ObservationAlignmentIssue,
    ObservationStack,
    ObservationStackBuild,
    ObservationStackMember,
    TemporalDifferenceDiagnostic,
    TemporalDifferenceIssue,
)


class ExactSupportObservationStackBuilder:
    """Build time series where the spatial support is explicitly identical.

    Supported profiles are point-sampled raster pixels and direct point
    observations. The builder does not reproject geometries, convert units,
    interpolate time, or calculate trends. Unresolved variables can only be
    grouped within the same declared dataset and source-variable name.
    """

    VERSION = "1.1.0"

    def build(self, observations: tuple[Observation, ...]) -> ObservationStackBuild:
        records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        issues: list[ObservationAlignmentIssue] = []
        eligible_observations = tuple(
            item
            for item in observations
            if item.provenance.get("satquery:asset_sampling") is not None
            or _has_point_support(item)
        )
        for observation in eligible_observations:
            has_raster_sampling_request = (
                observation.provenance.get("satquery:asset_sampling") is not None
            )
            measurements = tuple(
                measurement
                for measurement in observation.canonical_measurements
                if (
                    measurement.source_metadata.get("sampling") == "pixel_containing_point"
                    if has_raster_sampling_request
                    else True
                )
            )
            if not measurements:
                request = observation.provenance.get("satquery:asset_sampling", {})
                requested_variables = request.get("requested_variables", ())
                if isinstance(requested_variables, (list, tuple)):
                    issues.extend(
                        ObservationAlignmentIssue(
                            observation_id=observation.observation_id,
                            code="missing_measurement",
                            message=(
                                f"No canonical raster sample was produced for requested "
                                f"variable {variable!r}."
                            ),
                        )
                        for variable in requested_variables
                        if isinstance(variable, str) and variable.strip()
                    )
                continue
            for measurement in measurements:
                is_raster_sample = (
                    measurement.source_metadata.get("sampling")
                    == "pixel_containing_point"
                )
                issue = None
                if (
                    observation.observed_at is None
                    or observation.observed_at.tzinfo is None
                ):
                    issue = self._issue(observation, measurement, "missing_time",
                                        "A source acquisition time is required for a temporal stack.")
                elif measurement.semantic_status == "resolved":
                    variable_key = f"canonical:{measurement.canonical_variable}"
                elif observation.dataset is not None:
                    variable_key = "source:{}:{}:{}".format(
                        observation.dataset.connector_id,
                        observation.dataset.dataset_id,
                        measurement.source_variable.casefold(),
                    )
                else:
                    issue = self._issue(
                        observation,
                        measurement,
                        "unresolved_variable",
                        "An unresolved variable requires a declared dataset scope before it can be stacked.",
                    )

                value = measurement.value
                if issue is None and value is None:
                    issue = self._issue(
                        observation,
                        measurement,
                        "missing_measurement",
                        "The source reported no numeric value for this measurement.",
                    )
                if issue is None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or (isinstance(value, float) and not math.isfinite(value))
                ):
                    issue = self._issue(
                        observation,
                        measurement,
                        "non_numeric_value",
                        "The measurement is not a finite numeric value.",
                    )
                if issue is None and not (measurement.unit or "").strip():
                    issue = self._issue(
                        observation,
                        measurement,
                        "missing_unit",
                        "A declared unit is required for a comparable measurement stack.",
                    )
                support = measurement.source_metadata
                alignment = "exact_pixel_support" if is_raster_sample else "exact_point_support"
                geometry_key, crs_key = (
                    ("pixel_support_geometry", "pixel_support_crs")
                    if is_raster_sample
                    else ("observation_support_geometry", "observation_support_crs")
                )
                geometry = support.get(geometry_key)
                crs = support.get(crs_key)
                if not is_raster_sample:
                    geometry = observation.geometry
                    crs = observation.crs
                if issue is None and (
                    not isinstance(geometry, dict)
                    or not isinstance(crs, str)
                    or not crs.strip()
                ):
                    issue = self._issue(
                        observation,
                        measurement,
                        "unknown_spatial_support",
                        "The measurement does not declare its exact spatial support geometry and CRS.",
                    )
                if issue is not None:
                    issues.append(issue)
                    continue

                support_key = _fingerprint(
                    {"alignment": alignment, "geometry": geometry, "crs": crs}
                )
                records[variable_key].append(
                    {
                        "observation": observation,
                        "measurement": measurement,
                        "variable_key": variable_key,
                        "canonical_variable": (
                            measurement.canonical_variable
                            if measurement.semantic_status == "resolved"
                            else None
                        ),
                        "unit": measurement.unit,
                        "support_key": support_key,
                        "support_geometry": geometry,
                        "support_crs": crs,
                        "spatial_alignment": alignment,
                    }
                )

        stacks: list[ObservationStack] = []
        for variable_key, values in sorted(records.items()):
            if len(values) < 2:
                if len(eligible_observations) > 1:
                    value = values[0]
                    issues.append(
                        self._issue(
                            value["observation"],
                            value["measurement"],
                            "insufficient_members",
                            "Only one compatible measurement is available for this variable.",
                        )
                    )
                continue
            units = {value["unit"] for value in values}
            if len(units) != 1:
                issues.extend(
                    self._issue(
                        value["observation"],
                        value["measurement"],
                        "unit_mismatch",
                        "Source units differ; no unit conversion is performed by this stack builder.",
                    )
                    for value in values
                )
                continue

            support_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for value in values:
                support_groups[value["support_key"]].append(value)
            for support_values in support_groups.values():
                if len(support_values) < 2:
                    value = support_values[0]
                    issues.append(
                        self._issue(
                            value["observation"],
                            value["measurement"],
                            "support_not_shared",
                            "No second observation has this exact spatial geometry and CRS.",
                        )
                    )
                    continue
                ordered = sorted(
                    support_values,
                    key=lambda value: (
                        value["observation"].observed_at,
                        value["observation"].observation_id,
                    ),
                )
                times = [value["observation"].observed_at for value in ordered]
                if len(times) != len(set(times)):
                    issues.extend(
                        self._issue(
                            value["observation"],
                            value["measurement"],
                            "duplicate_time",
                            "Multiple observations at the same timestamp are not collapsed into one temporal sample.",
                        )
                        for value in ordered
                    )
                    continue
                members = tuple(
                    ObservationStackMember(
                        observation_id=value["observation"].observation_id,
                        measurement_observation_id=value["measurement"].observation_id,
                        source_id=value["observation"].source_id,
                        dataset=value["observation"].dataset,
                        observed_at=value["observation"].observed_at,
                        value=value["measurement"].value,
                        unit=value["measurement"].unit,
                        source_variable=value["measurement"].source_variable,
                        uncertainty=dict(value["observation"].uncertainty),
                        source_measurement_metadata={
                            **dict(value["measurement"].source_metadata),
                            (
                                "pixel_support_geometry"
                                if value["spatial_alignment"] == "exact_pixel_support"
                                else "observation_support_geometry"
                            ): value["support_geometry"],
                            (
                                "pixel_support_crs"
                                if value["spatial_alignment"] == "exact_pixel_support"
                                else "observation_support_crs"
                            ): value["support_crs"],
                        },
                        provenance=dict(value["observation"].provenance),
                    )
                    for value in ordered
                )
                support_geometry = ordered[0]["support_geometry"]
                support_crs = ordered[0]["support_crs"]
                stack_identity = {
                    "variable_key": variable_key,
                    "unit": next(iter(units)),
                    "support_geometry": support_geometry,
                    "support_crs": support_crs,
                    "spatial_alignment": ordered[0]["spatial_alignment"],
                    "members": [
                        {
                            "observation_id": member.observation_id,
                            "observed_at": member.observed_at.isoformat(),
                            "value": member.value,
                        }
                        for member in members
                    ],
                    "builder_version": self.VERSION,
                }
                stack_id = "obs-stack:" + _fingerprint(stack_identity)
                stacks.append(
                    ObservationStack(
                        stack_id=stack_id,
                        variable_key=variable_key,
                        canonical_variable=ordered[0]["canonical_variable"],
                        unit=next(iter(units)),
                        spatial_support_geometry=support_geometry,
                        spatial_support_crs=support_crs,
                        spatial_alignment=ordered[0]["spatial_alignment"],
                        temporal_alignment="source_acquisition_time",
                        members=members,
                        reproducibility={
                            "builder": type(self).__name__,
                            "builder_version": self.VERSION,
                            "input_observation_ids": tuple(
                                member.observation_id for member in members
                            ),
                            "unit_policy": "exact_match_no_conversion",
                            "spatial_policy": (
                                "exact_geometry_and_crs_no_resampling_or_reprojection"
                            ),
                            "temporal_policy": "source_acquisition_time_no_interpolation",
                            "uncertainty_policy": "source_uncertainty_copied_per_member_no_aggregation",
                        },
                    )
                )

        return ObservationStackBuild(
            stacks=tuple(sorted(stacks, key=lambda value: value.stack_id)),
            issues=tuple(
                sorted(
                    issues,
                    key=lambda item: (
                        item.observation_id,
                        item.canonical_variable or "",
                        item.code,
                    ),
                )
            ),
            builder_version=self.VERSION,
        )

    @staticmethod
    def _issue(
        observation: Observation,
        measurement: Any,
        code: str,
        message: str,
    ) -> ObservationAlignmentIssue:
        return ObservationAlignmentIssue(
            observation_id=observation.observation_id,
            canonical_variable=(
                measurement.canonical_variable
                if measurement.semantic_status == "resolved"
                else None
            ),
            code=code,
            message=message,
        )


class ConsecutiveTemporalDifferenceEngine:
    """Describe adjacent sample differences without performing inference.

    Inputs must already be grouped by :class:`ExactSupportObservationStackBuilder`,
    which guarantees exact spatial support and exact declared-unit equality.
    The engine does not calculate rates, trends, significance, uncertainty, or
    physical interpretation. Every output retains both complete source members.
    """

    METHOD_ID = "satquery.temporal.consecutive-difference"
    VERSION = "1.0.0"

    def build(
        self, stacks: tuple[ObservationStack, ...]
    ) -> tuple[tuple[TemporalDifferenceDiagnostic, ...], tuple[TemporalDifferenceIssue, ...]]:
        diagnostics: list[TemporalDifferenceDiagnostic] = []
        issues: list[TemporalDifferenceIssue] = []
        for stack in sorted(stacks, key=lambda item: item.stack_id):
            for earlier, later in zip(stack.members, stack.members[1:]):
                if earlier.dataset is None or later.dataset is None:
                    issues.append(TemporalDifferenceIssue(
                        stack_id=stack.stack_id,
                        earlier_observation_id=earlier.observation_id,
                        later_observation_id=later.observation_id,
                        code="source_dataset_unknown",
                        message=(
                            "A same-dataset comparison cannot be established because "
                            "at least one source member has no dataset identity."
                        ),
                    ))
                    continue
                if earlier.dataset != later.dataset:
                    issues.append(TemporalDifferenceIssue(
                        stack_id=stack.stack_id,
                        earlier_observation_id=earlier.observation_id,
                        later_observation_id=later.observation_id,
                        code="dataset_mismatch",
                        message=(
                            "Cross-dataset differences require an independently validated "
                            "compatibility method; the source values remain available in the stack."
                        ),
                    ))
                    continue
                if earlier.source_variable != later.source_variable:
                    issues.append(TemporalDifferenceIssue(
                        stack_id=stack.stack_id,
                        earlier_observation_id=earlier.observation_id,
                        later_observation_id=later.observation_id,
                        code="source_variable_mismatch",
                        message=(
                            "Different source variable names require an explicit validated "
                            "mapping before a difference can be reported."
                        ),
                    ))
                    continue
                difference = later.value - earlier.value
                if isinstance(difference, float) and not math.isfinite(difference):
                    issues.append(
                        TemporalDifferenceIssue(
                            stack_id=stack.stack_id,
                            earlier_observation_id=earlier.observation_id,
                            later_observation_id=later.observation_id,
                            code="non_finite_difference",
                            message=(
                                "The finite source measurements overflowed during subtraction; "
                                "no difference diagnostic was produced."
                            ),
                        )
                    )
                    continue
                diagnostic_identity = {
                    "method_id": self.METHOD_ID,
                    "method_version": self.VERSION,
                    "stack_id": stack.stack_id,
                    "earlier_observation_id": earlier.observation_id,
                    "later_observation_id": later.observation_id,
                    "earlier_value": earlier.value,
                    "later_value": later.value,
                    "spatial_alignment": stack.spatial_alignment,
                }
                diagnostics.append(
                    TemporalDifferenceDiagnostic(
                        diagnostic_id="temporal-difference:" + _fingerprint(diagnostic_identity),
                        stack_id=stack.stack_id,
                        variable_key=stack.variable_key,
                        canonical_variable=stack.canonical_variable,
                        unit=stack.unit,
                        spatial_support_geometry=stack.spatial_support_geometry,
                        spatial_support_crs=stack.spatial_support_crs,
                        spatial_alignment=stack.spatial_alignment,
                        earlier=earlier,
                        later=later,
                        elapsed_seconds=(later.observed_at - earlier.observed_at).total_seconds(),
                        difference_value=difference,
                        method_id=self.METHOD_ID,
                        method_version=self.VERSION,
                        reproducibility={
                            **diagnostic_identity,
                            "operation": "later.value - earlier.value",
                            "input_observation_ids": (
                                earlier.observation_id,
                                later.observation_id,
                            ),
                            "spatial_support_policy": (
                                f"inherited_{stack.spatial_alignment}_stack"
                            ),
                            "unit_policy": "exact_declared_unit_match_no_conversion",
                            "temporal_policy": "consecutive_source_acquisition_times_no_interpolation",
                            "uncertainty_policy": "source_uncertainty_preserved_per_member_not_propagated",
                            "scientific_interpretation": "descriptive_only_no_trend_or_causal_inference",
                        },
                    )
                )
        return (
            tuple(sorted(diagnostics, key=lambda item: (
                item.earlier.observed_at,
                item.later.observed_at,
                item.stack_id,
                item.diagnostic_id,
            ))),
            tuple(sorted(issues, key=lambda item: (
                item.stack_id, item.earlier_observation_id, item.later_observation_id
            ))),
        )


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _has_point_support(observation: Observation) -> bool:
    geometry = observation.geometry
    return (
        isinstance(geometry, dict)
        and geometry.get("type") == "Point"
        and isinstance(geometry.get("coordinates"), (tuple, list))
        and len(geometry["coordinates"]) == 2
        and isinstance(observation.crs, str)
        and bool(observation.crs.strip())
    )
