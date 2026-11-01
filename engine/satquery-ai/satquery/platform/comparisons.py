"""Cross-investigation evidence alignment without inferred change claims."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator

from .contracts import (
    Contract,
    Observation,
    ObservationAlignmentIssue,
    ObservationStack,
    TemporalDifferenceDiagnostic,
    TemporalDifferenceIssue,
)
from .reports import build_investigation_report
from .scientific_governance import canonical_digest
from .spatiotemporal import (
    ConsecutiveTemporalDifferenceEngine,
    ExactSupportObservationStackBuilder,
)

if TYPE_CHECKING:
    from .runtime import PlatformRuntime


class InvestigationComparisonRequest(Contract):
    investigation_ids: tuple[str, ...] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def unique_investigations(self) -> InvestigationComparisonRequest:
        if len(self.investigation_ids) != len(set(self.investigation_ids)):
            raise ValueError("investigation_ids must be unique")
        return self


class ComparisonMeasurement(Contract):
    investigation_id: str
    observation_id: str
    canonical_variable: str
    value: Any = None
    unit: str
    observed_at: str | None = None
    dataset: dict[str, Any] | None = None
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class MeasurementComparisonGroup(Contract):
    canonical_variable: str
    unit: str
    records: tuple[ComparisonMeasurement, ...] = ()
    investigation_ids: tuple[str, ...] = ()
    coverage: str
    interpretation: str = (
        "Exact canonical variable and unit labels are aligned for inspection. "
        "This does not establish scientific comparability, temporal trend, or causation."
    )


class InvestigationComparison(Contract):
    comparison_id: str
    comparison_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    schema_version: str = "1.2"
    stack_builder_version: str = Field(min_length=1)
    temporal_method_id: str = Field(min_length=1)
    temporal_method_version: str = Field(min_length=1)
    investigation_reports: tuple[dict[str, Any], ...]
    measurement_groups: tuple[MeasurementComparisonGroup, ...] = ()
    observation_stacks: tuple[ObservationStack, ...] = ()
    temporal_diagnostics: tuple[TemporalDifferenceDiagnostic, ...] = ()
    alignment_issues: tuple[ObservationAlignmentIssue, ...] = ()
    temporal_issues: tuple[TemporalDifferenceIssue, ...] = ()
    observation_identity_conflicts: tuple[dict[str, Any], ...] = ()
    unmatched_observation_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...]
    markdown: str


def compare_investigations(
    runtime: PlatformRuntime, request: InvestigationComparisonRequest
) -> InvestigationComparison:
    if len(request.investigation_ids) != len(set(request.investigation_ids)):
        raise ValueError("investigation_ids must be unique")
    reports = tuple(
        build_investigation_report(runtime, identifier)
        for identifier in sorted(request.investigation_ids)
    )
    grouped: dict[tuple[str, str], list[ComparisonMeasurement]] = {}
    observations_by_id: dict[str, Observation] = {}
    conflicting_observations: dict[str, dict[str, Any]] = {}
    matched_observation_ids: set[str] = set()
    for report in reports:
        investigation_id = report.investigation["investigation_id"]
        for observation in report.observations:
            existing = observations_by_id.get(observation.observation_id)
            if existing is None:
                observations_by_id[observation.observation_id] = observation
            elif existing != observation:
                conflicting_observations.setdefault(observation.observation_id, {
                    "observation_id": observation.observation_id,
                    "investigations": set(),
                    "content_digests": set(),
                })["investigations"].add(investigation_id)
                conflict = conflicting_observations[observation.observation_id]
                conflict["investigations"].add(
                    next((
                        prior.investigation["investigation_id"]
                        for prior in reports
                        if any(item.observation_id == observation.observation_id for item in prior.observations)
                    ), investigation_id)
                )
                conflict["content_digests"].update((
                    canonical_digest(existing.model_dump(mode="json")),
                    canonical_digest(observation.model_dump(mode="json")),
                ))
            resolved = tuple(
                item for item in observation.canonical_measurements
                if item.semantic_status == "resolved"
                and item.unit is not None
                and item.unit.strip()
            )
            for measurement in resolved:
                grouped.setdefault(
                    (measurement.canonical_variable, measurement.unit), []
                ).append(ComparisonMeasurement(
                    investigation_id=investigation_id,
                    observation_id=observation.observation_id,
                    canonical_variable=measurement.canonical_variable,
                    value=measurement.value,
                    unit=measurement.unit,
                    observed_at=(observation.observed_at.isoformat() if observation.observed_at else None),
                    dataset=(observation.dataset.model_dump(mode="json") if observation.dataset else None),
                    uncertainty=observation.uncertainty,
                    provenance={
                        "observation": observation.provenance,
                        "measurement": measurement.source_metadata,
                        "source_variable": measurement.source_variable,
                        "source_unit": measurement.source_unit,
                    },
                ))
                matched_observation_ids.add(observation.observation_id)

    for observation_id in conflicting_observations:
        observations_by_id.pop(observation_id, None)
    identity_conflicts = tuple(
        {
            "observation_id": key,
            "investigation_ids": tuple(sorted(value["investigations"])),
            "content_digests": tuple(sorted(value["content_digests"])),
            "resolution": "excluded_from_temporal_alignment",
        }
        for key, value in sorted(conflicting_observations.items())
    )
    stack_builder = ExactSupportObservationStackBuilder()
    stack_build = stack_builder.build(
        tuple(observations_by_id[key] for key in sorted(observations_by_id))
    )
    temporal_engine = ConsecutiveTemporalDifferenceEngine()
    temporal_diagnostics, temporal_issues = temporal_engine.build(
        stack_build.stacks
    )

    groups = []
    for (variable, unit), records in sorted(grouped.items()):
        records.sort(key=lambda item: (
            item.observed_at is None,
            item.observed_at or "",
            item.investigation_id,
            item.observation_id,
        ))
        investigation_ids = tuple(sorted({item.investigation_id for item in records}))
        groups.append(MeasurementComparisonGroup(
            canonical_variable=variable,
            unit=unit,
            records=tuple(records),
            investigation_ids=investigation_ids,
            coverage=(
                "present_in_all_selected_investigations"
                if set(investigation_ids) == set(request.investigation_ids)
                else "present_in_subset_of_selected_investigations"
            ),
        ))
    unmatched = tuple(sorted(set(observations_by_id) - matched_observation_ids))
    limitations = (
        "Comparison aligns only explicitly resolved canonical variable identifiers and exact unit strings.",
        "No unit conversion, temporal aggregation, spatial resampling, statistical test, trend, anomaly, or causal analysis is performed.",
        "Differences in dataset, sensor, calibration, quality, spatial support, temporal support, and sampling design may make aligned values scientifically incomparable.",
        "Unresolved measurements and observations without resolved canonical measurements remain listed as unmatched; they are not discarded from their source investigation reports.",
        "Temporal diagnostics are emitted only for exact declared support, exact units, and compatible source dataset/variable identities; they are descriptive arithmetic, not trend, significance, or causal analysis.",
        "Uncertainty remains attached to source observations and is not propagated through temporal differences.",
        "Observation identifiers with conflicting canonical content across investigations are excluded from temporal alignment and listed as identity conflicts.",
        "Investigation report snapshots include evidence and scientific records, not mutable monitoring lifecycle or prior comparison context; those operational records remain available from their investigation and monitoring APIs.",
    )
    report_payload = tuple(_comparison_report_snapshot(item) for item in reports)
    group_payload = tuple(item.model_dump(mode="json") for item in groups)
    base_payload = {
        "investigation_ids": tuple(sorted(request.investigation_ids)),
        "reports": report_payload,
        "stack_builder_version": stack_build.builder_version,
        "temporal_method_id": temporal_engine.METHOD_ID,
        "temporal_method_version": temporal_engine.VERSION,
        "groups": group_payload,
        "observation_stacks": tuple(item.model_dump(mode="json") for item in stack_build.stacks),
        "temporal_diagnostics": tuple(item.model_dump(mode="json") for item in temporal_diagnostics),
        "alignment_issues": tuple(item.model_dump(mode="json") for item in stack_build.issues),
        "temporal_issues": tuple(item.model_dump(mode="json") for item in temporal_issues),
        "identity_conflicts": identity_conflicts,
        "unmatched": unmatched,
        "limitations": limitations,
    }
    source_digest = canonical_digest(base_payload)
    lines = [
        "# Investigation comparison",
        "",
        f"- Investigations: {', '.join(f'`{identifier}`' for identifier in sorted(request.investigation_ids))}",
        f"- Aligned measurement groups: {len(groups)}",
        f"- Observations without resolved measurements: {len(unmatched)}",
        f"- Exact-support temporal stacks: {len(stack_build.stacks)}",
        f"- Descriptive consecutive differences: {len(temporal_diagnostics)}",
        f"- Temporal alignment blockers: {len(stack_build.issues) + len(temporal_issues)}",
        f"- Stack builder version: `{stack_build.builder_version}`",
        f"- Temporal method: `{temporal_engine.METHOD_ID}@{temporal_engine.VERSION}`",
        f"- Source records digest: `{source_digest}`",
        "",
        "Exact canonical variable and unit labels are aligned for inspection. Arithmetic differences, when shown, are descriptive only and do not establish scientific comparability or a scientifically interpreted change.",
        "",
        "## Measurements",
        "",
    ]
    if not groups:
        lines.append("No resolved canonical measurements with explicit units are available to align across the selected investigations.")
    for group in groups:
        lines.extend([
            f"### {group.canonical_variable} ({group.unit})",
            "",
            f"Coverage: {group.coverage}",
            "",
        ])
        lines.extend(
            f"- Investigation `{item.investigation_id}`, observation `{item.observation_id}`, "
            f"time `{item.observed_at or 'unknown'}`: `{item.value}`; dataset "
            f"`{(item.dataset or {}).get('connector_id', 'unknown')}/"
            f"{(item.dataset or {}).get('dataset_id', 'unknown')}`"
            for item in group.records
        )
        lines.append("")
    lines.extend(["## Exact-support temporal diagnostics", ""])
    if temporal_diagnostics:
        for diagnostic in temporal_diagnostics:
            lines.append(
                f"- `{diagnostic.canonical_variable or diagnostic.variable_key}` ({diagnostic.unit}) "
                f"from `{diagnostic.earlier.observation_id}` to `{diagnostic.later.observation_id}`: "
                f"later minus earlier = `{diagnostic.difference_value}` over "
                f"`{diagnostic.elapsed_seconds}` seconds; method "
                f"`{diagnostic.method_id}@{diagnostic.method_version}`. Descriptive only; "
                "uncertainty is not propagated."
            )
    else:
        lines.append("No exact-support consecutive temporal differences were eligible.")
    if stack_build.issues or temporal_issues:
        lines.extend(["", "### Temporal blockers", ""])
        lines.extend(
            f"- Observation `{item.observation_id}` [{item.code}]: {item.message}"
            for item in stack_build.issues
        )
        lines.extend(
            f"- Stack `{item.stack_id}`, observations `{item.earlier_observation_id}` → "
            f"`{item.later_observation_id}` [{item.code}]: {item.message}"
            for item in temporal_issues
        )
    if identity_conflicts:
        lines.extend(["", "### Conflicting observation identities", ""])
        lines.extend(
            f"- Observation `{item['observation_id']}` has differing canonical content "
            f"in investigations {', '.join(item['investigation_ids'])}; excluded from temporal alignment."
            for item in identity_conflicts
        )
    lines.append("")
    if unmatched:
        lines.extend([
            "## Observations without aligned measurements",
            "",
            *(f"- `{identifier}`" for identifier in unmatched),
            "",
        ])
    lines.extend([
        "## Limitations",
        "",
        *(f"- {item}" for item in limitations),
        "",
        "No trends, statistical tests, or scientific conclusions were generated. Any differences shown are descriptive arithmetic only.",
    ])
    markdown = "\n".join(lines)
    digest = canonical_digest({**base_payload, "markdown": markdown})
    return InvestigationComparison(
        comparison_id=f"investigation-comparison:{digest[:20]}",
        comparison_sha256=digest,
        stack_builder_version=stack_build.builder_version,
        temporal_method_id=temporal_engine.METHOD_ID,
        temporal_method_version=temporal_engine.VERSION,
        investigation_reports=report_payload,
        measurement_groups=tuple(groups),
        observation_stacks=stack_build.stacks,
        temporal_diagnostics=temporal_diagnostics,
        alignment_issues=stack_build.issues,
        temporal_issues=temporal_issues,
        observation_identity_conflicts=identity_conflicts,
        unmatched_observation_ids=unmatched,
        limitations=limitations,
        markdown=markdown,
    )


def _comparison_report_snapshot(report) -> dict[str, Any]:
    """Return stable evidence records without mutable operational projections."""
    payload = report.model_dump(mode="json")
    fields = (
        "mission", "investigation", "plan", "design", "executions",
        "observations", "observation_stacks", "temporal_differences",
        "temporal_difference_issues", "alignment_issues", "earth_objects",
        "assessment", "reasoning", "unavailable_artifact_ids",
        "unavailable_execution_ids",
    )
    snapshot = {field: payload[field] for field in fields}
    snapshot["snapshot_sha256"] = canonical_digest(snapshot)
    return snapshot
