"""Evidence sufficiency and deterministic acquisition refinement for methods."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Literal

from .capabilities import EarthCapabilityMatrix
from .contracts import Contract, EarthQuery, Observation
from .scientific_library import ScientificMethodKnowledge


class SufficiencyCheck(Contract):
    criterion: str
    status: Literal["satisfied", "unsatisfied", "unknown"]
    evidence_ids: tuple[str, ...] = ()
    explanation: str


class MethodEvidenceSufficiency(Contract):
    method_id: str
    method_version: str
    status: Literal["sufficient", "insufficient", "indeterminate"]
    executable: bool
    checks: tuple[SufficiencyCheck, ...]
    missing_observations: tuple[str, ...] = ()
    capability_matrix_revision: str
    benchmark_suite_status: Literal["applicable", "not_applicable", "unknown"]
    explanation: str


class EvidenceSufficiencyEngine:
    """Only declares sufficiency when every required precondition is verified."""

    def assess(
        self,
        method: ScientificMethodKnowledge,
        observations: Iterable[Observation],
        query: EarthQuery,
        matrix: EarthCapabilityMatrix,
        *,
        benchmark_suite_status: Literal["applicable", "not_applicable", "unknown"] = "unknown",
        executable_method_ids: Iterable[tuple[str, str]] = (),
        certified_method_ids: Iterable[tuple[str, str]] = (),
    ) -> MethodEvidenceSufficiency:
        items = tuple(sorted(observations, key=lambda item: item.observation_id))
        executable_keys = set(executable_method_ids)
        certified_keys = set(certified_method_ids)
        executable = (
            method.implementation_status == "executable_certified"
            and (method.executable_method_id, method.executable_method_version) in executable_keys
            and (method.executable_method_id, method.executable_method_version) in certified_keys
        )
        checks: list[SufficiencyCheck] = []
        missing: list[str] = []

        for requirement in method.required_measurements:
            matches = []
            unknown = []
            incompatible = []
            for observation in items:
                candidates: list[tuple[object, str | None, bool]] = []
                if requirement.variable in observation.measured_variables:
                    raw = observation.measured_variables[requirement.variable]
                    value = raw.get("value") if isinstance(raw, dict) else raw
                    unit = raw.get("unit") if isinstance(raw, dict) else None
                    candidates.append((value, unit, True))
                candidates.extend(
                    (measurement.value, measurement.unit,
                     measurement.semantic_status == "resolved")
                    for measurement in observation.canonical_measurements
                    if measurement.canonical_variable == requirement.variable
                )
                usable = [(value, unit) for value, unit, semantic in candidates if semantic and value is not None]
                if usable:
                    units = {unit for _, unit in usable}
                    if any(unit in requirement.compatible_units for unit in units):
                        matches.append(observation.observation_id)
                    elif None in units:
                        unknown.append(observation.observation_id)
                    else:
                        incompatible.append(observation.observation_id)
                elif candidates:
                    unknown.append(observation.observation_id)
            if matches:
                checks.append(SufficiencyCheck(
                    criterion=f"measurement:{requirement.variable}", status="satisfied",
                    evidence_ids=tuple(matches), explanation="At least one observation carries the required variable in an explicitly compatible unit.",
                ))
            elif unknown:
                checks.append(SufficiencyCheck(
                    criterion=f"measurement:{requirement.variable}", status="unknown",
                    evidence_ids=tuple(unknown), explanation="The variable is present, but units are absent; compatibility remains unknown.",
                ))
                missing.append(f"measurement unit for {requirement.variable}")
            elif incompatible:
                checks.append(SufficiencyCheck(
                    criterion=f"measurement:{requirement.variable}", status="unsatisfied",
                    evidence_ids=tuple(incompatible), explanation="The required variable is present only in units outside the method's explicitly compatible unit set; no conversion is inferred.",
                ))
                missing.append(f"compatible measurement unit for {requirement.variable}")
            else:
                checks.append(SufficiencyCheck(
                    criterion=f"measurement:{requirement.variable}", status="unsatisfied",
                    explanation="No acquired observation provides this required measurement.",
                ))
                missing.append(f"measurement:{requirement.variable}")

        count_status: Literal["satisfied", "unsatisfied", "unknown"] = (
            "unknown" if method.minimum_observation_count is None
            else "satisfied" if len(items) >= method.minimum_observation_count
            else "unsatisfied"
        )
        checks.append(SufficiencyCheck(
            criterion="minimum_observation_count", status=count_status,
            evidence_ids=tuple(item.observation_id for item in items),
            explanation=(
                "The method's declared minimum observation count is met."
                if count_status == "satisfied"
                else "The method's declared minimum observation count is not met."
                if count_status == "unsatisfied"
                else "The method record does not declare a minimum observation count; sample adequacy remains unknown."
            ),
        ))
        if count_status != "satisfied":
            missing.append("method-required observation count")

        required_modalities = set(method.required_modalities)
        available_modalities = {modality for item in items for modality in item.modalities}
        modality_matches = [item.observation_id for item in items if required_modalities.intersection(set(item.modalities))]
        modalities_satisfied = required_modalities.issubset(available_modalities)
        checks.append(SufficiencyCheck(
            criterion="required_modalities",
            status="satisfied" if modalities_satisfied else "unsatisfied" if items else "unknown",
            evidence_ids=tuple(sorted(modality_matches)),
            explanation=("The observation set declares all method-required modalities." if modalities_satisfied else "The observation set does not declare every required modality."),
        ))
        if not modalities_satisfied:
            missing.append("observation modalities: " + ", ".join(sorted(required_modalities)))

        spatial = _spatial_check(items, query)
        checks.append(spatial)
        if spatial.status != "satisfied":
            missing.append("spatial coverage for requested area")
        temporal = _temporal_check(items, query)
        checks.append(temporal)
        if temporal.status != "satisfied":
            missing.append("temporal coverage for requested interval")

        provenance_ids = tuple(item.observation_id for item in items if item.provenance)
        checks.append(SufficiencyCheck(
            criterion="provenance", status=("satisfied" if len(provenance_ids) == len(items) and items else "unknown"),
            evidence_ids=provenance_ids,
            explanation="Every observation must carry a non-empty source provenance record; non-empty metadata is only a completeness check, not validation of provenance claims.",
        ))
        if len(provenance_ids) != len(items) or not items:
            missing.append("complete observation provenance")

        uncertainty_ids = tuple(
            item.observation_id for item in items
            if item.uncertainty and all(
                category in item.uncertainty for category in method.required_uncertainty_categories
            )
        )
        uncertainty_satisfied = not method.required_uncertainty_categories or len(uncertainty_ids) == len(items) and bool(items)
        checks.append(SufficiencyCheck(
            criterion="required_uncertainty_declarations",
            status="satisfied" if uncertainty_satisfied else "unknown",
            evidence_ids=uncertainty_ids,
            explanation="Only declared required uncertainty categories are checked; their values and semantics are not inferred.",
        ))
        if not uncertainty_satisfied:
            missing.append("required uncertainty declarations")

        dataset_ids = {item.dataset.dataset_id for item in items if item.dataset}
        required_datasets = set(method.required_datasets)
        # Human-readable dataset constraints are not identities. Preserve unknown
        # unless a capability declaration carries an exact matching requirement.
        exact_dataset_matches = {item for item in required_datasets if item in dataset_ids}
        dataset_status = "satisfied" if exact_dataset_matches == required_datasets else "unknown"
        checks.append(SufficiencyCheck(
            criterion="required_datasets", status=dataset_status,
            evidence_ids=tuple(sorted(item.observation_id for item in items if item.dataset and item.dataset.dataset_id in exact_dataset_matches)),
            explanation="Dataset constraints are descriptive; no equivalence is inferred between a description and a dataset ID." if dataset_status == "unknown" else "All exact required dataset IDs are present.",
        ))
        if dataset_status != "satisfied":
            missing.append("method-compatible dataset identity")

        executable_status: Literal["satisfied", "unsatisfied"] = "satisfied" if executable else "unsatisfied"
        checks.append(SufficiencyCheck(
            criterion="registered_certified_implementation", status=executable_status,
            explanation="A matching implementation must exist and pass the platform certification gate." if executable else "The catalog record does not identify an implementation registered as certified in this runtime.",
        ))
        if not executable:
            missing.append("certified executable method implementation")

        benchmark_map = {"applicable": "satisfied", "not_applicable": "unsatisfied", "unknown": "unknown"}
        checks.append(SufficiencyCheck(
            criterion=f"benchmark:{method.benchmark_suite_id or 'not_registered'}",
            status=benchmark_map[benchmark_suite_status],
            explanation="A method benchmark must be available and applicable to the method and investigation scope." if benchmark_suite_status == "applicable" else "Benchmark suite applicability has not been established for this investigation.",
        ))
        if benchmark_suite_status != "applicable":
            missing.append("applicable validated benchmark suite")

        statuses = {item.status for item in checks}
        status: Literal["sufficient", "insufficient", "indeterminate"]
        if "unsatisfied" in statuses:
            status = "insufficient"
        elif "unknown" in statuses:
            status = "indeterminate"
        else:
            status = "sufficient"
        return MethodEvidenceSufficiency(
            method_id=method.method_id, method_version=method.version, status=status,
            executable=executable, checks=tuple(checks), missing_observations=tuple(dict.fromkeys(missing)),
            capability_matrix_revision=matrix.revision, benchmark_suite_status=benchmark_suite_status,
            explanation=("Every declared method precondition was verified." if status == "sufficient" else "At least one declared precondition is absent." if status == "insufficient" else "At least one declared precondition cannot be determined from available evidence."),
        )


class AdaptiveObservationRecommendation(Contract):
    recommendation_id: str
    method_id: str
    method_version: str
    missing_observation: str
    rationale: str
    capability_matches: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()
    connectors: tuple[str, ...] = ()
    methods_enabled_after_acquisition: tuple[str, ...] = ()
    acquisition_status: Literal["recommended_only_not_executed"] = "recommended_only_not_executed"


class AdaptiveInvestigationRefiner:
    """Recommend declared evidence gaps and matrix candidates, never acquire."""

    def recommend(
        self,
        sufficiency: Iterable[MethodEvidenceSufficiency],
        methods: Iterable[ScientificMethodKnowledge],
        matrix: EarthCapabilityMatrix,
    ) -> tuple[AdaptiveObservationRecommendation, ...]:
        method_map = {(item.method_id, item.version): item for item in methods}
        output = []
        for assessment in sufficiency:
            method = method_map.get((assessment.method_id, assessment.method_version))
            if method is None or assessment.status == "sufficient":
                continue
            for missing in assessment.missing_observations:
                if not missing.startswith((
                    "measurement:", "compatible measurement unit for ",
                    "measurement unit for ", "observation modalities:",
                    "spatial coverage", "temporal coverage",
                    "required uncertainty", "complete observation provenance",
                )):
                    continue
                if missing.startswith("compatible measurement unit for "):
                    variable = missing.removeprefix("compatible measurement unit for ")
                elif missing.startswith("measurement unit for "):
                    variable = missing.removeprefix("measurement unit for ")
                else:
                    variable = missing.removeprefix("measurement:").split(" ", 1)[0]
                candidates = [
                    entry for entry in matrix.entries if entry.scope == "dataset"
                    and (
                        any(
                            (item.canonical_name or item.source_name) == variable
                            and (
                                not missing.startswith((
                                    "compatible measurement unit for ",
                                    "measurement unit for ",
                                ))
                                or item.unit in next(
                                    requirement.compatible_units
                                    for requirement in method.required_measurements
                                    if requirement.variable == variable
                                )
                            )
                            for item in entry.variables
                        )
                        if missing.startswith(("measurement:", "compatible measurement unit for ", "measurement unit for "))
                        else set(method.required_variables).issubset(
                            {item.canonical_name or item.source_name for item in entry.variables}
                        ) and set(method.required_modalities).issubset(set(entry.modalities))
                    )
                ]
                candidate_ids = tuple(sorted({entry.dataset_id for entry in candidates if entry.dataset_id}))
                connector_ids = tuple(sorted({entry.connector_id for entry in candidates}))
                identity = hashlib.sha256(
                    f"{assessment.method_id}@{assessment.method_version}:{missing}:{matrix.revision}".encode()
                ).hexdigest()[:24]
                output.append(AdaptiveObservationRecommendation(
                    recommendation_id=identity, method_id=assessment.method_id,
                    method_version=assessment.method_version, missing_observation=missing,
                    rationale=(
                        f"{missing} is required by the versioned method manifest; acquisition is not automatic."
                        if method.implementation_status == "executable_certified"
                        else f"{missing} is required by the cited method record. Acquiring it alone will not make the method executable because no certified SatQuery implementation is registered."
                    ),
                    capability_matches=tuple(sorted(f"{item.connector_id}:{item.dataset_id}" for item in candidates if item.dataset_id)),
                    datasets=candidate_ids, connectors=connector_ids,
                    methods_enabled_after_acquisition=(
                        (f"{method.method_id}@{method.version}",)
                        if method.implementation_status == "executable_certified"
                        else ()
                    ),
                ))
        return tuple(sorted(output, key=lambda item: item.recommendation_id))


def _spatial_check(observations: tuple[Observation, ...], query: EarthQuery) -> SufficiencyCheck:
    if query.point is None and query.bbox is None and query.geometry is None:
        return SufficiencyCheck(criterion="spatial_coverage", status="satisfied", explanation="No spatial restriction was declared by the investigation.")
    unknown: list[str] = []
    try:
        from .spatial import bbox_geometry, geometry_contains, normalize_geometry
        query_geometry = query.geometry or (bbox_geometry(_bbox4(query.bbox)) if query.bbox else {"type": "Point", "coordinates": query.point})
        for item in observations:
            geometry = item.geometry or (bbox_geometry(_bbox4(item.bbox)) if item.bbox and len(item.bbox) >= 4 else None)
            if geometry is None or not item.crs:
                unknown.append(item.observation_id)
                continue
            normalized = normalize_geometry(geometry, source_crs=item.crs)
            wanted = normalize_geometry(query_geometry, source_crs=query.crs)
            if geometry_contains(normalized, wanted):
                return SufficiencyCheck(criterion="spatial_coverage", status="satisfied", evidence_ids=(item.observation_id,), explanation="One observation geometry contains the requested area after CRS normalization.")
    except (RuntimeError, ValueError, TypeError):
        unknown.extend(item.observation_id for item in observations)
    return SufficiencyCheck(criterion="spatial_coverage", status="unknown", evidence_ids=tuple(sorted(set(unknown))), explanation="Full requested-area coverage cannot be established from the available observation geometries; partial observations may still collectively cover the area, but no union-coverage proof is available.")


def _temporal_check(observations: tuple[Observation, ...], query: EarthQuery) -> SufficiencyCheck:
    if query.temporal_start is None and query.temporal_end is None:
        return SufficiencyCheck(criterion="temporal_coverage", status="satisfied", explanation="No temporal restriction was declared by the investigation.")
    matches = []
    unknown = []
    for item in observations:
        extent = item.temporal_extent
        if extent is None:
            if item.observed_at is None:
                unknown.append(item.observation_id)
            else:
                start = end = item.observed_at
                if query.temporal_start == start and query.temporal_end == end:
                    matches.append(item.observation_id)
                else:
                    unknown.append(item.observation_id)
            continue
        if extent.start is None or extent.end is None:
            unknown.append(item.observation_id)
            continue
        if (query.temporal_start is None or extent.start <= query.temporal_start) and (query.temporal_end is None or extent.end >= query.temporal_end):
            matches.append(item.observation_id)
    return SufficiencyCheck(
        criterion="temporal_coverage", status="satisfied" if matches else "unknown",
        evidence_ids=tuple(sorted(matches)),
        explanation="At least one observation declares an interval containing the full requested period." if matches else "Complete temporal coverage of the requested interval is not established.",
    )


def _bbox4(bounds: tuple[float, ...]) -> tuple[float, float, float, float]:
    if len(bounds) == 6:
        return (bounds[0], bounds[1], bounds[3], bounds[4])
    return (bounds[0], bounds[1], bounds[2], bounds[3])
