"""Cross-investigation evidence alignment without inferred change claims."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field, model_validator

from .contracts import Contract, Observation
from .reports import build_investigation_report
from .scientific_governance import canonical_digest

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
    schema_version: str = "1.0"
    investigation_reports: tuple[dict[str, Any], ...]
    measurement_groups: tuple[MeasurementComparisonGroup, ...] = ()
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
    matched_observation_ids: set[str] = set()
    for report in reports:
        investigation_id = report.investigation["investigation_id"]
        for observation in report.observations:
            observations_by_id[observation.observation_id] = observation
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
    )
    report_payload = tuple(item.model_dump(mode="json") for item in reports)
    group_payload = tuple(item.model_dump(mode="json") for item in groups)
    base_payload = {
        "investigation_ids": tuple(sorted(request.investigation_ids)),
        "reports": report_payload,
        "groups": group_payload,
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
        f"- Source records digest: `{source_digest}`",
        "",
        "Exact canonical variable and unit labels are aligned for inspection. The comparison does not establish scientific comparability or infer change.",
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
        "No deltas, trends, or conclusions were generated.",
    ])
    markdown = "\n".join(lines)
    digest = canonical_digest({**base_payload, "markdown": markdown})
    return InvestigationComparison(
        comparison_id=f"investigation-comparison:{digest[:20]}",
        comparison_sha256=digest,
        investigation_reports=report_payload,
        measurement_groups=tuple(groups),
        unmatched_observation_ids=unmatched,
        limitations=limitations,
        markdown=markdown,
    )
