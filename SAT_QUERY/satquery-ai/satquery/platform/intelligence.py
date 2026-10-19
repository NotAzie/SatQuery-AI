"""Deterministic investigation design and evidence coverage auditing.

The intelligence layer connects a parsed investigation plan to evidence
collection strategies, then audits acquired observations against declared
requirements. It does not infer causality, scientific truth, or confidence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Literal, Optional

from pydantic import Field, model_validator

from .contracts import Contract, Observation, PerceptionResult
from .ontology import EARTH_VARIABLE_ONTOLOGY, EarthVariableOntology
from .planning import (
    CandidateHypothesis,
    CandidateInvestigationPlan,
    EvidenceRequirement,
    InvestigationPlan,
)

INTELLIGENCE_ENGINE_ID = "satquery.deterministic-investigation-intelligence"
INTELLIGENCE_ENGINE_VERSION = "1.0.0"


class EvidenceStrategyItem(Contract):
    """Trace one planning requirement to one or more acquisition steps."""

    requirement: EvidenceRequirement
    supporting_step_ids: tuple[str, ...] = ()
    status: Literal["planned", "unaddressed"]
    explanation: str


class CandidateEvidenceStrategy(Contract):
    candidate_plan_id: str = Field(min_length=1)
    step_ids: tuple[str, ...] = ()
    requirements: tuple[EvidenceStrategyItem, ...] = ()
    status: Literal["ready_for_acquisition", "incomplete", "unexecutable"]
    limitations: tuple[str, ...] = ()


class HypothesisStrategy(Contract):
    hypothesis: CandidateHypothesis
    context_requirement_ids: tuple[str, ...] = ()
    status: Literal["unassessed"] = "unassessed"
    explanation: str = (
        "The proposition is preserved from the request; no test or scientific conclusion has been evaluated."
    )


class InvestigationEvidenceNode(Contract):
    node_id: str = Field(min_length=1)
    node_type: Literal[
        "investigation_plan", "hypothesis", "evidence_requirement",
        "candidate_strategy", "observation_step", "observation",
        "assessment", "reported_conflict",
    ]
    label: str = Field(min_length=1)
    source_reference: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class InvestigationEvidenceEdge(Contract):
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    relation: Literal[
        "records", "requires", "contains", "planned_by", "observed_in",
        "reports", "conflicts_with",
    ]
    basis: dict[str, Any] = Field(default_factory=dict)


class InvestigationEvidenceGraph(Contract):
    nodes: tuple[InvestigationEvidenceNode, ...] = ()
    edges: tuple[InvestigationEvidenceEdge, ...] = ()

    @model_validator(mode="after")
    def validate_graph(self) -> "InvestigationEvidenceGraph":
        node_ids = [item.node_id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("investigation evidence graph node identifiers must be unique")
        known_nodes = set(node_ids)
        edge_ids = [
            (item.source_node_id, item.target_node_id, item.relation)
            for item in self.edges
        ]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("investigation evidence graph edges must be unique")
        for edge in self.edges:
            if edge.source_node_id not in known_nodes or edge.target_node_id not in known_nodes:
                raise ValueError("investigation evidence graph edges must reference existing nodes")
        return self


class InvestigationDesign(Contract):
    design_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    engine_id: str = INTELLIGENCE_ENGINE_ID
    engine_version: str = INTELLIGENCE_ENGINE_VERSION
    status: Literal["ready_for_acquisition", "needs_clarification", "no_executable_strategy"]
    hypotheses: tuple[HypothesisStrategy, ...] = ()
    candidate_strategies: tuple[CandidateEvidenceStrategy, ...] = ()
    evidence_graph: InvestigationEvidenceGraph = Field(default_factory=InvestigationEvidenceGraph)
    evidence_policy: Literal["declared_requirement_coverage_only"] = "declared_requirement_coverage_only"
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()


class EvidenceRequirementAssessment(Contract):
    requirement_id: str = Field(min_length=1)
    evidence_type: str
    target: str
    status: Literal["observed", "partial", "missing", "indeterminate"]
    observation_ids: tuple[str, ...] = ()
    explanation: str


class HypothesisAssessment(Contract):
    hypothesis: CandidateHypothesis
    status: Literal["not_evaluated"] = "not_evaluated"
    explanation: str = (
        "No preregistered scientific test operator is available; observations alone do not establish this proposition."
    )


class EvidenceAssessment(Contract):
    assessment_id: str = Field(min_length=1)
    design_id: str = Field(min_length=1)
    candidate_plan_id: str = Field(min_length=1)
    status: Literal["coverage_observed", "coverage_partial", "no_observations", "indeterminate"]
    requirements: tuple[EvidenceRequirementAssessment, ...] = ()
    hypotheses: tuple[HypothesisAssessment, ...] = ()
    observation_ids: tuple[str, ...] = ()
    reported_conflicts: tuple[dict[str, Any], ...] = ()
    execution_statuses: tuple[str, ...] = ()
    evidence_graph: InvestigationEvidenceGraph = Field(default_factory=InvestigationEvidenceGraph)
    reproducibility: dict[str, Any] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()


class InvestigationIntelligenceEngine:
    """Design evidence strategies and report bounded, auditable coverage."""

    def __init__(
        self,
        *,
        ontology: EarthVariableOntology = EARTH_VARIABLE_ONTOLOGY,
    ) -> None:
        self.ontology = ontology

    def design(self, plan: InvestigationPlan) -> InvestigationDesign:
        strategies = tuple(
            self._candidate_strategy(plan, candidate)
            for candidate in plan.candidate_plans
        )
        if plan.status == "needs_clarification":
            status = "needs_clarification"
        elif any(item.status == "ready_for_acquisition" for item in strategies):
            status = "ready_for_acquisition"
        else:
            status = "no_executable_strategy"

        hypotheses = tuple(
            HypothesisStrategy(
                hypothesis=hypothesis,
                context_requirement_ids=tuple(
                    requirement.requirement_id for requirement in plan.required_evidence
                ),
                explanation=(
                    "Investigation-level collection requirements are shown for context only; "
                    "they are not asserted to operationalize this hypothesis."
                ),
            )
            for hypothesis in plan.hypotheses
        )
        design_id = _stable_id(
            f"{INTELLIGENCE_ENGINE_VERSION}:{plan.plan_id}:"
            f"{plan.reproducibility.get('request_sha256', '')}:"
            f"{plan.capability_matrix_revision}"
        )
        return InvestigationDesign(
            design_id=design_id,
            plan_id=plan.plan_id,
            status=status,
            hypotheses=hypotheses,
            candidate_strategies=strategies,
            evidence_graph=_design_graph(plan, strategies),
            reproducibility={
                "engine_id": INTELLIGENCE_ENGINE_ID,
                "engine_version": INTELLIGENCE_ENGINE_VERSION,
                "plan_id": plan.plan_id,
                "capability_matrix_revision": plan.capability_matrix_revision,
                "policy": "requirement-to-step traceability; no inferred scientific truth",
            },
            limitations=(
                "Strategies organize declared evidence requirements; they do not prove a hypothesis is testable.",
                "No observations are acquired during design.",
                "No causal inference, confidence estimate, or scientific conclusion is produced.",
            ),
        )

    def assess(
        self,
        design: InvestigationDesign,
        candidate: CandidateInvestigationPlan,
        results: Iterable[PerceptionResult],
    ) -> EvidenceAssessment:
        result_values = tuple(results)
        observations = tuple(
            observation
            for result in result_values
            for observation in result.observations
        )
        unique_observations = {
            item.observation_id: item for item in observations
        }
        observations = tuple(unique_observations[key] for key in sorted(unique_observations))

        candidate_strategy = next(
            (item for item in design.candidate_strategies
             if item.candidate_plan_id == candidate.candidate_plan_id),
            None,
        )
        assessments = tuple(
            self._assess_requirement(item.requirement, observations, result_values)
            for item in (candidate_strategy.requirements if candidate_strategy else ())
        )
        result_statuses = tuple(sorted({result.status for result in result_values}))
        conflicts = tuple(
            conflict
            for result in result_values
            for conflict in result.conflicts
        )

        if not observations:
            status = "no_observations" if result_values and all(
                result.status == "complete" for result in result_values
            ) else "indeterminate"
        elif result_values and any(result.status != "complete" for result in result_values):
            status = "coverage_partial" if observations else "indeterminate"
        elif assessments and all(item.status == "observed" for item in assessments):
            status = "coverage_observed"
        elif any(
            item.status in {"observed", "partial", "missing"}
            for item in assessments
        ):
            status = "coverage_partial"
        else:
            status = "indeterminate"

        assessment_id = _stable_id(
            f"{design.design_id}:{candidate.candidate_plan_id}:"
            f"{','.join(sorted(unique_observations))}:{','.join(result_statuses)}"
        )
        evidence_graph = _assessment_graph(
            design=design,
            assessment_id=assessment_id,
            assessments=assessments,
            observations=observations,
            conflicts=conflicts,
        )
        return EvidenceAssessment(
            assessment_id=assessment_id,
            design_id=design.design_id,
            candidate_plan_id=candidate.candidate_plan_id,
            status=status,
            requirements=assessments,
            hypotheses=tuple(
                HypothesisAssessment(hypothesis=item.hypothesis)
                for item in design.hypotheses
            ),
            observation_ids=tuple(sorted(unique_observations)),
            reported_conflicts=conflicts,
            execution_statuses=result_statuses,
            evidence_graph=evidence_graph,
            reproducibility={
                "engine_id": INTELLIGENCE_ENGINE_ID,
                "engine_version": INTELLIGENCE_ENGINE_VERSION,
                "design_id": design.design_id,
                "candidate_plan_id": candidate.candidate_plan_id,
            },
            limitations=(
                "Coverage means a requested field or modality was present in returned observation metadata; it is not scientific sufficiency.",
                "Spatial and temporal compliance cannot be confirmed by metadata presence alone and are reported as indeterminate.",
                "Reported conflicts are passed through from perception fusion without reinterpreting them.",
                "Hypotheses remain unevaluated; no calibrated confidence or causal effect is inferred.",
            ),
        )

    def _candidate_strategy(
        self,
        plan: InvestigationPlan,
        candidate: CandidateInvestigationPlan,
    ) -> CandidateEvidenceStrategy:
        items = tuple(
            self._strategy_item(requirement, candidate)
            for requirement in plan.required_evidence
        )
        if plan.status == "no_capability" or not candidate.selected_implementations:
            status = "unexecutable"
        elif all(item.status == "planned" for item in items):
            status = "ready_for_acquisition"
        else:
            status = "incomplete"
        limitations = ()
        if candidate.perception_plan.unavailable_variables or candidate.perception_plan.unavailable_modalities:
            limitations = (
                "Capability selection reports unavailable requested targets; this strategy must not be executed as a complete investigation.",
            )
            if status == "ready_for_acquisition":
                status = "incomplete"
        return CandidateEvidenceStrategy(
            candidate_plan_id=candidate.candidate_plan_id,
            step_ids=tuple(step.step_id for step in candidate.steps),
            requirements=items,
            status=status,
            limitations=limitations,
        )

    @staticmethod
    def _strategy_item(
        requirement: EvidenceRequirement,
        candidate: CandidateInvestigationPlan,
    ) -> EvidenceStrategyItem:
        matching_steps = []
        for step in candidate.steps:
            if requirement.evidence_type == "variable" and requirement.target in step.requested_variables:
                matching_steps.append(step.step_id)
            elif requirement.evidence_type == "modality" and requirement.target in step.requested_modalities:
                matching_steps.append(step.step_id)
            elif requirement.evidence_type == "spatial_scope" and (
                step.earth_query.point or step.earth_query.bbox or step.earth_query.geometry or step.earth_query.region
            ):
                matching_steps.append(step.step_id)
            elif requirement.evidence_type == "temporal_scope" and (
                step.earth_query.temporal_start or step.earth_query.temporal_end
            ):
                matching_steps.append(step.step_id)
        if matching_steps:
            status = "planned"
            explanation = "Requirement is explicitly represented by the linked EarthQuery step(s)."
        else:
            status = "unaddressed"
            explanation = "No candidate observation step explicitly covers this requirement."
        return EvidenceStrategyItem(
            requirement=requirement,
            supporting_step_ids=tuple(matching_steps),
            status=status,
            explanation=explanation,
        )

    def _assess_requirement(
        self,
        requirement: EvidenceRequirement,
        observations: tuple[Observation, ...],
        results: tuple[PerceptionResult, ...],
    ) -> EvidenceRequirementAssessment:
        evidence_type = requirement.evidence_type
        target = requirement.target
        if evidence_type in {"spatial_scope", "temporal_scope"}:
            return EvidenceRequirementAssessment(
                requirement_id=requirement.requirement_id,
                evidence_type=evidence_type,
                target=target,
                status="indeterminate",
                explanation="Returned geometry/time metadata cannot establish that the requested scope was completely covered.",
            )

        matches = []
        for observation in observations:
            if evidence_type == "modality":
                matched = target in observation.modalities
            else:
                matched = any(
                    self._same_variable(target, source_name)
                    and _has_measurement_value(observation.measured_variables[source_name])
                    for source_name in observation.measured_variables
                )
            if matched:
                matches.append(observation.observation_id)

        if matches:
            status = "observed"
            explanation = "At least one returned observation declares this requested variable or modality."
        elif not observations and results and all(result.status == "complete" for result in results):
            status = "missing"
            explanation = "Acquisition completed but returned no observations for this requirement."
        elif observations and any(result.status != "complete" for result in results):
            status = "indeterminate"
            explanation = "Acquisition was partial or failed; absence cannot be treated as evidence of absence."
        elif observations:
            status = "missing"
            explanation = "Returned observations do not declare this requested variable or modality."
        else:
            status = "indeterminate"
            explanation = "No complete acquisition record is available to assess this requirement."

        return EvidenceRequirementAssessment(
            requirement_id=requirement.requirement_id,
            evidence_type=evidence_type,
            target=target,
            status=status,
            observation_ids=tuple(sorted(matches)),
            explanation=explanation,
        )

    def _same_variable(self, requested: str, observed: str) -> bool:
        left = self.ontology.resolve_variable(requested)
        right = self.ontology.resolve_variable(observed)
        if left is not None and right is not None:
            return left.canonical_name == right.canonical_name
        return requested.casefold().replace(" ", "_") == observed.casefold().replace(" ", "_")


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _design_graph(
    plan: InvestigationPlan,
    strategies: tuple[CandidateEvidenceStrategy, ...],
) -> InvestigationEvidenceGraph:
    nodes: dict[str, InvestigationEvidenceNode] = {}
    edges: dict[tuple[str, str, str], InvestigationEvidenceEdge] = {}

    def add_node(node: InvestigationEvidenceNode) -> None:
        nodes[node.node_id] = node

    def add_edge(source: str, target: str, relation: str, basis: dict[str, Any]) -> None:
        edge = InvestigationEvidenceEdge(
            source_node_id=source,
            target_node_id=target,
            relation=relation,
            basis=basis,
        )
        edges[(source, target, relation)] = edge

    plan_node = f"plan:{plan.plan_id}"
    add_node(InvestigationEvidenceNode(
        node_id=plan_node,
        node_type="investigation_plan",
        label=plan.question,
        source_reference=plan.plan_id,
    ))

    for hypothesis in plan.hypotheses:
        hypothesis_node = f"hypothesis:{_stable_id(hypothesis.source_text + hypothesis.statement)}"
        add_node(InvestigationEvidenceNode(
            node_id=hypothesis_node,
            node_type="hypothesis",
            label=hypothesis.statement,
            source_reference=hypothesis.source_text,
            attributes={"origin": hypothesis.origin, "status": "unassessed"},
        ))
        add_edge(plan_node, hypothesis_node, "records", {"basis": "request extraction"})

    for requirement in plan.required_evidence:
        requirement_node = f"requirement:{requirement.requirement_id}"
        add_node(InvestigationEvidenceNode(
            node_id=requirement_node,
            node_type="evidence_requirement",
            label=requirement.target,
            source_reference=requirement.requirement_id,
            attributes={"evidence_type": requirement.evidence_type, "required": requirement.required},
        ))
        add_edge(plan_node, requirement_node, "requires", {"basis": "investigation plan contract"})

    for strategy in strategies:
        candidate_node = f"candidate:{strategy.candidate_plan_id}"
        add_node(InvestigationEvidenceNode(
            node_id=candidate_node,
            node_type="candidate_strategy",
            label=strategy.candidate_plan_id,
            source_reference=strategy.candidate_plan_id,
            attributes={"status": strategy.status},
        ))
        add_edge(plan_node, candidate_node, "contains", {"basis": "capability candidate"})
        for item in strategy.requirements:
            requirement_node = f"requirement:{item.requirement.requirement_id}"
            for step_id in item.supporting_step_ids:
                step_node = f"step:{strategy.candidate_plan_id}:{step_id}"
                if step_node not in nodes:
                    add_node(InvestigationEvidenceNode(
                        node_id=step_node,
                        node_type="observation_step",
                        label=step_id,
                        source_reference=step_id,
                        attributes={"candidate_plan_id": strategy.candidate_plan_id},
                    ))
                    add_edge(candidate_node, step_node, "contains", {"basis": "planned observation step"})
                add_edge(requirement_node, step_node, "planned_by", {
                    "requirement_id": item.requirement.requirement_id,
                    "mapping_status": item.status,
                })

    return InvestigationEvidenceGraph(
        nodes=tuple(nodes[key] for key in sorted(nodes)),
        edges=tuple(edges[key] for key in sorted(edges)),
    )


def _assessment_graph(
    *,
    design: InvestigationDesign,
    assessment_id: str,
    assessments: tuple[EvidenceRequirementAssessment, ...],
    observations: tuple[Observation, ...],
    conflicts: tuple[dict[str, Any], ...],
) -> InvestigationEvidenceGraph:
    nodes = {item.node_id: item for item in design.evidence_graph.nodes}
    edges = {
        (item.source_node_id, item.target_node_id, item.relation): item
        for item in design.evidence_graph.edges
    }

    def add_edge(source: str, target: str, relation: str, basis: dict[str, Any]) -> None:
        edge = InvestigationEvidenceEdge(
            source_node_id=source,
            target_node_id=target,
            relation=relation,
            basis=basis,
        )
        edges[(source, target, relation)] = edge

    assessment_node = f"assessment:{assessment_id}"
    nodes[assessment_node] = InvestigationEvidenceNode(
        node_id=assessment_node,
        node_type="assessment",
        label="Evidence coverage assessment",
        source_reference=assessment_id,
    )
    for observation in observations:
        observation_node = f"observation:{observation.observation_id}"
        nodes[observation_node] = InvestigationEvidenceNode(
            node_id=observation_node,
            node_type="observation",
            label=observation.source_id or observation.observation_id,
            source_reference=observation.observation_id,
            attributes={
                "dataset": observation.dataset.model_dump(mode="json") if observation.dataset else None,
                "provenance": dict(observation.provenance),
            },
        )
        add_edge(assessment_node, observation_node, "reports", {
            "basis": "execution result observation reference",
        })

    for assessment in assessments:
        requirement_node = f"requirement:{assessment.requirement_id}"
        for observation_id in assessment.observation_ids:
            observation_node = f"observation:{observation_id}"
            if observation_node in nodes:
                add_edge(requirement_node, observation_node, "observed_in", {
                    "assessment_status": assessment.status,
                    "basis": "declared measurement or modality metadata",
                })

    for index, conflict in enumerate(conflicts):
        encoded = json.dumps(conflict, sort_keys=True, default=str, separators=(",", ":"))
        conflict_node = f"conflict:{_stable_id(f'{assessment_id}:{index}:{encoded}')}"
        nodes[conflict_node] = InvestigationEvidenceNode(
            node_id=conflict_node,
            node_type="reported_conflict",
            label="Perception-reported conflict",
            source_reference=conflict_node,
            attributes={"source_conflict": conflict},
        )
        add_edge(assessment_node, conflict_node, "records", {
            "basis": "passed through from perception fusion",
        })
        related_ids = set()
        declared_ids = conflict.get("observation_ids", ())
        if isinstance(declared_ids, (list, tuple)):
            related_ids.update(value for value in declared_ids if isinstance(value, str))
        values = conflict.get("values", ())
        if isinstance(values, (list, tuple)):
            related_ids.update(
                value["observation_id"]
                for value in values
                if isinstance(value, dict) and isinstance(value.get("observation_id"), str)
            )
        for observation_id in sorted(related_ids):
            observation_node = f"observation:{observation_id}"
            if observation_node in nodes:
                add_edge(conflict_node, observation_node, "conflicts_with", {
                    "basis": "source conflict explicitly identifies observation",
                })

    return InvestigationEvidenceGraph(
        nodes=tuple(nodes[key] for key in sorted(nodes)),
        edges=tuple(edges[key] for key in sorted(edges)),
    )


def _has_measurement_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict) and "value" in value:
        return value["value"] is not None
    return True
