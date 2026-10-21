"""Provider-neutral lifecycle and evidence bookkeeping for scientific inference.

These services organize declarations and evidence. They do not assign trust,
independence, probability, or scientific meaning without explicit assessments.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from typing import Any, Iterable, Literal

from pydantic import Field, model_validator

from .contracts import Contract, Observation, utc_now
from .planning import CandidateHypothesis
from .scientific_methods import ScientificUncertainty


class HypothesisRecord(Contract):
    hypothesis_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    proposition: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    origin: Literal["explicit", "question_derived", "composite"]
    lifecycle: Literal[
        "proposed", "active", "under_review", "superseded", "withdrawn", "closed"
    ] = "proposed"
    competing_group_id: str | None = None
    parent_hypothesis_ids: tuple[str, ...] = ()
    composition: Literal["all", "any"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def composite_is_explicit(self) -> "HypothesisRecord":
        if self.origin == "composite":
            if len(self.parent_hypothesis_ids) < 2 or self.composition is None:
                raise ValueError(
                    "composite hypotheses require at least two parents and an explicit composition"
                )
        elif self.parent_hypothesis_ids or self.composition is not None:
            raise ValueError("only composite hypotheses may declare parent hypotheses")
        if len(self.parent_hypothesis_ids) != len(set(self.parent_hypothesis_ids)):
            raise ValueError("composite hypothesis parents must be unique")
        return self


class HypothesisLifecycleEvent(Contract):
    event_id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    prior_version: int = Field(ge=0)
    version: int = Field(ge=1)
    from_status: str | None = None
    to_status: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=utc_now)


class HypothesisGraph(Contract):
    hypotheses: tuple[HypothesisRecord, ...] = ()

    @model_validator(mode="after")
    def validate_hypothesis_graph(self) -> "HypothesisGraph":
        records = {item.hypothesis_id: item for item in self.hypotheses}
        if len(records) != len(self.hypotheses):
            raise ValueError("hypothesis identifiers must be unique in a graph")
        for item in self.hypotheses:
            if any(parent not in records for parent in item.parent_hypothesis_ids):
                raise ValueError("composite hypotheses must reference known parents")
            if item.hypothesis_id in item.parent_hypothesis_ids:
                raise ValueError("a hypothesis cannot depend on itself")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(hypothesis_id: str) -> None:
            if hypothesis_id in visiting:
                raise ValueError("hypothesis dependency graph must be acyclic")
            if hypothesis_id in visited:
                return
            visiting.add(hypothesis_id)
            for parent in records[hypothesis_id].parent_hypothesis_ids:
                visit(parent)
            visiting.remove(hypothesis_id)
            visited.add(hypothesis_id)

        for hypothesis_id in records:
            visit(hypothesis_id)
        return self

    def topological_order(self) -> tuple[HypothesisRecord, ...]:
        """Return a stable parent-before-child order for lifecycle registration."""
        pending = {item.hypothesis_id: item for item in self.hypotheses}
        registered: set[str] = set()
        ordered: list[HypothesisRecord] = []
        while pending:
            ready = sorted(
                hypothesis_id
                for hypothesis_id, item in pending.items()
                if set(item.parent_hypothesis_ids) <= registered
            )
            if not ready:
                raise ValueError("hypothesis graph cannot be ordered by its dependencies")
            for hypothesis_id in ready:
                ordered.append(pending.pop(hypothesis_id))
                registered.add(hypothesis_id)
        return tuple(ordered)


class HypothesisLifecycleLedger:
    """Append-only, optimistic-versioned in-memory hypothesis lifecycle."""

    _TRANSITIONS = {
        "proposed": {"active", "withdrawn"},
        "active": {"under_review", "withdrawn", "closed"},
        "under_review": {"active", "superseded", "withdrawn", "closed"},
        "superseded": {"closed"},
        "withdrawn": {"closed"},
        "closed": set(),
    }

    def __init__(self) -> None:
        self._records: dict[str, HypothesisRecord] = {}
        self._events: list[HypothesisLifecycleEvent] = []
        self._lock = threading.RLock()

    def add(self, record: HypothesisRecord, *, actor: str, rationale: str) -> None:
        with self._lock:
            if not actor.strip() or not rationale.strip():
                raise ValueError("hypothesis lifecycle events require actor and rationale")
            if record.hypothesis_id in self._records:
                raise ValueError(f"hypothesis already exists: {record.hypothesis_id}")
            if record.version != 1:
                raise ValueError("new hypotheses must begin at version 1")
            HypothesisGraph(
                hypotheses=(
                    *(self._records[key] for key in sorted(self._records)),
                    record,
                )
            )
            self._records[record.hypothesis_id] = record
            self._append_event(record, None, 0, actor, rationale)

    def transition(
        self,
        hypothesis_id: str,
        *,
        expected_version: int,
        status: str,
        actor: str,
        rationale: str,
    ) -> HypothesisRecord:
        with self._lock:
            if not actor.strip() or not rationale.strip():
                raise ValueError("hypothesis lifecycle events require actor and rationale")
            current = self._records[hypothesis_id]
            if current.version != expected_version:
                raise ValueError(
                    f"stale hypothesis version: expected {current.version}, received {expected_version}"
                )
            if status not in self._TRANSITIONS[current.lifecycle]:
                raise ValueError(
                    f"invalid hypothesis lifecycle transition: {current.lifecycle} -> {status}"
                )
            updated = current.model_copy(
                update={"version": current.version + 1, "lifecycle": status}
            )
            self._records[hypothesis_id] = updated
            self._append_event(updated, current.lifecycle, current.version, actor, rationale)
            return updated

    def restore_event(
        self, record: HypothesisRecord, event: HypothesisLifecycleEvent
    ) -> None:
        """Restore a recorded transition only when its prior state and identity match."""
        with self._lock:
            if event.hypothesis_id != record.hypothesis_id:
                raise ValueError("hypothesis event and record identities differ")
            if event.version != record.version or event.to_status != record.lifecycle:
                raise ValueError("hypothesis event does not describe the supplied record")
            expected_id = hashlib.sha256(
                json.dumps(
                    [
                        record.hypothesis_id,
                        event.version,
                        event.from_status,
                        event.to_status,
                        event.actor,
                        event.rationale,
                    ],
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if event.event_id != expected_id:
                raise ValueError("hypothesis event identity digest is invalid")

            current = self._records.get(record.hypothesis_id)
            if current is None:
                if (
                    event.version != 1
                    or event.prior_version != 0
                    or event.from_status is not None
                    or event.to_status != "proposed"
                ):
                    raise ValueError(
                        "hypothesis lifecycle history must start proposed at version 1"
                    )
                HypothesisGraph(
                    hypotheses=(*self._records.values(), record)
                )
            else:
                if (
                    event.prior_version != current.version
                    or event.version != current.version + 1
                    or event.from_status != current.lifecycle
                    or event.to_status not in self._TRANSITIONS[current.lifecycle]
                ):
                    raise ValueError("hypothesis lifecycle events are not a valid transition")
                prior_fields = current.model_dump(exclude={"version", "lifecycle"})
                restored_fields = record.model_dump(exclude={"version", "lifecycle"})
                if prior_fields != restored_fields:
                    raise ValueError("hypothesis identity or declared content changed in lifecycle")
                HypothesisGraph(
                    hypotheses=(
                        *(
                            record if key == record.hypothesis_id else value
                            for key, value in sorted(self._records.items())
                        ),
                    )
                )
            self._records[record.hypothesis_id] = record
            self._events.append(event)

    def graph(self) -> HypothesisGraph:
        with self._lock:
            return HypothesisGraph(
                hypotheses=tuple(self._records[key] for key in sorted(self._records))
            )

    def get(self, hypothesis_id: str) -> HypothesisRecord | None:
        with self._lock:
            return self._records.get(hypothesis_id)

    def events(self, hypothesis_id: str | None = None) -> tuple[HypothesisLifecycleEvent, ...]:
        with self._lock:
            return tuple(
                item
                for item in self._events
                if hypothesis_id is None or item.hypothesis_id == hypothesis_id
            )

    def _append_event(
        self,
        record: HypothesisRecord,
        from_status: str | None,
        prior_version: int,
        actor: str,
        rationale: str,
    ) -> None:
        event_id = hashlib.sha256(
            json.dumps(
                [record.hypothesis_id, record.version, from_status, record.lifecycle, actor, rationale],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._events.append(
            HypothesisLifecycleEvent(
                event_id=event_id,
                hypothesis_id=record.hypothesis_id,
                prior_version=prior_version,
                version=record.version,
                from_status=from_status,
                to_status=record.lifecycle,
                actor=actor,
                rationale=rationale,
            )
        )


class DatasetTrustAssertion(Contract):
    assertion_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    connector_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: str | None = None
    status: Literal["trusted_for_scope", "limited", "rejected"]
    scope_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    assessor: str = Field(min_length=1)
    reference_ids: tuple[str, ...] = ()


class ObservationIndependenceAssertion(Contract):
    assertion_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    observation_ids: tuple[str, str] = Field(min_length=2, max_length=2)
    group_id: str | None = None
    relation: Literal["independent", "dependent"]
    basis: str = Field(min_length=1)
    reference_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def pair_is_distinct(self) -> "ObservationIndependenceAssertion":
        if self.observation_ids[0] == self.observation_ids[1]:
            raise ValueError("independence assertions require two distinct observations")
        object.__setattr__(self, "observation_ids", tuple(sorted(self.observation_ids)))
        return self


class EvidenceUnitEvaluation(Contract):
    observation_id: str
    connector_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    dataset_trust: Literal["trusted_for_scope", "limited", "rejected", "not_assessed"]
    trust_basis: str | None = None
    trust_assertion_id: str | None = None
    trust_assertion_version: int | None = None
    trust_reference_ids: tuple[str, ...] = ()
    trusted_scope_ids: tuple[str, ...] = ()
    quality_status: Literal["valid", "invalid", "not_assessed"]
    quality_score: float | None = None
    independence: Literal["independent", "dependent", "unknown"]
    independence_group_ids: tuple[str, ...] = ()
    independence_basis: str | None = None
    independence_assertion_ids: tuple[str, ...] = ()
    independence_assertion_versions: tuple[int, ...] = ()
    independence_reference_ids: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    provenance_present: bool
    limitations: tuple[str, ...] = ()


class EvidenceEvaluationReport(Contract):
    units: tuple[EvidenceUnitEvaluation, ...] = ()
    modality_observation_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    declared_source_count: int = Field(ge=0)
    independence_assessed_count: int = Field(ge=0)
    statement: str
    limitations: tuple[str, ...] = ()


class EvidenceEvaluationEngine:
    """Expose evidence reliability dimensions without synthesizing a score."""

    def __init__(self) -> None:
        self.dataset_trust = DatasetTrustRegistry()
        self.observation_independence = ObservationIndependenceRegistry()

    def evaluate(
        self,
        observations: Iterable[Observation],
        *,
        dataset_trust: Iterable[DatasetTrustAssertion] | None = None,
        independence: Iterable[ObservationIndependenceAssertion] | None = None,
    ) -> EvidenceEvaluationReport:
        observations = tuple(observations)
        dataset_trust = tuple(dataset_trust) if dataset_trust is not None else self.dataset_trust.all()
        independence = (
            tuple(independence)
            if independence is not None
            else self.observation_independence.all()
        )
        trust = {
            (item.connector_id, item.dataset_id, item.dataset_version): item
            for item in dataset_trust
        }
        independent = {
            tuple(sorted(item.observation_ids)): item for item in independence
        }
        units: list[EvidenceUnitEvaluation] = []
        modality_ids: dict[str, list[str]] = {}
        sources: set[str] = set()
        for observation in observations:
            dataset = observation.dataset
            assertion = (
                trust.get((dataset.connector_id, dataset.dataset_id, dataset.version))
                or trust.get((dataset.connector_id, dataset.dataset_id, None))
                if dataset is not None
                else None
            )
            pair_assertions = [
                independent.get(tuple(sorted((observation.observation_id, other.observation_id))))
                for other in observations
                if other.observation_id != observation.observation_id
            ]
            declared_pairs = [item for item in pair_assertions if item is not None]
            independence_status = (
                "dependent"
                if any(item.relation == "dependent" for item in declared_pairs)
                else "independent"
                if len(declared_pairs) == max(0, len(observations) - 1)
                and declared_pairs
                and all(item.relation == "independent" for item in declared_pairs)
                else "unknown"
            )
            quality = observation.quality_assessment
            limitations: list[str] = []
            if assertion is None:
                limitations.append("Dataset trust has not been independently assessed.")
            if not declared_pairs:
                limitations.append("Observation independence has not been assessed.")
            if quality is None or quality.validation_status == "not_assessed":
                limitations.append("Observation quality has not been validated.")
            connector_id = dataset.connector_id if dataset else None
            dataset_id = dataset.dataset_id if dataset else None
            if connector_id and dataset_id:
                sources.add(f"{connector_id}:{dataset_id}")
            units.append(
                EvidenceUnitEvaluation(
                    observation_id=observation.observation_id,
                    connector_id=connector_id,
                    dataset_id=dataset_id,
                    dataset_version=dataset.version if dataset else None,
                    dataset_trust=assertion.status if assertion else "not_assessed",
                    trust_basis=assertion.basis if assertion else None,
                    trust_assertion_id=assertion.assertion_id if assertion else None,
                    trust_assertion_version=assertion.version if assertion else None,
                    trust_reference_ids=assertion.reference_ids if assertion else (),
                    trusted_scope_ids=(
                        (assertion.scope_id,)
                        if assertion and assertion.status == "trusted_for_scope"
                        else ()
                    ),
                    quality_status=(
                        quality.validation_status if quality else "not_assessed"
                    ),
                    quality_score=quality.quality_score if quality else None,
                    independence=independence_status,
                    independence_group_ids=tuple(
                        sorted(
                            {
                                item.group_id
                                for item in declared_pairs
                                if item.group_id is not None
                            }
                        )
                    ),
                    independence_basis="; ".join(
                        sorted({item.basis for item in declared_pairs})
                    )
                    or None,
                    independence_assertion_ids=tuple(
                        sorted(item.assertion_id for item in declared_pairs)
                    ),
                    independence_assertion_versions=tuple(
                        item.version
                        for item in sorted(declared_pairs, key=lambda value: value.assertion_id)
                    ),
                    independence_reference_ids=tuple(
                        sorted(
                            {
                                reference_id
                                for item in declared_pairs
                                for reference_id in item.reference_ids
                            }
                        )
                    ),
                    modalities=observation.modalities,
                    provenance_present=bool(observation.provenance),
                    limitations=tuple(limitations),
                )
            )
            for modality in observation.modalities:
                modality_ids.setdefault(modality, []).append(observation.observation_id)
        return EvidenceEvaluationReport(
            units=tuple(units),
            modality_observation_ids={
                key: tuple(sorted(values)) for key, values in sorted(modality_ids.items())
            },
            declared_source_count=len(sources),
            independence_assessed_count=sum(
                item.independence != "unknown" for item in units
            ),
            statement=(
                "Evidence dimensions are reported separately. Source count and modality diversity do not establish independence, agreement, reliability, or corroboration."
            ),
            limitations=(
                "No aggregate evidence score is calculated.",
                "Provider identity is not a proxy for source independence or dataset trust.",
            ),
        )


class DatasetTrustRegistry:
    """Versioned scoped assertions; registering one does not certify its basis."""

    def __init__(self) -> None:
        self._assertions: dict[tuple[str, str, str | None, int], DatasetTrustAssertion] = {}

    def register(self, assertion: DatasetTrustAssertion) -> None:
        key = (
            assertion.connector_id,
            assertion.dataset_id,
            assertion.dataset_version,
            assertion.version,
        )
        if key in self._assertions:
            raise ValueError("dataset trust assertion version already registered")
        self._assertions[key] = assertion

    def all(self) -> tuple[DatasetTrustAssertion, ...]:
        keys = sorted(
            self._assertions,
            key=lambda item: (item[0], item[1], item[2] or "", item[3]),
        )
        return tuple(self._assertions[key] for key in keys)


class ObservationIndependenceRegistry:
    """Versioned explicit dependence declarations keyed by observation identity."""

    def __init__(self) -> None:
        self._assertions: dict[tuple[str, str, int], ObservationIndependenceAssertion] = {}

    def register(self, assertion: ObservationIndependenceAssertion) -> None:
        key = (*tuple(sorted(assertion.observation_ids)), assertion.version)
        if key in self._assertions:
            raise ValueError("observation independence assertion version already registered")
        self._assertions[key] = assertion

    def all(self) -> tuple[ObservationIndependenceAssertion, ...]:
        return tuple(self._assertions[key] for key in sorted(self._assertions))


class UncertaintyComponent(Contract):
    component_id: str = Field(min_length=1)
    category: Literal[
        "measurement", "dataset", "model", "reasoning", "unclassified_observation"
    ]
    status: Literal["quantified", "partially_quantified", "not_quantified", "not_assessed"]
    source_id: str | None = None
    value: float | None = Field(default=None, ge=0)
    unit: str | None = None
    method_id: str | None = None
    method_version: str | None = None
    reference_ids: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def quantified_components_are_traceable(self) -> "UncertaintyComponent":
        if self.status == "quantified" and not all(
            (self.value is not None, self.unit, self.method_id, self.method_version)
        ):
            raise ValueError(
                "quantified uncertainty components require value, unit, and method version"
            )
        return self


class UncertaintyBudget(Contract):
    components: tuple[UncertaintyComponent, ...] = ()
    propagation_status: Literal["not_performed", "partially_performed", "performed"] = "not_performed"
    propagation_method_id: str | None = None
    propagation_method_version: str | None = None
    statement: str


class UncertaintyBudgetEngine:
    """Inventory uncertainty declarations without guessing their semantics."""

    def build(
        self,
        observations: Iterable[Observation],
        rule_uncertainties: Iterable[tuple[str, ScientificUncertainty]],
    ) -> UncertaintyBudget:
        components: list[UncertaintyComponent] = []
        for observation in observations:
            components.append(
                UncertaintyComponent(
                    component_id=f"measurement:{observation.observation_id}",
                    category="measurement",
                    status="not_assessed",
                    source_id=observation.observation_id,
                    source_metadata={},
                )
            )
            if observation.uncertainty:
                components.append(
                    UncertaintyComponent(
                        component_id=f"unclassified-observation:{observation.observation_id}",
                        category="unclassified_observation",
                        status="not_quantified",
                        source_id=observation.observation_id,
                        source_metadata=dict(observation.uncertainty),
                    )
                )
            components.append(
                UncertaintyComponent(
                    component_id=f"dataset:{observation.observation_id}",
                    category="dataset",
                    status="not_assessed",
                    source_id=(
                        f"{observation.dataset.connector_id}:{observation.dataset.dataset_id}"
                        if observation.dataset
                        else observation.observation_id
                    ),
                    source_metadata=(
                        dict(observation.dataset.metadata) if observation.dataset else {}
                    ),
                )
            )
        for source_id, uncertainty in rule_uncertainties:
            category = "model" if source_id.startswith("rule:") else "reasoning"
            components.append(
                UncertaintyComponent(
                    component_id=f"{category}:{source_id}",
                    category=category,
                    status=(
                        uncertainty.status
                        if uncertainty.status != "not_applicable"
                        else "not_assessed"
                    ),
                    source_id=source_id,
                    value=uncertainty.standard_uncertainty,
                    unit=uncertainty.unit,
                    method_id=uncertainty.method_id,
                    method_version=uncertainty.method_version,
                    reference_ids=uncertainty.reference_ids,
                    assumptions=uncertainty.assumptions,
                    source_metadata={
                        "distribution": uncertainty.distribution,
                        "reason": uncertainty.reason,
                        "observation_ids": uncertainty.observation_ids,
                    },
                )
            )
        quantified = [item for item in components if item.status == "quantified"]
        return UncertaintyBudget(
            components=tuple(components),
            propagation_status="not_performed",
            statement=(
                f"Recorded {len(components)} uncertainty components; {len(quantified)} are explicitly quantified. No values were combined because no registered method declared compatible units, distributions, dependencies, and propagation semantics."
            ),
        )


class AlternativeExplanation(Contract):
    hypothesis_id: str
    proposition: str
    status: Literal["unresolved", "has_directional_findings", "not_evaluated"]
    supporting_finding_ids: tuple[str, ...] = ()
    contradicting_finding_ids: tuple[str, ...] = ()
    unresolved_reason: str | None = None


class AlternativeExplanationSet(Contract):
    competing_group_id: str
    alternatives: tuple[AlternativeExplanation, ...] = ()
    interpretation: str


class AlternativeExplanationEngine:
    """Report explicitly grouped alternatives; never invent propositions."""

    def evaluate(
        self,
        graph: HypothesisGraph,
        findings: Iterable[dict[str, Any]],
    ) -> tuple[AlternativeExplanationSet, ...]:
        grouped: dict[str, list[HypothesisRecord]] = {}
        for hypothesis in graph.hypotheses:
            if hypothesis.competing_group_id:
                grouped.setdefault(hypothesis.competing_group_id, []).append(hypothesis)
        finding_list = tuple(findings)
        output = []
        for group_id, hypotheses in sorted(grouped.items()):
            alternatives = []
            for hypothesis in sorted(hypotheses, key=lambda item: item.hypothesis_id):
                related = [
                    item
                    for item in finding_list
                    if item.get("hypothesis_statement") == hypothesis.proposition
                ]
                supports = tuple(
                    sorted(
                        str(item["finding_id"])
                        for item in related
                        if item.get("evidential_relation") == "supports"
                    )
                )
                contradicts = tuple(
                    sorted(
                        str(item["finding_id"])
                        for item in related
                        if item.get("evidential_relation") == "contradicts"
                    )
                )
                alternatives.append(
                    AlternativeExplanation(
                        hypothesis_id=hypothesis.hypothesis_id,
                        proposition=hypothesis.proposition,
                        status=(
                            "has_directional_findings"
                            if supports or contradicts
                            else "not_evaluated"
                            if not related
                            else "unresolved"
                        ),
                        supporting_finding_ids=supports,
                        contradicting_finding_ids=contradicts,
                        unresolved_reason=(
                            None
                            if supports or contradicts
                            else "No directional finding evaluates this alternative."
                        ),
                    )
                )
            output.append(
                AlternativeExplanationSet(
                    competing_group_id=group_id,
                    alternatives=tuple(alternatives),
                    interpretation=(
                        "These alternatives were explicitly grouped by the investigation author or planner. Their presence does not imply exhaustiveness, mutual exclusivity, or a ranking."
                    ),
                )
            )
        return tuple(output)


class RefinementRecommendation(Contract):
    recommendation_id: str
    requirement_id: str
    evidence_type: str
    target: str
    action: Literal["acquire_observation", "clarify_scope", "inspect_capabilities"]
    rationale: str
    dataset_selection: Literal["deferred_to_capability_planning"] = "deferred_to_capability_planning"
    modality_selection: Literal["not_inferred"] = "not_inferred"


class InvestigationRefinementEngine:
    """Translate explicit evidence gaps into bounded next actions."""

    def recommend(self, gaps: Iterable[Any]) -> tuple[RefinementRecommendation, ...]:
        recommendations = []
        for gap in gaps:
            action = (
                "acquire_observation"
                if gap.evidence_type in {"variable", "modality", "temporal_support", "spatial_support"}
                else "inspect_capabilities"
                if gap.evidence_type == "dataset_metadata"
                else "clarify_scope"
            )
            recommendation_id = hashlib.sha256(
                f"{gap.requirement_id}:{gap.evidence_type}:{gap.target}:{gap.status}".encode()
            ).hexdigest()[:24]
            recommendations.append(
                RefinementRecommendation(
                    recommendation_id=recommendation_id,
                    requirement_id=gap.requirement_id,
                    evidence_type=gap.evidence_type,
                    target=gap.target,
                    action=action,
                    rationale=gap.explanation,
                )
            )
        return tuple(sorted(recommendations, key=lambda item: item.recommendation_id))


def hypothesis_graph_from_candidates(
    candidates: Iterable[CandidateHypothesis],
) -> HypothesisGraph:
    records = []
    for candidate in candidates:
        identifier = hashlib.sha256(
            json.dumps(
                [candidate.origin, candidate.source_text, candidate.statement],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        records.append(
            HypothesisRecord(
                hypothesis_id=identifier,
                proposition=candidate.statement,
                source_text=candidate.source_text,
                origin=candidate.origin,
                lifecycle="active",
            )
        )
    return HypothesisGraph(hypotheses=tuple(records))
