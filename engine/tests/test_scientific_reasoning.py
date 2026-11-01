from datetime import datetime, timezone

import pytest

from satquery.platform.contracts import Observation, PerceptionResult
from satquery.platform.intelligence import (
    HypothesisStrategy,
    InvestigationIntelligenceEngine,
)
from satquery.platform.normalization import SemanticNormalizer
from satquery.platform.reasoning import (
    OperatorRegistry,
    MeasurementAgreementCriterion,
    ObservationAgreementOperator,
    ReasoningContext,
    ScientificReasoningEngine,
    ScientificRuleResult,
    RuleRegistry,
)
from satquery.platform.scientific_methods import ScientificRuleManifest
from satquery.platform.scientific_inference import (
    DatasetTrustAssertion,
    EvidenceEvaluationEngine,
    HypothesisGraph,
    HypothesisLifecycleLedger,
    HypothesisRecord,
    ObservationIndependenceAssertion,
)
from satquery.platform.contracts import DatasetReference
from satquery.platform.runtime import PlatformRuntime


def _prepared_context():
    runtime = PlatformRuntime()
    runtime.investigation_planner.clock = lambda: datetime(
        2025, 3, 12, 12, 0, tzinfo=timezone.utc
    )
    plan = runtime.investigation_planner.plan(
        "Test whether air temperature increased globally during 2024"
    )
    design = InvestigationIntelligenceEngine().design(plan)
    design = design.model_copy(
        update={
            "hypotheses": (
                HypothesisStrategy(
                    hypothesis={
                        "statement": "Air temperature increased.",
                        "source_text": "Air temperature increased.",
                        "origin": "explicit",
                    }
                ),
                HypothesisStrategy(
                    hypothesis={
                        "statement": "Air temperature did not increase.",
                        "source_text": "Air temperature did not increase.",
                        "origin": "explicit",
                    }
                ),
            )
        }
    )
    observation = SemanticNormalizer().harmonize_observation(
        Observation(
            observation_id="obs-a",
            measured_variables={"air_temperature": {"value": 292.0, "unit": "K"}},
            modalities=("atmospheric",),
            provenance={"source": "declared-test-source"},
        )
    )
    perception = PerceptionResult(
        query_fingerprint="query-a",
        observations=(observation,),
        conflicts=({"kind": "reported_conflict", "first_observation_id": "obs-a"},),
        status="complete",
    )
    assessment = InvestigationIntelligenceEngine().assess(
        design, plan.candidate_plans[0], (perception,)
    )
    return ReasoningContext(
        investigation_id="investigation-a",
        observations=(observation,),
        design=design,
        assessment=assessment,
    )


def test_default_engine_preserves_competing_hypotheses_without_claiming_truth():
    report = ScientificReasoningEngine().evaluate(_prepared_context())

    assert len(report.hypothesis_evaluations) == 2
    assert all(item.status == "not_evaluated" for item in report.hypothesis_evaluations)
    assert report.findings == ()
    assert report.conclusion.status == "unresolved"
    assert report.conclusion.confidence is None
    assert report.conclusion.missing_evidence_details
    assert report.observation_ids == ("obs-a",)
    assert report.reproducibility["engine_version"] == report.engine_version
    assert report.hypothesis_graph.hypotheses
    assert report.evidence_evaluation.units[0].independence == "unknown"
    assert report.uncertainty_budget.propagation_status == "not_performed"
    assert report.refinement_recommendations
    assert any(
        item.operator_id == "satquery.observation-conflicts"
        for item in report.operator_results
    )


def test_hypothesis_lifecycle_is_versioned_and_append_only():
    ledger = HypothesisLifecycleLedger()
    record = HypothesisRecord(
        hypothesis_id="hypothesis-1",
        proposition="Surface water expanded.",
        source_text="The question explicitly proposed expansion.",
        origin="explicit",
    )
    ledger.add(record, actor="researcher", rationale="Preregistered proposition.")
    active = ledger.transition(
        record.hypothesis_id,
        expected_version=1,
        status="active",
        actor="researcher",
        rationale="Investigation approved.",
    )

    assert active.version == 2
    assert active.lifecycle == "active"
    assert [event.version for event in ledger.events()] == [1, 2]
    assert ledger.events()[-1].from_status == "proposed"
    try:
        ledger.transition(
            record.hypothesis_id,
            expected_version=1,
            status="withdrawn",
            actor="researcher",
            rationale="Stale update must fail.",
        )
    except ValueError as exc:
        assert "stale hypothesis version" in str(exc)
    else:
        raise AssertionError("stale hypothesis update was accepted")


def test_hypothesis_lifecycle_events_restore_exact_history_and_reject_tampering():
    import hashlib
    import json

    original = HypothesisLifecycleLedger()
    record = HypothesisRecord(
        hypothesis_id="persistent-hypothesis",
        proposition="Surface water expanded.",
        source_text="The question explicitly proposed expansion.",
        origin="explicit",
    )
    original.add(record, actor="researcher", rationale="Preregistered.")
    active = original.transition(
        record.hypothesis_id,
        expected_version=1,
        status="active",
        actor="researcher",
        rationale="Approved for evaluation.",
    )

    restored = HypothesisLifecycleLedger()
    restored.restore_event(record, original.events()[0])
    restored.restore_event(active, original.events()[1])

    assert restored.graph() == original.graph()
    assert restored.events() == original.events()

    tampered = active.model_copy(update={"proposition": "A different proposition."})
    tampered_restore = HypothesisLifecycleLedger()
    tampered_restore.restore_event(record, original.events()[0])
    with pytest.raises(ValueError, match="identity or declared content changed"):
        tampered_restore.restore_event(tampered, original.events()[1])

    invalid_initial = HypothesisLifecycleLedger()
    proposed_event = original.events()[0]
    active_record = record.model_copy(update={"lifecycle": "active"})
    invalid_initial_event = proposed_event.model_copy(
        update={
            "to_status": "active",
            "event_id": hashlib.sha256(
                json.dumps(
                    [record.hypothesis_id, 1, None, "active", "researcher", "Preregistered."],
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
    )
    with pytest.raises(ValueError, match="must start proposed"):
        invalid_initial.restore_event(active_record, invalid_initial_event)


def test_hypothesis_graph_orders_composites_after_parents_deterministically():
    graph = HypothesisGraph(
        hypotheses=(
            HypothesisRecord(
                hypothesis_id="z-composite",
                proposition="Both conditions hold.",
                source_text="Explicit conjunction.",
                origin="composite",
                parent_hypothesis_ids=("a-parent", "b-parent"),
                composition="all",
            ),
            HypothesisRecord(
                hypothesis_id="b-parent",
                proposition="Condition B holds.",
                source_text="Explicitly proposed.",
                origin="explicit",
            ),
            HypothesisRecord(
                hypothesis_id="a-parent",
                proposition="Condition A holds.",
                source_text="Explicitly proposed.",
                origin="explicit",
            ),
        )
    )

    assert tuple(item.hypothesis_id for item in graph.topological_order()) == (
        "a-parent",
        "b-parent",
        "z-composite",
    )


def test_hypothesis_graph_rejects_unknown_parents_and_cycles():
    with pytest.raises(ValueError, match="known parents"):
        HypothesisGraph(
            hypotheses=(
                HypothesisRecord(
                    hypothesis_id="composite",
                    proposition="A and B",
                    source_text="explicit",
                    origin="composite",
                    parent_hypothesis_ids=("a", "b"),
                    composition="all",
                ),
            )
        )
    with pytest.raises(ValueError, match="acyclic"):
        HypothesisGraph(
            hypotheses=(
                HypothesisRecord(
                    hypothesis_id="a",
                    proposition="A and B",
                    source_text="explicit",
                    origin="composite",
                    parent_hypothesis_ids=("b", "c"),
                    composition="all",
                ),
                HypothesisRecord(
                    hypothesis_id="b",
                    proposition="B and C",
                    source_text="explicit",
                    origin="composite",
                    parent_hypothesis_ids=("a", "c"),
                    composition="all",
                ),
                *(
                    HypothesisRecord(
                        hypothesis_id="c",
                        proposition="C",
                        source_text="explicit",
                        origin="explicit",
                    ),
                ),
            )
        )


def test_evidence_evaluation_keeps_trust_and_independence_explicit():
    context = _prepared_context()
    observation = context.observations[0].model_copy(
        update={
            "dataset": DatasetReference(
                connector_id="source-a",
                dataset_id="dataset-a",
                version="v1",
            )
        }
    )
    second_observation = Observation(observation_id="obs-independent")
    observations = (observation, second_observation)
    default_report = EvidenceEvaluationEngine().evaluate(observations)
    assert default_report.units[0].dataset_trust == "not_assessed"
    assert default_report.units[0].independence == "unknown"
    assessed = EvidenceEvaluationEngine().evaluate(
        observations,
        dataset_trust=(
            DatasetTrustAssertion(
                assertion_id="trust-assessment-1",
                version=1,
                connector_id="source-a",
                dataset_id="dataset-a",
                dataset_version="v1",
                status="trusted_for_scope",
                scope_id="air-temperature-calibration",
                scope="air temperature at the site",
                basis="Independent calibration review.",
                assessor="review-board",
                reference_ids=("calibration-report-1",),
            ),
        ),
        independence=(
            ObservationIndependenceAssertion(
                assertion_id="independence-assessment-1",
                version=1,
                observation_ids=(observation.observation_id, second_observation.observation_id),
                group_id="acquisition-1",
                relation="independent",
                basis="Distinct independently sampled instrument record.",
                reference_ids=("sampling-log-1",),
            ),
        ),
    )
    assert assessed.units[0].dataset_trust == "trusted_for_scope"
    assert all(item.independence == "independent" for item in assessed.units)
    assert "do not establish independence" in assessed.statement


def test_rule_declared_dataset_trust_scope_is_an_applicability_precondition():
    context = _prepared_context()
    observation = context.observations[0].model_copy(
        update={
            "dataset": DatasetReference(
                connector_id="source-a",
                dataset_id="dataset-a",
                version="v1",
            )
        }
    )
    context = context.model_copy(update={"observations": (observation,)})

    class TrustScopedRule:
        manifest = ScientificRuleManifest(
            rule_id="test.trust-scoped-rule",
            version="1.0.0",
            name="Trust scoped fixture",
            domain="test-only",
            description="Requires an explicit scoped dataset assessment.",
            validation_status="validated",
            implementation_sha256="e" * 64,
            scientific_references=(
                {
                    "reference_id": "trust-fixture-reference",
                    "title": "Synthetic test reference",
                    "citation": "Test-only.",
                    "uri": "urn:satquery:test:trust",
                },
            ),
            validation_record={
                "validation_id": "trust-fixture-validation",
                "validation_status": "validated",
                "validated_by": "unit-test",
                "validation_suite_id": "trust-fixture-suite",
                "validation_suite_sha256": "f" * 64,
                "implementation_sha256": "e" * 64,
                "reference_ids": ("trust-fixture-reference",),
            },
            dataset_compatibility={
                "required_trust_scope_ids": ("air-temperature-calibration",)
            },
            uncertainty_propagation={"status": "not_required"},
        )

        def evaluate(self, hypothesis, _context):
            return ScientificRuleResult(
                rule_id=self.manifest.rule_id,
                rule_version=self.manifest.version,
                hypothesis_statement=hypothesis.statement,
                status="evaluated",
                statement="Trust-scoped fixture finding.",
                evidential_relation="supports",
                observation_ids=(observation.observation_id,),
            )

    engine = ScientificReasoningEngine(
        rules=RuleRegistry((TrustScopedRule(),)),
        certification_check=lambda _method_id, _version: True,
    )
    report = engine.evaluate(context)
    assert report.findings == ()
    assert {item.status for item in report.rule_applicability} == {
        "insufficient_evidence"
    }

    engine.evidence_evaluation.dataset_trust.register(
        DatasetTrustAssertion(
            assertion_id="approved-trust",
            connector_id="source-a",
            dataset_id="dataset-a",
            dataset_version="v1",
            status="trusted_for_scope",
            scope_id="air-temperature-calibration",
            scope="air temperature calibration characteristics",
            basis="Explicit synthetic fixture declaration.",
            assessor="unit-test",
            reference_ids=("calibration-note",),
        )
    )
    trusted_report = engine.evaluate(context)
    assert len(trusted_report.findings) == 2
    assert all(
        unit.dataset_trust == "trusted_for_scope"
        for unit in trusted_report.evidence_evaluation.units
    )


def test_refinement_recommendations_only_restate_declared_gaps():
    context = _prepared_context()
    report = ScientificReasoningEngine().evaluate(context)
    recommendation_targets = {
        item.target for item in report.refinement_recommendations
    }
    gap_targets = {
        item.target for item in report.conclusion.missing_evidence_details
    }
    assert recommendation_targets == gap_targets
    assert all(
        item.dataset_selection == "deferred_to_capability_planning"
        and item.modality_selection == "not_inferred"
        for item in report.refinement_recommendations
    )


def test_semantic_measurement_retains_value_unit_source_and_observation_lineage():
    context = _prepared_context()
    measurement = context.observations[0].canonical_measurements[0]

    assert measurement.canonical_variable == "air_temperature"
    assert measurement.value == 292.0
    assert measurement.unit == "K"
    assert measurement.source_variable == "air_temperature"
    assert measurement.observation_id == "obs-a"
    assert measurement.semantic_status == "resolved"
    assert context.observations[0].provenance["source"] == "declared-test-source"


def test_registered_rule_finding_is_versioned_and_enriched_with_source_lineage():
    context = _prepared_context()

    class ExplicitFixtureRule:
        manifest = ScientificRuleManifest(
            rule_id="test.fixture-rule",
            version="1.0.0",
            name="Synthetic test rule",
            domain="test-only",
            description="A fixture that verifies evidence-trace wiring.",
            validation_status="validated",
            implementation_sha256="a" * 64,
            scientific_references=(
                {
                    "reference_id": "fixture-reference",
                    "title": "Synthetic fixture citation",
                    "citation": "Test-only, no scientific claim.",
                    "uri": "urn:satquery:test:fixture",
                },
            ),
            validation_record={
                "validation_id": "fixture-validation",
                "validation_status": "validated",
                "validated_by": "unit-test",
                "validation_suite_id": "test-scientific-reasoning",
                "validation_suite_sha256": "b" * 64,
                "implementation_sha256": "a" * 64,
                "reference_ids": ("fixture-reference",),
            },
            uncertainty_propagation={"status": "not_required"},
            required_evidence=(
                {
                    "requirement_id": "temperature-measurement",
                    "evidence_type": "variable",
                    "target": "air_temperature",
                    "minimum_observations": 1,
                    "rationale": "The rule requires a resolved temperature measurement.",
                },
            ),
        )

        def evaluate(self, hypothesis, _context):
            return ScientificRuleResult(
                rule_id=self.manifest.rule_id,
                rule_version=self.manifest.version,
                hypothesis_statement=hypothesis.statement,
                status="evaluated",
                statement="Fixture rule emitted a bounded finding.",
                evidential_relation="contextual",
                observation_ids=("obs-a",),
                parameters={"hypothesis": hypothesis.statement},
                limitations=("Synthetic test fixture; not a scientific rule.",),
            )

    engine = ScientificReasoningEngine(
        rules=RuleRegistry((ExplicitFixtureRule(),)),
        certification_check=lambda _method_id, _version: True,
    )
    report = engine.evaluate(context)

    assert len(report.findings) == 2
    assert all(item.rule_version == "1.0.0" for item in report.findings)
    assert all(item.evidential_relation == "contextual" for item in report.findings)
    assert all(
        not item.supporting_observation_ids for item in report.hypothesis_evaluations
    )
    assert all(
        item.status == "insufficient_evidence" for item in report.hypothesis_evaluations
    )
    assert report.conclusion.status == "unresolved"
    assert all(
        item.observation_provenance["obs-a"]["source"] == "declared-test-source"
        for item in report.findings
    )
    assert all(item.observation_uncertainty["obs-a"] == {} for item in report.findings)
    assert report.conclusion.confidence is None
    assert report.sufficiency.status == "method_inputs_satisfied"


def test_required_uncertainty_method_blocks_directional_finding_when_unavailable():
    context = _prepared_context()

    class RuleRequiringPropagation:
        manifest = ScientificRuleManifest(
            rule_id="test.requires-uncertainty",
            version="1.0.0",
            name="Uncertainty fixture",
            domain="test-only",
            description="Checks that declared propagation requirements are enforced.",
            validation_status="validated",
            implementation_sha256="c" * 64,
            scientific_references=(
                {
                    "reference_id": "uncertainty-reference",
                    "title": "Synthetic uncertainty fixture",
                    "citation": "Test-only, no scientific claim.",
                    "uri": "urn:satquery:test:uncertainty",
                },
            ),
            validation_record={
                "validation_id": "uncertainty-validation",
                "validation_status": "validated",
                "validated_by": "unit-test",
                "validation_suite_id": "test-uncertainty-gate",
                "validation_suite_sha256": "d" * 64,
                "implementation_sha256": "c" * 64,
                "reference_ids": ("uncertainty-reference",),
            },
            uncertainty_propagation={
                "status": "required",
                "method_id": "test.uncertainty-method",
                "method_version": "1.0.0",
            },
        )

        def evaluate(self, hypothesis, _context):
            return ScientificRuleResult(
                rule_id=self.manifest.rule_id,
                rule_version=self.manifest.version,
                hypothesis_statement=hypothesis.statement,
                status="evaluated",
                statement="Must be blocked before becoming a finding.",
                evidential_relation="supports",
                observation_ids=("obs-a",),
            )

    report = ScientificReasoningEngine(
        rules=RuleRegistry((RuleRequiringPropagation(),)),
        certification_check=lambda _method_id, _version: True,
    ).evaluate(context)

    assert report.findings == ()
    assert report.conclusion.status == "unresolved"
    assert {item.status for item in report.rule_evaluations} == {
        "insufficient_evidence"
    }
    assert any(
        "uncertainty" in item.statement.lower() for item in report.rule_evaluations
    )


def test_default_operators_report_alignment_and_measurement_preconditions_only():
    context = _prepared_context()
    first = context.observations[0].model_copy(
        update={
            "observed_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "bbox": (10.0, 10.0, 12.0, 12.0),
            "crs": "OGC:CRS84",
        }
    )
    second = SemanticNormalizer().harmonize_observation(
        Observation(
            observation_id="obs-b",
            observed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            bbox=(11.0, 11.0, 13.0, 13.0),
            crs="OGC:CRS84",
            measured_variables={"air_temperature": {"value": 293.0, "unit": "K"}},
        )
    )
    context = context.model_copy(update={"observations": (first, second)})

    report = ScientificReasoningEngine().evaluate(context)
    by_id = {item.operator_id: item for item in report.operator_results}

    measurement = by_id["satquery.measurement-compatibility"]
    assert measurement.status == "evaluated"
    assert measurement.diagnostics["comparable_groups"] == [
        {
            "variable": "air_temperature",
            "declared_unit": "K",
            "observation_ids": ["obs-a", "obs-b"],
        }
    ]
    temporal = by_id["satquery.temporal-alignment"]
    assert temporal.diagnostics["overlap_pairs"][0]["intervals_overlap"] is False
    spatial = by_id["satquery.spatial-alignment"]
    assert spatial.diagnostics["bbox_pairs"][0]["bboxes_intersect"] is True
    assert report.conclusion.status == "unresolved"


def test_measurement_agreement_requires_explicit_versioned_tolerance():
    context = _prepared_context()
    second = SemanticNormalizer().harmonize_observation(
        Observation(
            observation_id="obs-b",
            modalities=("hydrological",),
            measured_variables={"air_temperature": {"value": 293.0, "unit": "K"}},
        )
    )
    context = context.model_copy(update={"observations": (*context.observations, second)})

    unconfigured = ObservationAgreementOperator().evaluate(context)
    assert unconfigured.status == "insufficient_evidence"
    assert unconfigured.diagnostics["pairwise_comparisons"] == []

    operator = ObservationAgreementOperator(
        (
            MeasurementAgreementCriterion(
                criterion_id="fixture-temperature-agreement",
                version="1.0.0",
                canonical_variable="air_temperature",
                unit="K",
                absolute_tolerance=1.0,
                rationale="Synthetic criterion used only to verify operator wiring.",
                reference_ids=("fixture-method-note",),
            ),
        )
    )
    unaligned = operator.evaluate(context)
    assert unaligned.status == "insufficient_evidence"
    assert unaligned.diagnostics["pairwise_comparisons"] == []
    assert unaligned.diagnostics["alignment_blockers"][0]["reasons"] == [
        "spatial_support_unknown",
        "acquisition_time_unknown",
    ]
    assert "exact_spatiotemporal_support" in unaligned.requirement_ids
    reasoning_report = ScientificReasoningEngine(
        operators=OperatorRegistry((operator,))
    ).evaluate(context)
    assert any(
        item.requirement_id == "exact_spatiotemporal_support"
        and item.status == "indeterminate"
        for item in reasoning_report.conclusion.missing_evidence_details
    )
    assert any(
        item.evidence_type == "spatial_temporal_alignment"
        for item in reasoning_report.refinement_recommendations
    )

    support = {"type": "Point", "coordinates": [12.0, 45.0]}
    aligned_context = context.model_copy(
        update={
            "observations": tuple(
                item.model_copy(
                    update={
                        "geometry": support,
                        "crs": "OGC:CRS84",
                        "observed_at": datetime(2025, 3, 12, 12, tzinfo=timezone.utc),
                    }
                )
                for item in context.observations
            )
        }
    )
    configured = operator.evaluate(aligned_context)
    comparison = configured.diagnostics["pairwise_comparisons"][0]
    assert configured.status == "evaluated"
    assert comparison["within_declared_tolerance"] is True
    assert comparison["declared_modalities"] == [
        ["atmospheric"],
        ["hydrological"],
    ]
    assert "not independent corroboration" in configured.statement


def test_experimental_rule_is_inspectable_but_never_executed_for_a_conclusion():
    context = _prepared_context()

    class ExperimentalRule:
        manifest = ScientificRuleManifest(
            rule_id="test.experimental",
            version="0.1.0",
            name="Experimental fixture",
            domain="test-only",
            description="Must remain unavailable for scientific conclusions.",
            validation_status="experimental",
        )

        def evaluate(self, _hypothesis, _context):
            raise AssertionError("experimental rule must not execute")

    report = ScientificReasoningEngine(
        rules=RuleRegistry((ExperimentalRule(),))
    ).evaluate(context)

    assert report.conclusion.status == "unresolved"
    assert report.sufficiency.status == "not_assessable"
    assert {item.status for item in report.rule_applicability} == {"unvalidated"}
    assert {item.status for item in report.rule_evaluations} == {"not_applicable"}


def test_operator_failure_is_recorded_without_aborting_reasoning_report():
    context = _prepared_context()

    class BrokenOperator:
        operator_id = "test.broken-operator"
        version = "1.0.0"

        def evaluate(self, _context):
            raise RuntimeError("sensitive details must not be copied into report")

    report = ScientificReasoningEngine(
        operators=OperatorRegistry((BrokenOperator(),))
    ).evaluate(context)

    assert report.operator_results[0].status == "error"
    assert report.operator_results[0].statement.endswith(
        "RuntimeError; no scientific inference was produced."
    )
    assert "sensitive details" not in report.model_dump_json()
    assert report.conclusion.status == "unresolved"


def test_platform_certification_gate_rejects_self_declared_validated_rule():
    context = _prepared_context()

    class SelfDeclaredRule:
        manifest = ScientificRuleManifest(
            rule_id="test.self-declared", version="1.0.0", name="Self declared",
            domain="test", description="Validation metadata alone must not certify this rule.",
            validation_status="validated", implementation_sha256="1" * 64,
            scientific_references=({
                "reference_id": "test-ref", "title": "Test", "citation": "Test only.",
                "uri": "urn:satquery:test:governance",
            },),
            validation_record={
                "validation_id": "metadata-only", "validation_status": "validated",
                "validated_by": "manifest-author", "validation_suite_id": "declared-only",
                "validation_suite_sha256": "2" * 64, "implementation_sha256": "1" * 64,
                "reference_ids": ("test-ref",),
            },
            uncertainty_propagation={"status": "not_required"},
        )

        def evaluate(self, hypothesis, _context):
            return ScientificRuleResult(
                rule_id=self.manifest.rule_id, rule_version=self.manifest.version,
                hypothesis_statement=hypothesis.statement, status="evaluated",
                statement="Must never be reached.", evidential_relation="supports",
                observation_ids=("obs-a",),
            )

    report = ScientificReasoningEngine(
        rules=RuleRegistry((SelfDeclaredRule(),)),
    ).evaluate(context)
    assert report.findings == ()
    assert {item.status for item in report.rule_applicability} == {"unvalidated"}
    assert "platform certification" in report.rule_applicability[0].reasons[0]
