"""Deterministic, evidence-linked investigation reports for platform users."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import Field

from ..errors import ValidationError
from .contracts import (
    Contract,
    EarthObject,
    ExecutionResult,
    Observation,
    ObservationAlignmentIssue,
    ObservationSearchResult,
    ObservationStack,
    PerceptionResult,
    TemporalDifferenceDiagnostic,
    TemporalDifferenceIssue,
)
from .earth_memory import EarthMemoryQuery
from .intelligence import EvidenceAssessment, InvestigationDesign
from .monitoring import monitoring_schedule_revision_identity
from .planning import InvestigationPlan
from .reasoning import ScientificReasoningReport
from .scientific_governance import canonical_digest

if TYPE_CHECKING:
    from .runtime import PlatformRuntime


class InvestigationReport(Contract):
    """A reproducible view over recorded artifacts, not a new inference."""

    report_id: str = Field(min_length=1)
    report_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    source_records_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    schema_version: str = "1.4"
    mission: dict[str, Any]
    investigation: dict[str, Any]
    plan: dict[str, Any] | None = None
    design: dict[str, Any] | None = None
    executions: tuple[dict[str, Any], ...] = ()
    observations: tuple[Observation, ...] = ()
    observation_stacks: tuple[ObservationStack, ...] = ()
    temporal_differences: tuple[TemporalDifferenceDiagnostic, ...] = ()
    temporal_difference_issues: tuple[TemporalDifferenceIssue, ...] = ()
    alignment_issues: tuple[ObservationAlignmentIssue, ...] = ()
    earth_objects: tuple[EarthObject, ...] = ()
    assessment: dict[str, Any] | None = None
    reasoning: ScientificReasoningReport | None = None
    monitoring_context: dict[str, Any] | None = None
    monitoring_trigger_context: tuple[dict[str, Any], ...] = ()
    comparison_artifacts: tuple[dict[str, Any], ...] = ()
    unavailable_artifact_ids: tuple[str, ...] = ()
    unavailable_execution_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    markdown: str


def build_investigation_report(
    runtime: PlatformRuntime, investigation_id: str
) -> InvestigationReport:
    """Assemble current canonical records without adding scientific claims."""
    investigation = runtime.investigation_service.get(investigation_id)
    mission = runtime.mission_service.get(investigation.mission_id)
    plan: InvestigationPlan | None = None
    design: InvestigationDesign | None = None
    unavailable_artifacts: list[str] = []
    if investigation.investigation_plan_id:
        try:
            plan = runtime.get_investigation_plan(investigation.investigation_plan_id)
        except ValidationError:
            unavailable_artifacts.append(investigation.investigation_plan_id)
    if investigation.investigation_design_id:
        try:
            design = runtime.get_investigation_design(investigation.investigation_design_id)
        except ValidationError:
            unavailable_artifacts.append(investigation.investigation_design_id)
    assessment: EvidenceAssessment | None = runtime.get_evidence_assessment(investigation_id)
    reasoning = runtime.get_scientific_reasoning(investigation_id)

    executions: list[ExecutionResult] = []
    unavailable: list[str] = []
    for execution_id in investigation.result_ids:
        try:
            executions.append(runtime.get_execution_result(execution_id))
        except ValidationError:
            # The missing reference is visible in the report; never replace it
            # with an empty or synthetic execution result.
            unavailable.append(execution_id)

    observations_by_id: dict[str, Observation] = {}
    stacks_by_id: dict[str, ObservationStack] = {}
    differences_by_id: dict[str, TemporalDifferenceDiagnostic] = {}
    difference_issues_by_key: dict[tuple[str, str, str], TemporalDifferenceIssue] = {}
    alignment_issues_by_key: dict[tuple[str, str, str], ObservationAlignmentIssue] = {}
    for execution in executions:
        for task in execution.tasks:
            output = task.output
            if isinstance(output, dict) and "observations" in output:
                if "query_fingerprint" in output:
                    output = PerceptionResult.model_validate(output)
                else:
                    output = ObservationSearchResult.model_validate(output)
            for observation in getattr(output, "observations", ()):
                observations_by_id.setdefault(observation.observation_id, observation)
            for stack in getattr(output, "observation_stacks", ()):
                stacks_by_id.setdefault(stack.stack_id, stack)
            for difference in getattr(output, "temporal_differences", ()):
                differences_by_id.setdefault(difference.diagnostic_id, difference)
            for issue in getattr(output, "temporal_difference_issues", ()):
                difference_issues_by_key.setdefault(
                    (issue.stack_id, issue.earlier_observation_id, issue.later_observation_id),
                    issue,
                )
            for issue in getattr(output, "alignment_issues", ()):
                alignment_issues_by_key.setdefault(
                    (issue.observation_id, issue.canonical_variable or "", issue.code),
                    issue,
                )
    observations = tuple(observations_by_id[key] for key in sorted(observations_by_id))
    observation_stacks = tuple(stacks_by_id[key] for key in sorted(stacks_by_id))
    temporal_differences = tuple(
        sorted(
            differences_by_id.values(),
            key=lambda item: (
                item.earlier.observed_at,
                item.later.observed_at,
                item.stack_id,
                item.diagnostic_id,
            ),
        )
    )
    temporal_difference_issues = tuple(
        difference_issues_by_key[key] for key in sorted(difference_issues_by_key)
    )
    alignment_issues = tuple(
        alignment_issues_by_key[key] for key in sorted(alignment_issues_by_key)
    )
    observation_ids = set(observations_by_id)
    earth_objects = tuple(sorted(
        (
            item for item in runtime.earth_objects.current()
            if item.investigation_id == investigation_id
            or investigation_id in item.investigation_ids
            or observation_ids.intersection(item.source_observation_ids)
        ),
        key=lambda item: (item.stable_identity or "", item.revision, item.object_id),
    ))
    monitoring_context: dict[str, Any] | None = None
    monitoring_trigger_context: tuple[dict[str, Any], ...] = ()
    for task in investigation.tasks:
        trigger = task.parameters.get("monitoring_trigger")
        if isinstance(trigger, dict):
            monitoring_trigger_context += (trigger,)
    monitoring_runs = runtime.monitoring_service.runs_for_investigation(investigation_id)
    if monitoring_runs or monitoring_trigger_context:
        schedule_definitions: dict[str, dict[str, Any]] = {}
        missing_schedule_revisions: set[str] = set()
        monitoring_events: dict[str, dict[str, Any]] = {}
        monitoring_notifications: dict[str, dict[str, Any]] = {}
        for run in monitoring_runs:
            revision_id = monitoring_schedule_revision_identity(
                run.schedule_id, run.schedule_revision
            )
            revision_artifact = runtime.earth_memory.get(revision_id)
            if revision_artifact is None:
                missing_schedule_revisions.add(revision_id)
            else:
                schedule_definitions[revision_id] = revision_artifact.payload
            for event in runtime.monitoring_service.events(
                run.schedule_id, limit=1000, run_id=run.run_id
            ):
                monitoring_events[event.event_id] = event.model_dump(mode="json")
            for notification in runtime.monitoring_service.notifications(
                run.schedule_id, limit=1000
            ):
                if notification.run_id == run.run_id:
                    monitoring_notifications[notification.notification_id] = (
                        notification.model_dump(mode="json")
                    )
        for trigger in monitoring_trigger_context:
            schedule_id = trigger.get("schedule_id")
            if not isinstance(schedule_id, str):
                continue
            revision_id = monitoring_schedule_revision_identity(
                schedule_id, int(trigger.get("schedule_revision", 1))
            )
            revision_artifact = runtime.earth_memory.get(revision_id)
            if revision_artifact is None:
                missing_schedule_revisions.add(revision_id)
            else:
                schedule_definitions[revision_id] = revision_artifact.payload
            evaluation_id = trigger.get("evaluation_id")
            for event in runtime.monitoring_service.iter_events(schedule_id):
                if event.payload.get("evaluation_id") == evaluation_id:
                    monitoring_events[event.event_id] = event.model_dump(mode="json")
        monitoring_context = {
            "schedule_definitions": tuple(
                schedule_definitions[key] for key in sorted(schedule_definitions)
            ),
            "runs": tuple(
                item.model_dump(mode="json")
                for item in sorted(
                    monitoring_runs, key=lambda value: (value.started_at, value.run_id)
                )
            ),
            "events": tuple(monitoring_events[key] for key in sorted(monitoring_events)),
            "notifications": tuple(
                monitoring_notifications[key]
                for key in sorted(monitoring_notifications)
            ),
            "missing_schedule_revision_ids": tuple(sorted(missing_schedule_revisions)),
        }
    comparison_artifacts = []
    comparison_query = EarthMemoryQuery(
        artifact_types=("investigation_comparison", "monitoring_comparison"),
        source_artifact_id=f"investigation:{investigation_id}",
        limit=1000,
    )
    while True:
        comparison_page = runtime.search_earth_memory(comparison_query)
        comparison_artifacts.extend({
            "artifact_id": item.artifact_id,
            "artifact_type": item.artifact_type,
            "payload_sha256": item.payload_sha256,
            "source_artifact_ids": item.source_artifact_ids,
            "metadata": item.metadata,
            "comparison_id": item.payload.get("comparison_id"),
            "comparison_sha256": item.payload.get("comparison_sha256"),
            "investigation_ids": tuple(sorted(
                report.get("investigation", {}).get("investigation_id")
                for report in item.payload.get("investigation_reports", ())
                if report.get("investigation", {}).get("investigation_id")
            )),
            "measurement_group_count": len(item.payload.get("measurement_groups", ())),
            "temporal_diagnostic_count": len(item.payload.get("temporal_diagnostics", ())),
            "alignment_issue_count": len(item.payload.get("alignment_issues", ())),
            "temporal_issue_count": len(item.payload.get("temporal_issues", ())),
        } for item in comparison_page.artifacts)
        if comparison_page.next_cursor is None:
            break
        comparison_query = comparison_query.model_copy(
            update={"cursor": comparison_page.next_cursor}
        )
    comparison_artifacts.sort(key=lambda item: item["artifact_id"])
    limitations: list[str] = []
    for source in (plan, design, assessment, reasoning):
        limitations.extend(getattr(source, "limitations", ()) if source else ())
    if unavailable or unavailable_artifacts:
        limitations.append(
            "One or more referenced investigation artifacts could not be loaded; they are listed as unavailable and are not represented as evidence."
        )
    if reasoning is None:
        limitations.append(
            "No scientific reasoning report is available; observations alone are not presented as a conclusion."
        )
    if monitoring_context and monitoring_context["missing_schedule_revision_ids"]:
        limitations.append(
            "One or more monitoring schedule revisions referenced by this investigation are unavailable in Earth Memory; run records are retained without reconstructing missing definitions."
        )
    if comparison_artifacts:
        limitations.append(
            "Cross-investigation comparison artifacts are linked as recorded context; their descriptive measurements are not promoted to scientific conclusions in this report."
        )
    limitations = list(dict.fromkeys(item for item in limitations if item))

    mission_data = mission.model_dump(mode="json")
    investigation_data = investigation.model_dump(mode="json")
    plan_data = plan.model_dump(mode="json") if plan else None
    design_data = design.model_dump(mode="json") if design else None
    assessment_data = assessment.model_dump(mode="json") if assessment else None
    execution_data = tuple(item.model_dump(mode="json") for item in executions)
    artifact_payload = {
        "mission": mission_data,
        "investigation": investigation_data,
        "plan": plan_data,
        "design": design_data,
        "executions": execution_data,
        "observations": tuple(item.model_dump(mode="json") for item in observations),
        "observation_stacks": tuple(
            item.model_dump(mode="json") for item in observation_stacks
        ),
        "temporal_differences": tuple(
            item.model_dump(mode="json") for item in temporal_differences
        ),
        "temporal_difference_issues": tuple(
            item.model_dump(mode="json") for item in temporal_difference_issues
        ),
        "alignment_issues": tuple(
            item.model_dump(mode="json") for item in alignment_issues
        ),
        "earth_objects": tuple(item.model_dump(mode="json") for item in earth_objects),
        "assessment": assessment_data,
        "reasoning": reasoning.model_dump(mode="json") if reasoning else None,
        "monitoring_context": monitoring_context,
        "monitoring_trigger_context": monitoring_trigger_context,
        "comparison_artifacts": tuple(comparison_artifacts),
        "unavailable_artifact_ids": tuple(sorted(unavailable_artifacts)),
        "unavailable_execution_ids": tuple(sorted(unavailable)),
        "limitations": tuple(limitations),
    }
    source_digest = canonical_digest(artifact_payload)
    markdown = _render_markdown(
        mission_data, investigation_data, plan, design, assessment, reasoning,
        executions, observations, observation_stacks, alignment_issues,
        temporal_differences, temporal_difference_issues,
        earth_objects, tuple(unavailable), tuple(limitations), source_digest,
        monitoring_context,
        tuple(comparison_artifacts),
    )
    digest = canonical_digest({**artifact_payload, "markdown": markdown})
    return InvestigationReport(
        report_id=f"investigation-report:{investigation_id}:{digest[:16]}",
        report_sha256=digest,
        source_records_sha256=source_digest,
        mission=mission_data,
        investigation=investigation_data,
        plan=plan_data,
        design=design_data,
        executions=execution_data,
        observations=observations,
        observation_stacks=observation_stacks,
        temporal_differences=temporal_differences,
        temporal_difference_issues=temporal_difference_issues,
        alignment_issues=alignment_issues,
        earth_objects=earth_objects,
        assessment=assessment_data,
        reasoning=reasoning,
        monitoring_context=monitoring_context,
        monitoring_trigger_context=monitoring_trigger_context,
        comparison_artifacts=tuple(comparison_artifacts),
        unavailable_artifact_ids=tuple(sorted(unavailable_artifacts)),
        unavailable_execution_ids=tuple(sorted(unavailable)),
        limitations=tuple(limitations),
        markdown=markdown,
    )


def _render_markdown(
    mission: dict[str, Any],
    investigation: dict[str, Any],
    plan: InvestigationPlan | None,
    design: InvestigationDesign | None,
    assessment: EvidenceAssessment | None,
    reasoning: ScientificReasoningReport | None,
    executions: list[ExecutionResult],
    observations: tuple[Observation, ...],
    observation_stacks: tuple[ObservationStack, ...],
    alignment_issues: tuple[ObservationAlignmentIssue, ...],
    temporal_differences: tuple[TemporalDifferenceDiagnostic, ...],
    temporal_difference_issues: tuple[TemporalDifferenceIssue, ...],
    earth_objects: tuple[EarthObject, ...],
    unavailable: tuple[str, ...],
    limitations: tuple[str, ...],
    source_digest: str,
    monitoring_context: dict[str, Any] | None,
    comparison_artifacts: tuple[dict[str, Any], ...],
) -> str:
    lines = [
        f"# Investigation report: {mission['name']}",
        "",
        f"- **Mission:** `{mission['mission_id']}` ({mission['status']})",
        f"- **Investigation:** `{investigation['investigation_id']}` ({investigation['status']})",
        f"- **Objective:** {mission['objective']}",
        f"- **Source records digest:** `{source_digest}`",
        "",
        "## Investigation state",
        "",
        f"- Planning: {plan.status if plan else 'not recorded'}",
        f"- Design: {design.status if design else 'not recorded'}",
        f"- Execution records: {len(executions)} available; {len(unavailable)} unavailable",
        f"- Evidence coverage: {assessment.status if assessment else 'not assessed'}",
        f"- Observations: {len(observations)} distinct canonical observation(s)",
        f"- Earth Objects: {len(earth_objects)} evidence-backed object(s)",
        "",
    ]
    if monitoring_context is not None:
        lines.extend([
            "## Continuous observation context",
            "",
            f"- Monitoring runs linked to this investigation: {len(monitoring_context['runs'])}",
            f"- Schedule revisions available: {len(monitoring_context['schedule_definitions'])}",
            f"- Lifecycle events: {len(monitoring_context['events'])}",
            f"- Notifications: {len(monitoring_context['notifications'])}",
        ])
        for revision_id in monitoring_context["missing_schedule_revision_ids"]:
            lines.append(f"- Missing schedule revision record: `{revision_id}`")
        lines.extend([
            "",
            "These records describe monitoring execution and do not add scientific findings.",
        ])
    trigger_contexts = tuple(
        task.get("parameters", {}).get("monitoring_trigger")
        for task in investigation.get("tasks", ())
        if isinstance(task.get("parameters", {}).get("monitoring_trigger"), dict)
    )
    if trigger_contexts:
        lines.extend(["", "## Monitoring-trigger lineage", ""])
        for trigger in trigger_contexts:
            lines.append(
                f"- Policy `{trigger.get('policy_id', 'unknown')}` on schedule "
                f"`{trigger.get('schedule_id', 'unknown')}` revision "
                f"`{trigger.get('schedule_revision', 'unknown')}`; diagnostic "
                f"`{trigger.get('diagnostic_id', 'unknown')}`; source observations: "
                f"{', '.join(trigger.get('source_observation_ids', ())) or 'unknown'}; "
                f"comparison `{trigger.get('comparison_sha256', 'unknown')}`. "
                "The trigger is an operator-authored operational rule over a "
                "descriptive difference, not a scientific significance claim."
            )
    if comparison_artifacts:
        lines.extend([
            "", "## Linked cross-investigation comparisons", "",
            f"{len(comparison_artifacts)} comparison artifact(s) link this investigation to other recorded investigations.",
            "",
        ])
        for artifact in comparison_artifacts:
            lines.append(
                f"- `{artifact['artifact_id']}` ({artifact['artifact_type']}); "
                f"digest `{artifact['payload_sha256']}`; related investigations "
                f"{', '.join(f'`{item}`' for item in artifact['investigation_ids']) or 'not recorded'}; "
                f"measurement groups: {artifact['measurement_group_count']}; "
                f"descriptive temporal diagnostics: {artifact['temporal_diagnostic_count']}; "
                f"alignment blockers: {artifact['alignment_issue_count'] + artifact['temporal_issue_count']}."
            )
        lines.extend([
            "",
            "These linked comparisons remain separate, descriptive records; this report does not reinterpret them.",
        ])
    lines.extend(["", "## Observation inventory", ""])
    if not observations:
        lines.append("No observation records are attached to the available executions.")
    else:
        for item in observations:
            dataset = (
                f"{item.dataset.connector_id}/{item.dataset.dataset_id}"
                if item.dataset else "dataset unknown"
            )
            variables = ", ".join(sorted(item.measured_variables)) or "variables unknown"
            lines.append(
                f"- `{item.observation_id}` — {dataset}; time: "
                f"{item.observed_at.isoformat() if item.observed_at else 'unknown'}; "
                f"variables: {variables}; uncertainty metadata: "
                f"{'present' if item.uncertainty else 'not supplied'}"
            )
            for measurement in item.canonical_measurements:
                lines.append(
                    f"  - Canonical measurement `{measurement.canonical_variable}`: "
                    f"value `{_json_value(measurement.value)}`; unit "
                    f"`{measurement.unit or 'unknown'}`; semantic status "
                    f"`{measurement.semantic_status}`; source variable "
                    f"`{measurement.source_variable}` (`{measurement.source_unit or 'unit unknown'}`)"
                )
    lines.extend(["", "## Spatial-temporal observation stacks", ""])
    if observation_stacks:
        for stack in observation_stacks:
            lines.append(
                f"- `{stack.stack_id}`; variable `{stack.canonical_variable or stack.variable_key}`; "
                f"unit `{stack.unit}`; {len(stack.members)} source-time samples; "
                f"{stack.spatial_alignment.replace('_', ' ')} in "
                f"`{stack.spatial_support_crs}`; no resampling or temporal interpolation"
            )
            for member in stack.members:
                lines.append(
                    f"  - `{member.observation_id}` at {member.observed_at.isoformat()}: "
                    f"{_json_value(member.value)} `{member.unit}`"
                )
    else:
        lines.append("No exact-support temporal observation stacks are available.")
    lines.extend(["", "## Consecutive temporal differences", ""])
    if temporal_differences:
        for item in temporal_differences:
            lines.append(
                f"- `{item.canonical_variable or item.variable_key}`: "
                f"{_json_value(item.earlier.value)} to {_json_value(item.later.value)} "
                f"`{item.unit}`; later-minus-earlier difference "
                f"`{_json_value(item.difference_value)} {item.unit}` over "
                f"{item.elapsed_seconds:g} seconds; observations "
                f"`{item.earlier.observation_id}` -> `{item.later.observation_id}`. "
                "Descriptive only; uncertainty not propagated; no trend or causal inference."
            )
    else:
        lines.append("No eligible same-dataset consecutive sample differences are available.")
    if temporal_difference_issues:
        lines.append("")
        lines.append("Difference eligibility issues:")
        lines.extend(
            f"- Stack `{item.stack_id}` ({item.code}): {item.message}; "
            f"members `{item.earlier_observation_id}` -> `{item.later_observation_id}`"
            for item in temporal_difference_issues
        )
    if alignment_issues:
        lines.extend(["", "Alignment blockers:"])
        lines.extend(
            f"- `{item.observation_id}` ({item.code}): {item.message}"
            for item in alignment_issues
        )
    lines.extend(["", "## Declared evidence coverage", ""])
    if assessment and assessment.requirements:
        lines.extend(
            f"- `{item.requirement_id}` - {item.status}: {item.explanation}; "
            f"observation references: {', '.join(item.observation_ids) or 'none'}"
            for item in assessment.requirements
        )
    else:
        lines.append("No evidence coverage assessment is available.")
    lines.extend(["", "## Earth Objects", ""])
    if earth_objects:
        lines.extend(
            f"- `{item.object_id}` — `{item.object_type}`, identity: "
            f"{item.stable_identity or 'unknown'}; observations: "
            f"{', '.join(item.source_observation_ids)}; lifecycle: `{item.lifecycle}`; "
            f"geometry: {'present' if item.geometry else 'unknown'}; temporal validity: "
            f"{'present' if item.temporal_validity else 'unknown'}; evidence: "
            f"{', '.join(item.evidence_ids) or 'none'}"
            for item in earth_objects
        )
        for item in earth_objects:
            declaration = item.provenance.get("declaration", {})
            declared_provenance = (
                declaration.get("declared_provenance", {})
                if isinstance(declaration, dict)
                else {}
            )
            extraction = (
                declared_provenance.get("extraction_pipeline", {})
                if isinstance(declared_provenance, dict)
                else {}
            )
            if isinstance(extraction, dict) and extraction:
                method_identities = extraction.get("method_identities", ())
                method_identity = extraction.get("method_identity") or (
                    ", ".join(method_identities)
                    if method_identities
                    else "unknown"
                )
                lines.append(
                    f"  - Extraction `{extraction.get('pipeline_id', 'unknown')}` "
                    f"v`{extraction.get('pipeline_version', 'unknown')}`; "
                    f"method `{method_identity}`; "
                    f"status `{extraction.get('validation_status', 'unknown')}`; "
                    f"uncertainty `{extraction.get('extraction_uncertainty', 'unknown')}`"
                )
                for limitation in extraction.get("limitations", ()):
                    lines.append(f"    - Limitation: {limitation}")
            for measurement in item.measurements:
                lines.append(
                    f"  - Measurement `{measurement.canonical_variable}`: "
                    f"value `{_json_value(measurement.value)}`; unit "
                    f"`{measurement.unit or 'unknown'}`; source observation "
                    f"`{measurement.observation_id or 'unknown'}`"
                )
            for assertion in item.property_assertions:
                lines.append(
                    f"  - Property assertion `{assertion.property_id}`: "
                    f"`{_json_value(assertion.value)}`; observations: "
                    f"{', '.join(assertion.observation_ids) or 'none'}"
                )
            for attribute in item.source_attributes:
                lines.append(
                    f"  - Unmapped source attribute `{attribute.source_key}`: "
                    f"`{_json_value(attribute.value)}`; observation "
                    f"`{attribute.source_observation_id}`; dataset "
                    f"`{attribute.source_dataset.dataset_id if attribute.source_dataset else 'unknown'}`; "
                    "no canonical semantic mapping asserted"
                )
    else:
        lines.append("No Earth Objects are linked to the available investigation evidence.")
    lines.extend(["", "## Scientific assessment", ""])
    if reasoning is None:
        lines.append(
            "No scientific reasoning report is available. This report does not infer a conclusion from the observations."
        )
    else:
        lines.append(f"**Reasoning status:** {reasoning.status}")
        lines.append("")
        lines.append(reasoning.conclusion.explanation)
        lines.append("")
        lines.append("Conclusion confidence: not supplied")
        lines.append(
            f"Uncertainty inventory: {reasoning.uncertainty_budget.statement}"
        )
        if reasoning.findings:
            lines.extend(["", "Recorded findings:"])
            for finding in reasoning.findings:
                lines.append(
                    f"- {finding.statement} (rule `{finding.rule_id}@{finding.rule_version}`; "
                    f"observations: {', '.join(finding.observation_ids)})"
                )
        if reasoning.conclusion.supporting_evidence:
            lines.extend(["", "Supporting evidence records:"])
            lines.extend(
                f"- `{item.rule_id}@{item.rule_version}`: {item.statement}; "
                f"observations: {', '.join(item.observation_ids)}"
                for item in reasoning.conclusion.supporting_evidence
            )
        if reasoning.conclusion.contradicting_evidence:
            lines.extend(["", "Contradicting evidence records:"])
            lines.extend(
                f"- `{item.rule_id}@{item.rule_version}`: {item.statement}; "
                f"observations: {', '.join(item.observation_ids)}"
                for item in reasoning.conclusion.contradicting_evidence
            )
        if reasoning.conclusion.unresolved_evidence:
            lines.extend(["", "Unresolved evidence records:"])
            lines.extend(
                f"- `{item.rule_id}@{item.rule_version}`: {item.statement}; "
                f"observations: {', '.join(item.observation_ids)}"
                for item in reasoning.conclusion.unresolved_evidence
            )
        if reasoning.conclusion.missing_evidence_details:
            lines.extend(["", "Missing evidence:"])
            lines.extend(
                f"- `{item.requirement_id}` ({item.status}; {item.evidence_type}): {item.explanation}"
                for item in reasoning.conclusion.missing_evidence_details
            )
        if reasoning.conclusion.competing_hypothesis_statements:
            lines.extend(["", "Competing explanations still represented:"])
            lines.extend(
                f"- {statement}"
                for statement in reasoning.conclusion.competing_hypothesis_statements
            )
    lines.extend(["", "## Provenance records", ""])
    if observations:
        for item in observations:
            dataset = (
                f"{item.dataset.connector_id}/{item.dataset.dataset_id}@{item.dataset.version or 'unknown'}"
                if item.dataset else "unknown"
            )
            provenance = json.dumps(
                item.provenance, sort_keys=True, ensure_ascii=False, default=str
            )
            lines.append(
                f"- Observation `{item.observation_id}`; source `{item.source_id or 'unknown'}`; "
                f"dataset `{dataset}`; declared provenance: `{provenance}`"
            )
    else:
        lines.append("No observation provenance records are available.")
    lines.extend(["", "## Execution trace", ""])
    if executions:
        for execution in executions:
            lines.append(
                f"- Execution `{execution.plan_id}`: `{execution.status}`; "
                f"started {execution.started_at.isoformat() if execution.started_at else 'unknown'}; "
                f"finished {execution.finished_at.isoformat() if execution.finished_at else 'unknown'}"
            )
            for task in execution.tasks:
                lines.append(
                    f"  - Task `{task.task_id}` (`{task.status}`), attempts: {task.attempts}; "
                    f"error: {task.error or 'none'}"
                )
    else:
        lines.append("No execution records are available.")
    missing_artifacts = tuple(
        artifact_id
        for artifact_id, available in (
            (investigation.get("investigation_plan_id"), plan is not None),
            (investigation.get("investigation_design_id"), design is not None),
        )
        if artifact_id and not available
    )
    if missing_artifacts:
        lines.extend(["", "Unavailable artifact references:", ""])
        lines.extend(f"- `{item}`" for item in missing_artifacts)
    if limitations:
        lines.extend(["", "## Limitations and unknowns", ""])
        lines.extend(f"- {item}" for item in limitations)
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"Source records digest: `{source_digest}`",
        f"Execution references: {', '.join(investigation['result_ids']) or 'none'}",
        f"Unavailable execution references: {', '.join(unavailable) or 'none'}",
        "",
        "This report is a deterministic rendering of recorded platform artifacts. It adds no measurements, confidence, uncertainty, or scientific inference.",
    ])
    return "\n".join(lines)


def _json_value(value: Any) -> str:
    """Render the recorded value without converting or interpreting it."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
