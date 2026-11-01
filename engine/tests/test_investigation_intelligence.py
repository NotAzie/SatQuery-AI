from datetime import datetime, timezone

from satquery.platform.contracts import Observation, PerceptionResult
from satquery.platform.intelligence import InvestigationIntelligenceEngine
from satquery.platform.runtime import PlatformRuntime


def _runtime() -> PlatformRuntime:
    runtime = PlatformRuntime()
    runtime.investigation_planner.clock = lambda: datetime(
        2025, 3, 12, 12, 0, tzinfo=timezone.utc
    )
    return runtime


def test_design_traces_evidence_requirements_to_observation_steps():
    runtime = _runtime()
    plan = runtime.investigation_planner.plan(
        "Measure air temperature globally during 2024"
    )

    design = runtime.investigation_intelligence.design(plan)

    assert design.plan_id == plan.plan_id
    strategy = design.candidate_strategies[0]
    variable_item = next(
        item for item in strategy.requirements
        if item.requirement.evidence_type == "variable"
    )
    assert variable_item.status == "planned"
    assert variable_item.supporting_step_ids
    assert strategy.status == "unexecutable"  # no registered acquisition implementation
    assert design.evidence_policy == "declared_requirement_coverage_only"
    node_ids = {node.node_id for node in design.evidence_graph.nodes}
    assert all(
        edge.source_node_id in node_ids and edge.target_node_id in node_ids
        for edge in design.evidence_graph.edges
    )
    assert "supports_hypothesis" not in {
        edge.relation for edge in design.evidence_graph.edges
    }


def test_assessment_reports_coverage_without_assessing_scientific_truth():
    runtime = _runtime()
    plan = runtime.investigation_planner.plan(
        "Test whether air temperature is elevated globally during 2024"
    )
    design = InvestigationIntelligenceEngine().design(plan)
    candidate = plan.candidate_plans[0]
    observation = Observation(
        observation_id="obs-1",
        measured_variables={"air_temperature": {"value": 292.0, "unit": "K"}},
        modalities=("atmospheric",),
    )
    result = PerceptionResult(
        query_fingerprint="query-1",
        observations=(observation,),
        conflicts=({"kind": "source_conflict", "variable": "air_temperature"},),
        status="complete",
    )

    assessment = InvestigationIntelligenceEngine().assess(
        design, candidate, (result,)
    )

    variable = next(
        item for item in assessment.requirements
        if item.evidence_type == "variable"
    )
    temporal = next(
        item for item in assessment.requirements
        if item.evidence_type == "temporal_scope"
    )
    assert variable.status == "observed"
    assert variable.observation_ids == ("obs-1",)
    assert temporal.status == "indeterminate"
    assert assessment.hypotheses[0].status == "not_evaluated"
    assert assessment.reported_conflicts == result.conflicts
    assert "confidence" in " ".join(assessment.limitations)
    requirement_id = next(
        item.requirement_id for item in assessment.requirements
        if item.evidence_type == "variable"
    )
    assert any(
        edge.source_node_id == f"requirement:{requirement_id}"
        and edge.target_node_id == "observation:obs-1"
        and edge.relation == "observed_in"
        for edge in assessment.evidence_graph.edges
    )
