"""Deterministic, provider-neutral scientific reasoning primitives.

The default operators describe evidence structure and acquisition conflicts.
They do not turn data coverage into scientific support. Domain inference must
be supplied as a versioned rule with explicit applicability and traceable input.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from math import isfinite
from typing import Callable, Iterable, Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from .contracts import Contract, EarthObject, Observation
from .intelligence import EvidenceAssessment, InvestigationDesign
from .planning import CandidateHypothesis
from .scientific_inference import (
    AlternativeExplanationEngine,
    AlternativeExplanationSet,
    EvidenceEvaluationEngine,
    EvidenceEvaluationReport,
    HypothesisGraph,
    HypothesisLifecycleEvent,
    InvestigationRefinementEngine,
    RefinementRecommendation,
    UncertaintyBudget,
    UncertaintyBudgetEngine,
    UncertaintyComponent,
    hypothesis_graph_from_candidates,
)
from .scientific_methods import (
    CalibratedEvidenceWeight,
    ScientificRuleManifest,
    ScientificUncertainty,
)

REASONING_ENGINE_ID = "satquery.deterministic-scientific-reasoning"
REASONING_ENGINE_VERSION = "0.2.0"


def _stable_finding_id(
    rule_id: str,
    rule_version: str,
    hypothesis: str,
    observation_ids: tuple[str, ...],
    statement: str,
) -> str:
    payload = json.dumps(
        [rule_id, rule_version, hypothesis, sorted(observation_ids), statement],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class OperatorResult(Contract):
    operator_id: str = Field(min_length=1)
    operator_version: str = Field(min_length=1)
    status: Literal[
        "evaluated", "insufficient_evidence", "not_applicable", "incompatible", "error"
    ]
    statement: str
    observation_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()
    provenance: dict[str, object] = Field(default_factory=dict)
    diagnostics: dict[str, object] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()


class MeasurementAgreementCriterion(Contract):
    criterion_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    canonical_variable: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    absolute_tolerance: float = Field(ge=0)
    relative_tolerance: float = Field(default=0, ge=0)
    rationale: str = Field(min_length=1)
    reference_ids: tuple[str, ...] = ()


class HypothesisEvaluation(Contract):
    hypothesis: CandidateHypothesis
    status: Literal["not_evaluated", "insufficient_evidence", "evaluated"] = (
        "not_evaluated"
    )
    supporting_observation_ids: tuple[str, ...] = ()
    contradicting_observation_ids: tuple[str, ...] = ()
    unresolved_observation_ids: tuple[str, ...] = ()
    missing_requirement_ids: tuple[str, ...] = ()
    explanation: str
    rule_ids: tuple[str, ...] = ()
    uncertainty: ScientificUncertainty = Field(
        default_factory=lambda: ScientificUncertainty(
            status="not_quantified",
            reason="No calibrated uncertainty method was registered.",
        )
    )


class ScientificFinding(Contract):
    finding_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    hypothesis_statement: str = Field(min_length=1)
    evidential_relation: Literal[
        "supports", "contradicts", "contextual", "inconclusive"
    ] = "contextual"
    observation_ids: tuple[str, ...] = Field(min_length=1)
    provenance: dict[str, object] = Field(default_factory=dict)
    observation_provenance: dict[str, object] = Field(default_factory=dict)
    observation_uncertainty: dict[str, object] = Field(default_factory=dict)
    supporting_observation_ids: tuple[str, ...] = ()
    contradicting_observation_ids: tuple[str, ...] = ()
    unresolved_observation_ids: tuple[str, ...] = ()
    uncertainty: ScientificUncertainty = Field(
        default_factory=lambda: ScientificUncertainty(
            status="not_quantified", reason="No uncertainty method was supplied."
        )
    )
    evidence_weight: CalibratedEvidenceWeight = Field(
        default_factory=CalibratedEvidenceWeight
    )
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class EvidenceGap(Contract):
    requirement_id: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    target: str = Field(min_length=1)
    status: Literal["missing", "partial", "indeterminate"]
    explanation: str


class ScientificConclusion(Contract):
    status: Literal["unresolved", "findings_available"] = "unresolved"
    findings: tuple[ScientificFinding, ...] = ()
    explanation: str
    missing_evidence: tuple[str, ...] = ()
    missing_evidence_details: tuple[EvidenceGap, ...] = ()
    additional_observation_targets: tuple[str, ...] = ()
    competing_hypothesis_statements: tuple[str, ...] = ()
    supporting_evidence: tuple["EvidenceTraceItem", ...] = ()
    contradicting_evidence: tuple["EvidenceTraceItem", ...] = ()
    unresolved_evidence: tuple["EvidenceTraceItem", ...] = ()
    reasoning_trace: tuple["ReasoningTraceStep", ...] = ()
    confidence: None = None
    uncertainty: dict[str, object] = Field(default_factory=dict)


class ScientificReasoningReport(Contract):
    reasoning_id: str = Field(min_length=1)
    investigation_id: str = Field(min_length=1)
    engine_id: str = REASONING_ENGINE_ID
    engine_version: str = REASONING_ENGINE_VERSION
    status: Literal["evaluated", "insufficient_evidence", "not_evaluable"]
    hypothesis_evaluations: tuple[HypothesisEvaluation, ...] = ()
    hypothesis_graph: HypothesisGraph = Field(default_factory=HypothesisGraph)
    hypothesis_lifecycle_events: tuple[HypothesisLifecycleEvent, ...] = ()
    alternative_explanations: tuple[AlternativeExplanationSet, ...] = ()
    evidence_evaluation: EvidenceEvaluationReport = Field(
        default_factory=lambda: EvidenceEvaluationReport(
            statement="Evidence evaluation was not performed.",
            declared_source_count=0,
            independence_assessed_count=0,
        )
    )
    uncertainty_budget: UncertaintyBudget = Field(
        default_factory=lambda: UncertaintyBudget(
            statement="Uncertainty inventory was not performed."
        )
    )
    refinement_recommendations: tuple[RefinementRecommendation, ...] = ()
    operator_results: tuple[OperatorResult, ...] = ()
    findings: tuple[ScientificFinding, ...] = ()
    rule_applicability: tuple["RuleApplicabilityOutcome", ...] = ()
    rule_evaluations: tuple["ScientificRuleResult", ...] = ()
    reasoning_trace: tuple["ReasoningTraceStep", ...] = ()
    sufficiency: "EvidenceSufficiencyAssessment"
    conclusion: ScientificConclusion
    observation_ids: tuple[str, ...] = ()
    reproducibility: dict[str, object] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()


class ReasoningContext(Contract):
    investigation_id: str = Field(min_length=1)
    observations: tuple[Observation, ...] = ()
    earth_objects: tuple[EarthObject, ...] = ()
    design: InvestigationDesign
    assessment: EvidenceAssessment
    hypothesis_graph: HypothesisGraph | None = None
    hypothesis_lifecycle_events: tuple[HypothesisLifecycleEvent, ...] = ()
    evidence_evaluation: EvidenceEvaluationReport | None = None

    @model_validator(mode="after")
    def assessment_matches_design_and_observations(self) -> "ReasoningContext":
        if self.assessment.design_id != self.design.design_id:
            raise ValueError(
                "evidence assessment must refer to the supplied investigation design"
            )
        observation_ids = {item.observation_id for item in self.observations}
        if len(observation_ids) != len(self.observations):
            raise ValueError("reasoning context observation identifiers must be unique")
        if not set(self.assessment.observation_ids).issubset(observation_ids):
            raise ValueError(
                "evidence assessment references observations absent from reasoning context"
            )
        for item in self.earth_objects:
            if item.investigation_id not in {None, self.investigation_id}:
                raise ValueError("reasoning context contains an Earth Object from another investigation")
            if not set(item.source_observation_ids).issubset(observation_ids):
                raise ValueError("reasoning context Earth Object references unavailable observations")
        return self


class ScientificRuleResult(Contract):
    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    hypothesis_statement: str = Field(min_length=1)
    status: Literal["evaluated", "insufficient_evidence", "not_applicable", "error"]
    statement: str
    evidential_relation: Literal[
        "supports", "contradicts", "contextual", "inconclusive"
    ] = "contextual"
    observation_ids: tuple[str, ...] = ()
    missing_requirement_ids: tuple[str, ...] = ()
    uncertainty: ScientificUncertainty = Field(
        default_factory=lambda: ScientificUncertainty(
            status="not_quantified", reason="No uncertainty method was supplied."
        )
    )
    evidence_weight: CalibratedEvidenceWeight = Field(
        default_factory=CalibratedEvidenceWeight
    )
    parameters: dict[str, object] = Field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class EvidenceTraceItem(Contract):
    disposition: Literal["supports", "contradicts", "unresolved"]
    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    statement: str
    observation_ids: tuple[str, ...] = Field(min_length=1)
    provenance: dict[str, object] = Field(default_factory=dict)
    uncertainty: ScientificUncertainty
    evidence_weight: CalibratedEvidenceWeight = Field(
        default_factory=CalibratedEvidenceWeight
    )


class ReasoningTraceStep(Contract):
    sequence: int = Field(ge=0)
    stage: Literal[
        "operator",
        "applicability",
        "rule",
        "evidence_evaluation",
        "alternative",
        "uncertainty",
        "refinement",
        "conclusion",
    ]
    component_id: str = Field(min_length=1)
    component_version: str = Field(min_length=1)
    status: str
    input_observation_ids: tuple[str, ...] = ()
    output_finding_ids: tuple[str, ...] = ()
    explanation: str
    parameters: dict[str, object] = Field(default_factory=dict)


class RuleApplicabilityOutcome(Contract):
    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    hypothesis_statement: str = Field(min_length=1)
    status: Literal[
        "applicable", "insufficient_evidence", "incompatible", "unvalidated"
    ]
    reasons: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()


class EvidenceSufficiencyAssessment(Contract):
    status: Literal["method_inputs_satisfied", "insufficient", "not_assessable"]
    explanation: str
    applicable_validated_rule_ids: tuple[str, ...] = ()
    unmet_preconditions: tuple[str, ...] = ()


ScientificConclusion.model_rebuild()
ScientificReasoningReport.model_rebuild()


@runtime_checkable
class ScientificOperator(Protocol):
    operator_id: str
    version: str

    def evaluate(self, context: ReasoningContext) -> OperatorResult: ...


@runtime_checkable
class ScientificRule(Protocol):
    manifest: ScientificRuleManifest

    def evaluate(
        self, hypothesis: CandidateHypothesis, context: ReasoningContext
    ) -> ScientificRuleResult: ...


@runtime_checkable
class UncertaintyPropagationMethod(Protocol):
    method_id: str
    version: str

    def propagate(
        self, result: ScientificRuleResult, context: ReasoningContext
    ) -> ScientificUncertainty: ...


class UncertaintyMethodRegistry:
    def __init__(self, methods: Iterable[UncertaintyPropagationMethod] = ()) -> None:
        self._methods: dict[tuple[str, str], UncertaintyPropagationMethod] = {}
        for method in methods:
            self.register(method)

    def register(self, method: UncertaintyPropagationMethod) -> None:
        key = (method.method_id, method.version)
        if not all(part.strip() for part in key):
            raise ValueError("uncertainty methods require stable IDs and versions")
        if key in self._methods:
            raise ValueError(
                f"uncertainty method already registered: {key[0]}@{key[1]}"
            )
        self._methods[key] = method

    def get(self, method_id: str, version: str) -> UncertaintyPropagationMethod | None:
        return self._methods.get((method_id, version))

    def versions(self) -> dict[str, str]:
        return {method_id: version for method_id, version in sorted(self._methods)}


class OperatorRegistry:
    """Replaceable registry; duplicate IDs fail instead of silently shadowing."""

    def __init__(self, operators: Iterable[ScientificOperator] = ()) -> None:
        self._operators: dict[str, ScientificOperator] = {}
        for operator in operators:
            self.register(operator)

    def register(self, operator: ScientificOperator) -> None:
        if not operator.operator_id.strip() or not operator.version.strip():
            raise ValueError("scientific operators require stable IDs and versions")
        if operator.operator_id in self._operators:
            raise ValueError(
                f"scientific operator already registered: {operator.operator_id}"
            )
        self._operators[operator.operator_id] = operator

    def all(self) -> tuple[ScientificOperator, ...]:
        return tuple(self._operators[key] for key in sorted(self._operators))


class RuleRegistry:
    def __init__(self, rules: Iterable[ScientificRule] = ()) -> None:
        self._rules: dict[tuple[str, str], ScientificRule] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: ScientificRule) -> None:
        manifest = rule.manifest
        key = (manifest.rule_id, manifest.version)
        if key in self._rules:
            raise ValueError(
                f"scientific rule already registered: {manifest.rule_id}@{manifest.version}"
            )
        self._rules[key] = rule

    def all(self) -> tuple[ScientificRule, ...]:
        return tuple(self._rules[key] for key in sorted(self._rules))

    def validated(self) -> tuple[ScientificRule, ...]:
        return tuple(
            rule
            for rule in self.all()
            if rule.manifest.validation_status == "validated"
        )


class RuleApplicabilityEvaluator:
    """Check declared method preconditions without interpreting provider data."""

    def evaluate(
        self,
        manifest: ScientificRuleManifest,
        hypothesis: CandidateHypothesis,
        context: ReasoningContext,
    ) -> RuleApplicabilityOutcome:
        reasons: list[str] = []
        incompatibilities: list[str] = []
        spec = manifest.applicability
        if manifest.validation_status != "validated":
            return RuleApplicabilityOutcome(
                rule_id=manifest.rule_id,
                rule_version=manifest.version,
                hypothesis_statement=hypothesis.statement,
                status="unvalidated",
                reasons=(
                    f"Rule validation status is {manifest.validation_status!r}; it cannot contribute to a scientific conclusion.",
                ),
            )
        observations = context.observations
        if len(observations) < spec.minimum_observations:
            reasons.append(
                f"Requires at least {spec.minimum_observations} observations; received {len(observations)}."
            )
        available_variables = {
            item.canonical_variable
            for observation in observations
            for item in observation.canonical_measurements
            if item.semantic_status == "resolved"
        }
        missing_variables = set(spec.required_variables).difference(available_variables)
        if missing_variables:
            reasons.append(
                f"Required resolved variables are missing: {sorted(missing_variables)}."
            )
        modalities = {modality for item in observations for modality in item.modalities}
        missing_modalities = set(spec.required_modalities).difference(modalities)
        if missing_modalities:
            reasons.append(
                f"Required observation modalities are missing: {sorted(missing_modalities)}."
            )
        for requirement in manifest.required_evidence:
            if requirement.evidence_type == "variable":
                count = sum(
                    any(
                        measurement.canonical_variable == requirement.target
                        and measurement.semantic_status == "resolved"
                        for measurement in observation.canonical_measurements
                    )
                    for observation in observations
                )
            elif requirement.evidence_type == "modality":
                count = sum(
                    requirement.target in item.modalities for item in observations
                )
            elif requirement.evidence_type == "temporal_support":
                count = sum(
                    item.observed_at is not None
                    or (
                        item.temporal_extent is not None
                        and item.temporal_extent.start is not None
                        and item.temporal_extent.end is not None
                    )
                    for item in observations
                )
            elif requirement.evidence_type == "spatial_support":
                count = sum(
                    (item.geometry is not None or item.bbox is not None)
                    and item.crs is not None
                    for item in observations
                )
            else:
                count = sum(
                    item.dataset is not None
                    and requirement.target in item.dataset.metadata
                    for item in observations
                )
            if count < requirement.minimum_observations:
                reasons.append(
                    f"Required evidence {requirement.requirement_id!r} ({requirement.evidence_type}:{requirement.target}) is present in {count} observations; requires {requirement.minimum_observations}."
                )
        if spec.require_temporal_support and any(
            not (
                item.observed_at is not None
                or (
                    item.temporal_extent is not None
                    and item.temporal_extent.start is not None
                    and item.temporal_extent.end is not None
                )
            )
            for item in observations
        ):
            reasons.append(
                "Complete temporal support is required for each observation."
            )
        if spec.require_spatial_support and any(
            (item.geometry is None and item.bbox is None) or item.crs is None
            for item in observations
        ):
            reasons.append(
                "Spatial support and a declared CRS are required for each observation."
            )
        compatibility = manifest.dataset_compatibility
        evidence_by_id = {
            item.observation_id: item
            for item in (context.evidence_evaluation.units if context.evidence_evaluation else ())
        }
        for observation in observations:
            metadata = observation.dataset.metadata if observation.dataset else {}
            if spec.require_declared_dataset_metadata and not metadata:
                reasons.append(
                    f"Observation {observation.observation_id} lacks declared dataset metadata."
                )
                continue
            declared_variables = set(metadata.get("variables", ()))
            declared_modalities = set(metadata.get("modalities", ()))
            if compatibility.required_variables and not set(
                compatibility.required_variables
            ).issubset(declared_variables):
                target = incompatibilities if declared_variables else reasons
                target.append(
                    f"Dataset metadata for observation {observation.observation_id} does not declare all required variables."
                )
            if compatibility.required_modalities and not set(
                compatibility.required_modalities
            ).issubset(declared_modalities):
                target = incompatibilities if declared_modalities else reasons
                target.append(
                    f"Dataset metadata for observation {observation.observation_id} does not declare all required modalities."
                )
            if (
                compatibility.allowed_crs
                and observation.crs not in compatibility.allowed_crs
            ):
                target = reasons if observation.crs is None else incompatibilities
                target.append(
                    f"Observation {observation.observation_id} CRS is outside the rule's declared compatibility set."
                )
            for key, expected in compatibility.required_metadata.items():
                if metadata.get(key) != expected:
                    target = reasons if key not in metadata else incompatibilities
                    target.append(
                        f"Dataset metadata key {key!r} does not meet the rule compatibility declaration."
                    )
            if compatibility.required_trust_scope_ids:
                evidence = evidence_by_id.get(observation.observation_id)
                trusted_scopes = set(evidence.trusted_scope_ids) if evidence else set()
                missing_scopes = set(compatibility.required_trust_scope_ids).difference(
                    trusted_scopes
                )
                if missing_scopes:
                    target = (
                        incompatibilities
                        if evidence and evidence.dataset_trust == "rejected"
                        else reasons
                    )
                    target.append(
                        f"Observation {observation.observation_id} lacks acceptable dataset trust for scopes {sorted(missing_scopes)}."
                    )
        quality = manifest.required_quality
        for observation in observations:
            assessment = observation.quality_assessment
            if quality.require_validated_observation and (
                assessment is None or assessment.validation_status != "valid"
            ):
                target = (
                    reasons
                    if assessment is None
                    or assessment.validation_status == "not_assessed"
                    else incompatibilities
                )
                target.append(
                    f"Observation {observation.observation_id} lacks required valid quality assessment."
                )
            if quality.minimum_quality_score is not None:
                if assessment is None or assessment.quality_score is None:
                    reasons.append(
                        f"Observation {observation.observation_id} quality score is unknown."
                    )
                elif assessment.quality_score < quality.minimum_quality_score:
                    incompatibilities.append(
                        f"Observation {observation.observation_id} quality score is below the rule threshold."
                    )
            if quality.minimum_completeness is not None:
                if assessment is None or assessment.completeness is None:
                    reasons.append(
                        f"Observation {observation.observation_id} completeness is unknown."
                    )
                elif assessment.completeness < quality.minimum_completeness:
                    incompatibilities.append(
                        f"Observation {observation.observation_id} completeness is below the rule threshold."
                    )
        all_reasons = tuple(dict.fromkeys((*reasons, *incompatibilities)))
        return RuleApplicabilityOutcome(
            rule_id=manifest.rule_id,
            rule_version=manifest.version,
            hypothesis_statement=hypothesis.statement,
            status=(
                "incompatible"
                if incompatibilities
                else "insufficient_evidence"
                if reasons
                else "applicable"
            ),
            reasons=all_reasons,
            missing_evidence=tuple(dict.fromkeys(reasons)),
        )


class EvidenceCompletenessOperator:
    operator_id = "satquery.evidence-completeness"
    version = "1.0.0"

    def evaluate(self, context: ReasoningContext) -> OperatorResult:
        missing = tuple(
            item.requirement_id
            for item in context.assessment.requirements
            if item.status == "missing"
        )
        partial = tuple(
            item.requirement_id
            for item in context.assessment.requirements
            if item.status in {"partial", "indeterminate"}
        )
        if not context.assessment.requirements:
            status = "not_applicable"
            statement = "No explicit evidence requirements are available to assess completeness."
        elif missing or partial:
            status = "insufficient_evidence"
            statement = "Declared evidence requirements are missing, partial, or indeterminate; this is coverage status only."
        else:
            status = "evaluated"
            statement = "All declared evidence requirements are represented in the coverage assessment; scientific sufficiency is not implied."
        return OperatorResult(
            operator_id=self.operator_id,
            operator_version=self.version,
            status=status,
            statement=statement,
            observation_ids=context.assessment.observation_ids,
            requirement_ids=tuple(
                item.requirement_id for item in context.assessment.requirements
            ),
            provenance={
                "assessment_id": context.assessment.assessment_id,
                "design_id": context.design.design_id,
            },
            limitations=(
                "Requirement coverage does not establish measurement validity, hypothesis support, or scientific sufficiency.",
            ),
        )


class MissingEvidenceOperator:
    operator_id = "satquery.missing-evidence"
    version = "1.0.0"

    def evaluate(self, context: ReasoningContext) -> OperatorResult:
        missing = tuple(
            item.requirement_id
            for item in context.assessment.requirements
            if item.status in {"missing", "partial", "indeterminate"}
        )
        return OperatorResult(
            operator_id=self.operator_id,
            operator_version=self.version,
            status="insufficient_evidence"
            if missing
            else ("evaluated" if context.assessment.requirements else "not_applicable"),
            statement=(
                "Some declared requirements remain missing, partial, or indeterminate."
                if missing
                else "No declared requirement is reported missing; this does not establish scientific sufficiency."
                if context.assessment.requirements
                else "No declared evidence requirements are available."
            ),
            observation_ids=context.assessment.observation_ids,
            requirement_ids=missing,
            provenance={"assessment_id": context.assessment.assessment_id},
            limitations=(
                "This operator can identify only gaps represented in the investigation design and coverage assessment.",
            ),
        )


class ObservationConflictOperator:
    operator_id = "satquery.observation-conflicts"
    version = "1.0.0"

    def evaluate(self, context: ReasoningContext) -> OperatorResult:
        conflicts = context.assessment.reported_conflicts
        referenced = tuple(
            sorted(
                {
                    str(value)
                    for conflict in conflicts
                    for key, value in conflict.items()
                    if key
                    in {
                        "observation_id",
                        "first_observation_id",
                        "second_observation_id",
                    }
                    and value
                }
            )
        )
        return OperatorResult(
            operator_id=self.operator_id,
            operator_version=self.version,
            status="evaluated" if conflicts else "not_applicable",
            statement=(
                f"{len(conflicts)} conflict record(s) were reported by the upstream observation/fusion layer; no independent scientific interpretation was performed."
                if conflicts
                else "No upstream conflict records were supplied."
            ),
            observation_ids=referenced,
            provenance={
                "assessment_id": context.assessment.assessment_id,
                "reported_conflict_count": len(conflicts),
            },
            limitations=(
                "Conflict records are passed through as reported; comparability and scientific significance are not independently established.",
            ),
        )


class MeasurementCompatibilityOperator:
    """Find exact declared semantic/unit matches, without interpreting values."""

    operator_id = "satquery.measurement-compatibility"
    version = "1.0.0"

    def evaluate(self, context: ReasoningContext) -> OperatorResult:
        groups: dict[tuple[str, str], list[str]] = {}
        unresolved = 0
        for observation in context.observations:
            for measurement in observation.canonical_measurements:
                if (
                    measurement.semantic_status == "resolved"
                    and measurement.unit is not None
                    and measurement.unit.strip()
                ):
                    groups.setdefault(
                        (measurement.canonical_variable, measurement.unit), []
                    ).append(observation.observation_id)
                else:
                    unresolved += 1
        comparable = [
            {
                "variable": variable,
                "declared_unit": unit,
                "observation_ids": sorted(set(observation_ids)),
            }
            for (variable, unit), observation_ids in sorted(groups.items())
            if len(set(observation_ids)) > 1
        ]
        return OperatorResult(
            operator_id=self.operator_id,
            operator_version=self.version,
            status="evaluated"
            if comparable
            else ("insufficient_evidence" if unresolved else "not_applicable"),
            statement=(
                "Exact canonical variable and declared-unit groups are available for downstream analysis; this check does not establish spatial or temporal comparability."
                if comparable
                else "No multi-observation group has both a resolved variable and an explicit matching unit."
            ),
            observation_ids=context.assessment.observation_ids,
            provenance={"design_id": context.design.design_id},
            diagnostics={
                "comparable_groups": comparable,
                "unresolved_measurement_count": unresolved,
            },
            limitations=(
                "Unit strings are compared exactly; no aliases or conversions are assumed.",
                "Matching names and units do not establish compatible support, calibration, sampling, or measurement method.",
            ),
        )


class TemporalAlignmentOperator:
    """Report pairwise interval overlap only when explicit time support exists."""

    operator_id = "satquery.temporal-alignment"
    version = "1.0.0"

    @staticmethod
    def _interval(observation: Observation) -> tuple[datetime, datetime] | None:
        extent = observation.temporal_extent
        if extent is not None and extent.start is not None and extent.end is not None:
            if extent.start.tzinfo is not None and extent.end.tzinfo is not None:
                return extent.start, extent.end
        instant = observation.observed_at
        if instant is not None and instant.tzinfo is not None:
            return instant, instant
        return None

    def evaluate(self, context: ReasoningContext) -> OperatorResult:
        observations = sorted(
            context.observations, key=lambda item: item.observation_id
        )
        intervals = {item.observation_id: self._interval(item) for item in observations}
        pairs = []
        for index, first in enumerate(observations):
            first_interval = intervals[first.observation_id]
            for second in observations[index + 1 :]:
                second_interval = intervals[second.observation_id]
                if first_interval is None or second_interval is None:
                    continue
                pairs.append(
                    {
                        "first_observation_id": first.observation_id,
                        "second_observation_id": second.observation_id,
                        "intervals_overlap": max(first_interval[0], second_interval[0])
                        <= min(first_interval[1], second_interval[1]),
                    }
                )
        known_count = sum(interval is not None for interval in intervals.values())
        return OperatorResult(
            operator_id=self.operator_id,
            operator_version=self.version,
            status=(
                "not_applicable"
                if len(observations) < 2
                else "insufficient_evidence"
                if known_count < len(observations) or not pairs
                else "evaluated"
            ),
            statement=(
                "Pairwise overlap was evaluated from explicit timestamps or complete temporal extents."
                if pairs
                else "Pairwise temporal alignment cannot be evaluated from the available time support."
            ),
            observation_ids=tuple(item.observation_id for item in observations),
            provenance={"assessment_id": context.assessment.assessment_id},
            diagnostics={
                "overlap_pairs": pairs,
                "observations_with_explicit_time": known_count,
            },
            limitations=(
                "Interval overlap does not establish synchronization, temporal resolution compatibility, or event correspondence.",
                "A single observed_at timestamp is treated as an instant, not as a sampling interval.",
            ),
        )


class SpatialAlignmentOperator:
    """Conservatively compare bboxes only when both declare the same CRS."""

    operator_id = "satquery.spatial-alignment"
    version = "1.0.0"

    @staticmethod
    def _xy_bounds(
        observation: Observation,
    ) -> tuple[float, float, float, float] | None:
        bbox = observation.bbox
        if bbox is None:
            return None
        if len(bbox) == 4:
            bounds = (bbox[0], bbox[1], bbox[2], bbox[3])
        else:
            bounds = (bbox[0], bbox[1], bbox[3], bbox[4])
        if not all(isfinite(value) for value in bounds):
            return None
        if bounds[0] > bounds[2] or bounds[1] > bounds[3]:
            return None
        return bounds

    def evaluate(self, context: ReasoningContext) -> OperatorResult:
        observations = sorted(
            context.observations, key=lambda item: item.observation_id
        )
        pairs = []
        for index, first in enumerate(observations):
            for second in observations[index + 1 :]:
                first_bounds = self._xy_bounds(first)
                second_bounds = self._xy_bounds(second)
                if (
                    not first.crs
                    or first.crs != second.crs
                    or first_bounds is None
                    or second_bounds is None
                ):
                    continue
                pairs.append(
                    {
                        "first_observation_id": first.observation_id,
                        "second_observation_id": second.observation_id,
                        "same_crs": True,
                        "bboxes_intersect": (
                            first_bounds[0] <= second_bounds[2]
                            and first_bounds[2] >= second_bounds[0]
                            and first_bounds[1] <= second_bounds[3]
                            and first_bounds[3] >= second_bounds[1]
                        ),
                    }
                )
        return OperatorResult(
            operator_id=self.operator_id,
            operator_version=self.version,
            status=(
                "not_applicable"
                if len(observations) < 2
                else "evaluated"
                if pairs
                else "insufficient_evidence"
            ),
            statement=(
                "Pairwise bounding-box intersection was evaluated for observations with explicit matching CRSs."
                if pairs
                else "Spatial overlap cannot be evaluated because matching-CRS bounding boxes are unavailable."
            ),
            observation_ids=tuple(item.observation_id for item in observations),
            provenance={"assessment_id": context.assessment.assessment_id},
            diagnostics={"bbox_pairs": pairs},
            limitations=(
                "Bounding-box intersection is a coarse spatial precheck, not geometry intersection or footprint validity.",
                "No CRS transformation or antimeridian handling is performed.",
            ),
        )


class ObservationAgreementOperator:
    """Compare exact-aligned values under explicit criteria only.

    Exact declared support and acquisition time are required before arithmetic
    comparison. This is a conservative comparability check, not proof that two
    instruments measured the same physical support.
    """

    operator_id = "satquery.observation-agreement"
    version = "2.0.0"

    def __init__(self, criteria: Iterable[MeasurementAgreementCriterion] = ()) -> None:
        self.criteria = {
            (item.canonical_variable, item.unit): item for item in criteria
        }

    def evaluate(self, context: ReasoningContext) -> OperatorResult:
        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for observation in context.observations:
            for measurement in observation.canonical_measurements:
                if (
                    measurement.semantic_status != "resolved"
                    or not measurement.unit
                    or isinstance(measurement.value, bool)
                    or not isinstance(measurement.value, (int, float))
                    or not isfinite(float(measurement.value))
                ):
                    continue
                key = (measurement.canonical_variable, measurement.unit)
                grouped.setdefault(key, []).append(
                    {
                        "observation": observation,
                        "value": float(measurement.value),
                        "modalities": observation.modalities,
                        "measurement_metadata": measurement.source_metadata,
                    }
                )
        pairs = []
        missing_criteria = []
        alignment_blockers = []
        for key, measurements in sorted(grouped.items()):
            if len(measurements) < 2:
                continue
            criterion = self.criteria.get(key)
            if criterion is None:
                missing_criteria.append({"canonical_variable": key[0], "unit": key[1]})
                continue
            for index, left in enumerate(measurements):
                for right in measurements[index + 1 :]:
                    left_observation = left["observation"]
                    right_observation = right["observation"]
                    if left_observation.observation_id == right_observation.observation_id:
                        continue
                    left_metadata = left["measurement_metadata"]
                    right_metadata = right["measurement_metadata"]
                    left_geometry = left_metadata.get(
                        "pixel_support_geometry", left_observation.geometry
                    )
                    right_geometry = right_metadata.get(
                        "pixel_support_geometry", right_observation.geometry
                    )
                    left_crs = left_metadata.get("pixel_support_crs", left_observation.crs)
                    right_crs = right_metadata.get("pixel_support_crs", right_observation.crs)
                    blockers = []
                    if (
                        not isinstance(left_geometry, dict)
                        or not left_geometry
                        or not isinstance(right_geometry, dict)
                        or not right_geometry
                        or not isinstance(left_crs, str)
                        or not left_crs.strip()
                        or not isinstance(right_crs, str)
                        or not right_crs.strip()
                    ):
                        blockers.append("spatial_support_unknown")
                    elif left_crs != right_crs or left_geometry != right_geometry:
                        blockers.append("spatial_support_mismatch")
                    left_time = left_observation.observed_at
                    right_time = right_observation.observed_at
                    if (
                        left_time is None
                        or right_time is None
                        or left_time.tzinfo is None
                        or right_time.tzinfo is None
                    ):
                        blockers.append("acquisition_time_unknown")
                    elif left_time != right_time:
                        blockers.append("acquisition_time_mismatch")
                    if blockers:
                        alignment_blockers.append(
                            {
                                "canonical_variable": key[0],
                                "unit": key[1],
                                "observation_ids": [
                                    left_observation.observation_id,
                                    right_observation.observation_id,
                                ],
                                "reasons": blockers,
                            }
                        )
                        continue

                    difference = abs(left["value"] - right["value"])
                    threshold = criterion.absolute_tolerance + criterion.relative_tolerance * max(
                        abs(left["value"]), abs(right["value"])
                    )
                    pairs.append(
                        {
                            "canonical_variable": key[0],
                            "unit": key[1],
                            "observation_ids": [
                                left_observation.observation_id,
                                right_observation.observation_id,
                            ],
                            "declared_modalities": [
                                list(left["modalities"]),
                                list(right["modalities"]),
                            ],
                            "absolute_difference": difference,
                            "declared_tolerance": threshold,
                            "within_declared_tolerance": difference <= threshold,
                            "criterion_id": criterion.criterion_id,
                            "criterion_version": criterion.version,
                            "criterion_references": list(criterion.reference_ids),
                            "alignment_policy": "exact_geometry_crs_and_acquisition_time",
                        }
                    )
        if pairs:
            status = "evaluated"
            statement = (
                "Comparable numeric observations were checked against explicitly declared tolerances. This is measurement agreement under that criterion, not independent corroboration or scientific support."
            )
        elif missing_criteria or alignment_blockers:
            status = "insufficient_evidence"
            messages = []
            if missing_criteria:
                messages.append(
                    "no explicit agreement criterion supplies a scientifically justified tolerance"
                )
            if alignment_blockers:
                messages.append(
                    "spatial support and acquisition-time compatibility are unknown or differ"
                )
            statement = "Comparable measurement evaluation is incomplete because " + " and ".join(messages) + "."
        else:
            status = "not_applicable"
            statement = (
                "No pair of resolved numeric measurements shares an exact canonical variable and unit."
            )
        observation_ids = tuple(
            sorted(
                {oid for pair in pairs for oid in pair["observation_ids"]}
                | {
                    oid
                    for blocker in alignment_blockers
                    for oid in blocker["observation_ids"]
                }
            )
        )
        return OperatorResult(
            operator_id=self.operator_id,
            operator_version=self.version,
            status=status,
            statement=statement,
            observation_ids=observation_ids,
            requirement_ids=(
                ("exact_spatiotemporal_support",) if alignment_blockers else ()
            ),
            diagnostics={
                "pairwise_comparisons": pairs,
                "missing_criteria": missing_criteria,
                "alignment_blockers": alignment_blockers,
            },
            limitations=(
                "No unit conversion is performed.",
                "Exact declared geometry, CRS, and acquisition timestamp are required; equality does not prove equivalent instrument footprints or temporal aggregation.",
                "Agreement does not establish observation independence or scientific validity.",
            ),
        )


class HypothesisManager:
    """Evaluate hypotheses only with applicable, explicitly validated rules."""

    def __init__(
        self,
        applicability: RuleApplicabilityEvaluator | None = None,
        uncertainty_methods: UncertaintyMethodRegistry | None = None,
        certification_check: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.applicability = applicability or RuleApplicabilityEvaluator()
        self.uncertainty_methods = uncertainty_methods or UncertaintyMethodRegistry()
        self.certification_check = certification_check

    def evaluate(
        self,
        context: ReasoningContext,
        rules: tuple[ScientificRule, ...],
    ) -> tuple[
        tuple[HypothesisEvaluation, ...],
        tuple[ScientificFinding, ...],
        tuple[RuleApplicabilityOutcome, ...],
        tuple[ScientificRuleResult, ...],
        tuple[ReasoningTraceStep, ...],
    ]:
        if context.hypothesis_graph is None:
            hypotheses = tuple(item.hypothesis for item in context.design.hypotheses)
        else:
            hypotheses = tuple(
                CandidateHypothesis(
                    statement=item.proposition,
                    source_text=item.source_text,
                    origin=item.origin,
                )
                for item in context.hypothesis_graph.hypotheses
                if item.origin != "composite"
                and item.lifecycle in {"active", "under_review"}
            )
        findings: list[ScientificFinding] = []
        evaluations: list[HypothesisEvaluation] = []
        applicability_records: list[RuleApplicabilityOutcome] = []
        rule_results: list[ScientificRuleResult] = []
        traces: list[ReasoningTraceStep] = []
        observation_by_id = {item.observation_id: item for item in context.observations}
        declared_requirements = {
            item.requirement_id for item in context.assessment.requirements
        }
        declared_requirements.update(
            requirement.requirement_id
            for rule in rules
            for requirement in rule.manifest.required_evidence
        )

        for hypothesis in hypotheses:
            matched: list[ScientificFinding] = []
            evaluated_rule_ids: list[str] = []
            applicable_rule_count = 0
            missing_requirement_ids = {
                item.requirement_id
                for item in context.assessment.requirements
                if item.status in {"missing", "partial", "indeterminate"}
            }
            for rule in rules:
                manifest = rule.manifest
                certified = (
                    self.certification_check is not None
                    and self.certification_check(manifest.rule_id, manifest.version)
                )
                if certified:
                    applicability = self.applicability.evaluate(
                        manifest, hypothesis, context
                    )
                else:
                    applicability = RuleApplicabilityOutcome(
                        rule_id=manifest.rule_id,
                        rule_version=manifest.version,
                        hypothesis_statement=hypothesis.statement,
                        status="unvalidated",
                        reasons=("Method has not completed platform certification through executable validation and required review.",),
                    )
                applicability_records.append(applicability)
                traces.append(
                    ReasoningTraceStep(
                        sequence=len(traces),
                        stage="applicability",
                        component_id=manifest.rule_id,
                        component_version=manifest.version,
                        status=applicability.status,
                        input_observation_ids=tuple(
                            item.observation_id for item in context.observations
                        ),
                        explanation=" ".join(applicability.reasons)
                        or "All declared rule preconditions are met.",
                        parameters={"hypothesis": hypothesis.statement},
                    )
                )
                if applicability.status != "applicable":
                    status = (
                        "not_applicable"
                        if applicability.status == "unvalidated"
                        else "insufficient_evidence"
                    )
                    result = ScientificRuleResult(
                        rule_id=manifest.rule_id,
                        rule_version=manifest.version,
                        hypothesis_statement=hypothesis.statement,
                        status=status,
                        statement="Rule was not executed because its validation status or declared preconditions did not permit evaluation.",
                        missing_requirement_ids=tuple(sorted(missing_requirement_ids)),
                        limitations=applicability.reasons,
                    )
                    rule_results.append(result)
                    continue
                applicable_rule_count += 1
                try:
                    result = ScientificRuleResult.model_validate(
                        rule.evaluate(hypothesis, context)
                    )
                except (
                    Exception
                ) as exc:  # isolate scientific extensions from acquisition lifecycle
                    result = ScientificRuleResult(
                        rule_id=manifest.rule_id,
                        rule_version=manifest.version,
                        hypothesis_statement=hypothesis.statement,
                        status="error",
                        statement=f"Rule execution failed with {type(exc).__name__}; no scientific finding was emitted.",
                        limitations=(
                            "The raw exception message is not included in the scientific record.",
                        ),
                    )
                if (
                    result.rule_id != manifest.rule_id
                    or result.rule_version != manifest.version
                ):
                    result = result.model_copy(
                        update={
                            "status": "error",
                            "statement": "Rule output identity/version did not match its registered manifest; output was rejected.",
                            "observation_ids": (),
                            "evidential_relation": "inconclusive",
                            "limitations": (
                                *result.limitations,
                                "Rule identity mismatch.",
                            ),
                        }
                    )
                unknown_observation_ids = set(result.observation_ids).difference(
                    observation_by_id
                )
                unknown_requirement_ids = set(
                    result.missing_requirement_ids
                ).difference(declared_requirements)
                if unknown_observation_ids or unknown_requirement_ids:
                    result = result.model_copy(
                        update={
                            "status": "error",
                            "statement": "Rule output referenced evidence outside the investigation contract; output was rejected.",
                            "observation_ids": (),
                            "evidential_relation": "inconclusive",
                            "limitations": (
                                *result.limitations,
                                "Evidence reference validation failed.",
                            ),
                        }
                    )
                expected_uncertainty = manifest.uncertainty_propagation
                if expected_uncertainty.status == "required":
                    method = self.uncertainty_methods.get(
                        expected_uncertainty.method_id or "",
                        expected_uncertainty.method_version or "",
                    )
                    if method is None:
                        result = result.model_copy(
                            update={
                                "status": "insufficient_evidence",
                                "statement": "The rule requires an uncertainty propagator that is not registered; no directional finding was emitted.",
                                "evidential_relation": "inconclusive",
                                "limitations": (
                                    *result.limitations,
                                    "Required uncertainty method is unavailable.",
                                ),
                            }
                        )
                    else:
                        try:
                            uncertainty = method.propagate(result, context)
                            if (
                                uncertainty.method_id != method.method_id
                                or uncertainty.method_version != method.version
                            ):
                                raise ValueError(
                                    "uncertainty method identity/version mismatch"
                                )
                            result = result.model_copy(
                                update={"uncertainty": uncertainty}
                            )
                        except Exception as exc:
                            result = result.model_copy(
                                update={
                                    "status": "error",
                                    "statement": f"Uncertainty propagation failed with {type(exc).__name__}; no scientific finding was emitted.",
                                    "evidential_relation": "inconclusive",
                                    "limitations": (
                                        *result.limitations,
                                        "Uncertainty method output was rejected.",
                                    ),
                                }
                            )
                if result.hypothesis_statement != hypothesis.statement:
                    result = result.model_copy(
                        update={
                            "status": "error",
                            "statement": "Rule output hypothesis did not match the evaluated hypothesis; output was rejected.",
                            "observation_ids": (),
                            "evidential_relation": "inconclusive",
                            "limitations": (
                                *result.limitations,
                                "Hypothesis identity validation failed.",
                            ),
                        }
                    )
                uncertainty_valid = expected_uncertainty.status != "required" or (
                    result.uncertainty.status in {"quantified", "partially_quantified"}
                    and result.uncertainty.method_id == expected_uncertainty.method_id
                    and result.uncertainty.method_version
                    == expected_uncertainty.method_version
                )
                if not uncertainty_valid:
                    result = result.model_copy(
                        update={
                            "status": "insufficient_evidence",
                            "statement": "The rule's required uncertainty propagation was not supplied by its declared method; no directional finding was emitted.",
                            "evidential_relation": "inconclusive",
                            "limitations": (
                                *result.limitations,
                                "Required uncertainty propagation is missing or mismatched.",
                            ),
                        }
                    )
                if result.evidence_weight.status == "available":
                    reference_ids = {
                        item.reference_id for item in manifest.scientific_references
                    }
                    if not set(
                        result.evidence_weight.calibration_reference_ids
                    ).issubset(reference_ids):
                        result = result.model_copy(
                            update={
                                "status": "error",
                                "statement": "Evidence weight cited calibration references absent from the registered rule manifest; output was rejected.",
                                "evidence_weight": CalibratedEvidenceWeight(),
                                "evidential_relation": "inconclusive",
                                "limitations": (
                                    *result.limitations,
                                    "Evidence-weight calibration provenance failed validation.",
                                ),
                            }
                        )
                rule_results.append(result)
                traces.append(
                    ReasoningTraceStep(
                        sequence=len(traces),
                        stage="rule",
                        component_id=manifest.rule_id,
                        component_version=manifest.version,
                        status=result.status,
                        input_observation_ids=result.observation_ids,
                        explanation=result.statement,
                        parameters={
                            "hypothesis": hypothesis.statement,
                            **result.parameters,
                        },
                    )
                )
                if result.status == "evaluated":
                    evaluated_rule_ids.append(manifest.rule_id)
                if (
                    result.status == "evaluated"
                    and result.evidential_relation in {"supports", "contradicts"}
                    and not result.observation_ids
                ):
                    result = result.model_copy(
                        update={
                            "status": "error",
                            "statement": "Directional rule result omitted supporting observation references; output was rejected.",
                            "evidential_relation": "inconclusive",
                            "limitations": (
                                *result.limitations,
                                "Directional findings must cite observations.",
                            ),
                        }
                    )
                    rule_results[-1] = result
                    traces[-1] = traces[-1].model_copy(
                        update={"status": "error", "explanation": result.statement}
                    )
                if (
                    result.status != "evaluated"
                    or result.evidential_relation == "inconclusive"
                    or not result.observation_ids
                ):
                    continue
                finding = ScientificFinding(
                    finding_id=_stable_finding_id(
                        manifest.rule_id,
                        manifest.version,
                        hypothesis.statement,
                        result.observation_ids,
                        result.statement,
                    ),
                    rule_id=manifest.rule_id,
                    rule_version=manifest.version,
                    statement=result.statement,
                    hypothesis_statement=hypothesis.statement,
                    evidential_relation=result.evidential_relation,
                    observation_ids=result.observation_ids,
                    provenance={
                        "rule_manifest": manifest.model_dump(mode="json"),
                        "rule_parameters": result.parameters,
                    },
                    observation_provenance={
                        oid: observation_by_id[oid].provenance
                        for oid in result.observation_ids
                    },
                    observation_uncertainty={
                        oid: observation_by_id[oid].uncertainty
                        for oid in result.observation_ids
                    },
                    supporting_observation_ids=result.observation_ids
                    if result.evidential_relation == "supports"
                    else (),
                    contradicting_observation_ids=result.observation_ids
                    if result.evidential_relation == "contradicts"
                    else (),
                    unresolved_observation_ids=result.observation_ids
                    if result.evidential_relation in {"contextual", "inconclusive"}
                    else (),
                    uncertainty=result.uncertainty,
                    evidence_weight=result.evidence_weight,
                    assumptions=(
                        *manifest.applicability.assumptions,
                        *result.assumptions,
                    ),
                    limitations=(*manifest.known_limitations, *result.limitations),
                )
                matched.append(finding)
                findings.append(finding)
            supporting = tuple(
                sorted(
                    {oid for item in matched for oid in item.supporting_observation_ids}
                )
            )
            contradicting = tuple(
                sorted(
                    {
                        oid
                        for item in matched
                        for oid in item.contradicting_observation_ids
                    }
                )
            )
            unresolved = tuple(
                sorted(
                    {oid for item in matched for oid in item.unresolved_observation_ids}
                )
            )
            directional = bool(supporting or contradicting)
            evaluations.append(
                HypothesisEvaluation(
                    hypothesis=hypothesis,
                    status=(
                        "evaluated"
                        if directional
                        else "insufficient_evidence"
                        if applicable_rule_count
                        else "not_evaluated"
                    ),
                    supporting_observation_ids=supporting,
                    contradicting_observation_ids=contradicting,
                    unresolved_observation_ids=unresolved,
                    missing_requirement_ids=tuple(sorted(missing_requirement_ids)),
                    explanation=(
                        "Validated methods produced directional findings. No aggregate hypothesis ranking is claimed without explicit prior and calibrated evidence weights."
                        if directional
                        else "No validated applicable method produced directional evidence for this hypothesis."
                    ),
                    rule_ids=tuple(evaluated_rule_ids),
                    uncertainty=ScientificUncertainty(
                        status="not_quantified",
                        reason="No registered engine-level uncertainty model combined the per-rule uncertainty records.",
                        observation_ids=tuple(
                            sorted(set(supporting + contradicting + unresolved))
                        ),
                    ),
                )
            )
        return (
            tuple(evaluations),
            tuple(findings),
            tuple(applicability_records),
            tuple(rule_results),
            tuple(traces),
        )


class ScientificReasoningEngine:
    def __init__(
        self,
        *,
        operators: OperatorRegistry | None = None,
        rules: RuleRegistry | None = None,
        uncertainty_methods: UncertaintyMethodRegistry | None = None,
        evidence_evaluation: EvidenceEvaluationEngine | None = None,
        certification_check: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.operators = operators or OperatorRegistry(
            (
                EvidenceCompletenessOperator(),
                MissingEvidenceOperator(),
                ObservationConflictOperator(),
                MeasurementCompatibilityOperator(),
                TemporalAlignmentOperator(),
                SpatialAlignmentOperator(),
                ObservationAgreementOperator(),
            )
        )
        self.rules = rules or RuleRegistry()
        self.uncertainty_methods = uncertainty_methods or UncertaintyMethodRegistry()
        self.evidence_evaluation = evidence_evaluation or EvidenceEvaluationEngine()
        self.hypothesis_manager = HypothesisManager(
            uncertainty_methods=self.uncertainty_methods,
            certification_check=certification_check,
        )

    def evaluate(self, context: ReasoningContext) -> ScientificReasoningReport:
        evidence_evaluation = self.evidence_evaluation.evaluate(context.observations)
        context = context.model_copy(update={"evidence_evaluation": evidence_evaluation})
        operator_results: list[OperatorResult] = []
        trace: list[ReasoningTraceStep] = []
        for operator in self.operators.all():
            try:
                result = operator.evaluate(context)
            except Exception as exc:
                result = OperatorResult(
                    operator_id=operator.operator_id,
                    operator_version=operator.version,
                    status="error",
                    statement=f"Operator failed with {type(exc).__name__}; no scientific inference was produced.",
                    provenance={"assessment_id": context.assessment.assessment_id},
                )
            operator_results.append(result)
            trace.append(
                ReasoningTraceStep(
                    sequence=len(trace),
                    stage="operator",
                    component_id=result.operator_id,
                    component_version=result.operator_version,
                    status=result.status,
                    input_observation_ids=result.observation_ids,
                    explanation=result.statement,
                    parameters=result.diagnostics,
                )
            )
        (
            hypothesis_evaluations,
            findings,
            applicability,
            rule_evaluations,
            rule_trace,
        ) = self.hypothesis_manager.evaluate(context, self.rules.all())
        trace.extend(
            item.model_copy(update={"sequence": len(trace) + index})
            for index, item in enumerate(rule_trace)
        )
        missing_set = {rid for item in operator_results for rid in item.requirement_ids}
        missing_set.update(
            rid for item in rule_evaluations for rid in item.missing_requirement_ids
        )
        missing = tuple(sorted(missing_set))
        precondition_gaps = tuple(
            dict.fromkeys(
                target
                for item in applicability
                if item.status == "insufficient_evidence"
                for target in item.missing_evidence
            )
        )
        missing = tuple(sorted(set(missing).union(precondition_gaps)))
        has_observations = bool(context.observations)
        conclusion_findings = tuple(
            item
            for item in findings
            if item.evidential_relation in {"supports", "contradicts"}
        )
        observation_by_id = {item.observation_id: item for item in context.observations}

        def trace_evidence(
            finding: ScientificFinding, disposition: str
        ) -> EvidenceTraceItem:
            return EvidenceTraceItem(
                disposition=disposition,
                rule_id=finding.rule_id,
                rule_version=finding.rule_version,
                statement=finding.statement,
                observation_ids=finding.observation_ids,
                provenance={
                    observation_id: observation_by_id[observation_id].provenance
                    for observation_id in finding.observation_ids
                },
                uncertainty=finding.uncertainty,
                evidence_weight=finding.evidence_weight,
            )

        supporting = tuple(
            trace_evidence(item, "supports")
            for item in conclusion_findings
            if item.evidential_relation == "supports"
        )
        contradicting = tuple(
            trace_evidence(item, "contradicts")
            for item in conclusion_findings
            if item.evidential_relation == "contradicts"
        )
        unresolved = [
            trace_evidence(item, "unresolved")
            for item in findings
            if item.evidential_relation in {"contextual", "inconclusive"}
        ]
        for result in rule_evaluations:
            if (
                result.status in {"insufficient_evidence", "error"}
                and result.observation_ids
            ):
                unresolved.append(
                    EvidenceTraceItem(
                        disposition="unresolved",
                        rule_id=result.rule_id,
                        rule_version=result.rule_version,
                        statement=result.statement,
                        observation_ids=result.observation_ids,
                        provenance={
                            observation_id: observation_by_id[observation_id].provenance
                            for observation_id in result.observation_ids
                            if observation_id in observation_by_id
                        },
                        uncertainty=result.uncertainty,
                        evidence_weight=result.evidence_weight,
                    )
                )
        unresolved_evidence = tuple(unresolved)
        missing_details = tuple(
            EvidenceGap(
                requirement_id=item.requirement_id,
                evidence_type=item.evidence_type,
                target=item.target,
                status=item.status,
                explanation=item.explanation,
            )
            for item in context.assessment.requirements
            if item.status in {"missing", "partial", "indeterminate"}
        )
        alignment_gaps = {
            (
                "exact_spatiotemporal_support",
                f"{item['canonical_variable']} [{item['unit']}]; observations "
                f"{item['observation_ids'][0]} and {item['observation_ids'][1]}",
            ): EvidenceGap(
                requirement_id="exact_spatiotemporal_support",
                evidence_type="spatial_temporal_alignment",
                target=(
                    f"{item['canonical_variable']} [{item['unit']}]; observations "
                    f"{item['observation_ids'][0]} and {item['observation_ids'][1]}"
                ),
                status="indeterminate",
                explanation=(
                    "Agreement comparison was withheld because exact declared "
                    "spatial support, CRS, and acquisition time were not established "
                    f"({', '.join(item['reasons'])})."
                ),
            )
            for result in operator_results
            for item in result.diagnostics.get("alignment_blockers", ())
        }
        missing_details = (
            *missing_details,
            *(alignment_gaps[key] for key in sorted(alignment_gaps)),
        )
        rule_requirements = {
            requirement.requirement_id: requirement
            for rule in self.rules.all()
            for requirement in rule.manifest.required_evidence
        }
        rule_missing_details = tuple(
            EvidenceGap(
                requirement_id=requirement_id,
                evidence_type=requirement.evidence_type,
                target=requirement.target,
                status="missing",
                explanation=requirement.rationale,
            )
            for requirement_id in sorted(
                {
                    requirement_id
                    for result in rule_evaluations
                    for requirement_id in result.missing_requirement_ids
                }
            )
            if (requirement := rule_requirements.get(requirement_id)) is not None
        )
        hypothesis_graph = context.hypothesis_graph or hypothesis_graph_from_candidates(
            item.hypothesis for item in context.design.hypotheses
        )
        uncertainty_budget = UncertaintyBudgetEngine().build(
            context.observations,
            (
                (f"rule:{item.rule_id}@{item.rule_version}", item.uncertainty)
                for item in rule_evaluations
                if item.status in {"evaluated", "insufficient_evidence"}
            ),
        )
        uncertainty_budget = uncertainty_budget.model_copy(
            update={
                "components": (
                    *uncertainty_budget.components,
                    UncertaintyComponent(
                        component_id="reasoning:scientific-engine",
                        category="reasoning",
                        status="not_quantified",
                        source_id=REASONING_ENGINE_ID,
                        source_metadata={"engine_version": REASONING_ENGINE_VERSION},
                    ),
                ),
                "propagation_status": (
                    "partially_performed"
                    if any(
                        item.uncertainty.status
                        in {"quantified", "partially_quantified"}
                        for item in rule_evaluations
                    )
                    else "not_performed"
                ),
            }
        )
        alternative_explanations = AlternativeExplanationEngine().evaluate(
            hypothesis_graph,
            (item.model_dump(mode="json") for item in findings),
        )
        refinement_recommendations = InvestigationRefinementEngine().recommend(
            (*missing_details, *rule_missing_details)
        )
        trace.append(
            ReasoningTraceStep(
                sequence=len(trace),
                stage="evidence_evaluation",
                component_id="satquery.evidence-evaluation",
                component_version="1.0.0",
                status="evaluated",
                input_observation_ids=tuple(sorted(observation_by_id)),
                explanation=evidence_evaluation.statement,
                parameters={
                    "declared_source_count": evidence_evaluation.declared_source_count,
                    "independence_assessed_count": evidence_evaluation.independence_assessed_count,
                },
            )
        )
        trace.append(
            ReasoningTraceStep(
                sequence=len(trace),
                stage="alternative",
                component_id="satquery.alternative-explanations",
                component_version="1.0.0",
                status="evaluated" if alternative_explanations else "no_explicit_groups",
                explanation=(
                    "Explicitly grouped alternatives were inspected; no completeness or ranking is implied."
                    if alternative_explanations
                    else "No competing-hypothesis groups were explicitly declared; the engine did not invent alternatives."
                ),
                parameters={"group_count": len(alternative_explanations)},
            )
        )
        trace.append(
            ReasoningTraceStep(
                sequence=len(trace),
                stage="uncertainty",
                component_id="satquery.uncertainty-budget",
                component_version="1.0.0",
                status=uncertainty_budget.propagation_status,
                input_observation_ids=tuple(sorted(observation_by_id)),
                explanation=uncertainty_budget.statement,
                parameters={
                    "component_count": len(uncertainty_budget.components),
                    "quantified_component_count": sum(
                        item.status == "quantified"
                        for item in uncertainty_budget.components
                    ),
                },
            )
        )
        trace.append(
            ReasoningTraceStep(
                sequence=len(trace),
                stage="refinement",
                component_id="satquery.investigation-refinement",
                component_version="1.0.0",
                status="recommendations_available"
                if refinement_recommendations
                else "no_gaps",
                explanation=(
                    "Recommendations are limited to declared missing or indeterminate evidence requirements; dataset and modality choice remains capability-planned."
                ),
                parameters={
                    "recommendation_ids": [
                        item.recommendation_id for item in refinement_recommendations
                    ]
                },
            )
        )
        conclusion_trace = ReasoningTraceStep(
            sequence=len(trace),
            stage="conclusion",
            component_id="satquery.conclusion-assembler",
            component_version=REASONING_ENGINE_VERSION,
            status="findings_available" if conclusion_findings else "unresolved",
            input_observation_ids=tuple(sorted(observation_by_id)),
            output_finding_ids=tuple(item.finding_id for item in conclusion_findings),
            explanation=(
                "Conclusion assembled from rule outputs with explicit evidential direction; no ranking or confidence was inferred."
                if conclusion_findings
                else "No validated applicable rule produced a directional finding; the conclusion remains unresolved."
            ),
            parameters={"missing_requirement_ids": missing},
        )
        trace.append(conclusion_trace)
        conclusion = ScientificConclusion(
            status="findings_available" if conclusion_findings else "unresolved",
            findings=conclusion_findings,
            explanation=(
                "Registered scientific rules produced traceable, directional findings. They are not a calibrated probability or universal ranking."
                if conclusion_findings
                else "No defensible scientific conclusion can be generated: structural evidence diagnostics are not hypothesis tests, and no applicable registered scientific rule produced a directional finding."
            ),
            missing_evidence=missing,
            missing_evidence_details=(*missing_details, *rule_missing_details),
            additional_observation_targets=precondition_gaps,
            competing_hypothesis_statements=tuple(
                item.hypothesis.statement for item in hypothesis_evaluations
            ),
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            unresolved_evidence=unresolved_evidence,
            reasoning_trace=tuple(trace),
            uncertainty={
                "status": "not_quantified",
                "reason": "No calibrated uncertainty propagation method is registered.",
            },
        )
        observation_manifest = [
            item.model_dump(mode="json")
            for item in sorted(
                context.observations, key=lambda value: value.observation_id
            )
        ]
        input_sha256 = hashlib.sha256(
            json.dumps(
                observation_manifest, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        rule_manifest_sha256 = hashlib.sha256(
            json.dumps(
                [rule.manifest.model_dump(mode="json") for rule in self.rules.all()],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        validated_rule_ids = {
            rule.manifest.rule_id
            for rule in self.rules.all()
            if rule.manifest.validation_status == "validated"
        }
        applicable_rule_ids = tuple(
            sorted(
                {item.rule_id for item in applicability if item.status == "applicable"}
            )
        )
        unmet_preconditions = tuple(
            dict.fromkeys(
                target for item in applicability for target in item.missing_evidence
            )
        )
        sufficiency = EvidenceSufficiencyAssessment(
            status=(
                "method_inputs_satisfied"
                if applicable_rule_ids
                else "insufficient"
                if validated_rule_ids
                else "not_assessable"
            ),
            explanation=(
                "At least one validated method's declared input preconditions are met. This is method input sufficiency, not scientific evidence sufficiency."
                if applicable_rule_ids
                else "Validated methods exist, but none currently meet their declared input preconditions."
                if validated_rule_ids
                else "No validated scientific methods are registered; scientific sufficiency cannot be assessed."
            ),
            applicable_validated_rule_ids=applicable_rule_ids,
            unmet_preconditions=unmet_preconditions,
        )
        return ScientificReasoningReport(
            reasoning_id=f"{context.investigation_id}:{context.assessment.assessment_id}:{REASONING_ENGINE_VERSION}",
            investigation_id=context.investigation_id,
            status="evaluated"
            if conclusion_findings
            else (
                "insufficient_evidence"
                if not has_observations or missing
                else "not_evaluable"
            ),
            hypothesis_evaluations=hypothesis_evaluations,
            hypothesis_graph=hypothesis_graph,
            hypothesis_lifecycle_events=context.hypothesis_lifecycle_events,
            alternative_explanations=alternative_explanations,
            evidence_evaluation=evidence_evaluation,
            uncertainty_budget=uncertainty_budget,
            refinement_recommendations=refinement_recommendations,
            operator_results=operator_results,
            findings=findings,
            rule_applicability=applicability,
            rule_evaluations=rule_evaluations,
            reasoning_trace=tuple(trace),
            sufficiency=sufficiency,
            conclusion=conclusion,
            observation_ids=tuple(
                sorted(item.observation_id for item in context.observations)
            ),
            reproducibility={
                "engine_id": REASONING_ENGINE_ID,
                "engine_version": REASONING_ENGINE_VERSION,
                "design_id": context.design.design_id,
                "assessment_id": context.assessment.assessment_id,
                "input_observation_manifest_sha256": input_sha256,
                "rule_manifest_sha256": rule_manifest_sha256,
                "operator_versions": {
                    item.operator_id: item.operator_version for item in operator_results
                },
                "rule_versions": {
                    f"{rule.manifest.rule_id}@{rule.manifest.version}": {
                        "version": rule.manifest.version,
                        "validation_status": rule.manifest.validation_status,
                        "implementation_sha256": rule.manifest.implementation_sha256,
                    }
                    for rule in self.rules.all()
                },
                "uncertainty_method_versions": self.uncertainty_methods.versions(),
                "hypothesis_graph_sha256": hashlib.sha256(
                    hypothesis_graph.model_dump_json().encode("utf-8")
                ).hexdigest(),
                "hypothesis_lifecycle_event_ids": [
                    item.event_id for item in context.hypothesis_lifecycle_events
                ],
                "evidence_evaluation_sha256": hashlib.sha256(
                    evidence_evaluation.model_dump_json().encode("utf-8")
                ).hexdigest(),
                "uncertainty_budget_sha256": hashlib.sha256(
                    uncertainty_budget.model_dump_json().encode("utf-8")
                ).hexdigest(),
            },
            limitations=(
                "No default operator makes scientific truth, causality, probability, or confidence claims.",
                "Measurement comparability requires explicit semantics and units; raw measured_variables are never silently interpreted by this engine.",
                "Numerical evidence weights are retained only when a validated rule supplies calibrated likelihood evidence; the engine does not aggregate them without explicit priors and dependence assumptions.",
            ),
        )
