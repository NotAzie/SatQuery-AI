from __future__ import annotations

from datetime import datetime, timezone

from satquery.platform.contracts import EarthQuery, PerceptionPlan
from satquery.platform.runtime import PlatformRuntime


def _runtime() -> PlatformRuntime:
    runtime = PlatformRuntime()
    runtime.investigation_planner.clock = lambda: datetime(
        2025, 3, 12, 12, 0, tzinfo=timezone.utc
    )
    return runtime


def test_planner_extracts_ontology_terms_and_requests_unresolved_scope():
    plan = _runtime().investigation_planner.plan(
        "Map air temperature near Chennai during 2024"
    )

    assert plan.status == "needs_clarification"
    assert plan.objective.objective_type == "map"
    assert [item.canonical_variable for item in plan.variables] == ["air_temperature"]
    assert plan.geographic_entities[0].source_text == "Chennai"
    assert plan.geographic_entities[0].resolution == "unresolved"
    assert plan.time_interpretation.start == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert {item.field for item in plan.missing_information} == {"spatial_scope"}
    assert plan.assumptions[0].field == "timezone"


def test_planner_is_reproducible_for_fixed_request_clock_and_capabilities():
    runtime = _runtime()
    first = runtime.investigation_planner.plan("Map air temperature globally in 2024")
    second = runtime.investigation_planner.plan("Map air temperature globally in 2024")

    assert first.plan_id == second.plan_id
    assert first.reproducibility == second.reproducibility
    assert first.candidate_plans[0].earth_query.region == "*"
    assert first.time_interpretation.start == second.time_interpretation.start


def test_ambiguous_variable_yields_multiple_explicit_candidates():
    runtime = _runtime()
    plan = runtime.investigation_planner.plan(
        "Measure temperature near Chennai last 7 days"
    )

    assert plan.status == "needs_clarification"
    ambiguous = next(item for item in plan.variables if item.resolution == "ambiguous")
    assert set(ambiguous.candidate_variables) == {
        "air_temperature",
        "land_surface_temperature",
    }
    assert {item.selected_variables[0] for item in plan.candidate_plans} == set(
        ambiguous.candidate_variables
    )
    assert any(item.field == "variable_interpretation" for item in plan.missing_information)
    for candidate in plan.candidate_plans:
        expected_modalities = set(
            runtime.perception_engine.modality_registry.for_variables(
                candidate.selected_variables
            )
        )
        assert set(candidate.earth_query.requested_modalities) == expected_modalities
        assert all(
            set(step.earth_query.requested_modalities).issubset(expected_modalities)
            for step in candidate.steps
        )


def test_relative_hours_are_anchored_and_reproducible():
    plan = _runtime().investigation_planner.plan(
        "Measure air temperature globally for the last 6 hours"
    )

    assert plan.time_interpretation.resolution == "relative"
    assert plan.time_interpretation.end == datetime(2025, 3, 12, 12, 0, tzinfo=timezone.utc)
    assert plan.time_interpretation.start == datetime(2025, 3, 12, 6, 0, tzinfo=timezone.utc)
    assert plan.assumptions[0].field == "relative_time_anchor"


def test_partial_capability_does_not_make_investigation_executable():
    runtime = _runtime()

    def partial_coverage(query):
        selected = tuple(
            variable for variable in query.requested_variables
            if variable == "air_temperature"
        )
        return PerceptionPlan(
            requested_variables=query.requested_variables,
            selected_variables=selected,
            unavailable_variables=tuple(
                variable for variable in query.requested_variables
                if variable != "air_temperature"
            ),
            implementation_ids=("fixture-atmosphere",),
        )

    runtime.investigation_planner.capability_plan = partial_coverage
    plan = runtime.investigation_planner.plan(
        "Measure air temperature and precipitation globally in 2024",
        earth_query=EarthQuery(
            region="*",
            temporal_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            temporal_end=datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc),
            requested_variables=("air_temperature", "precipitation"),
        ),
    )

    assert plan.status == "no_capability"
    assert plan.candidate_plans[0].perception_plan.unavailable_variables == (
        "precipitation",
    )


def test_relative_time_and_hazard_domain_are_explicitly_interpreted():
    plan = _runtime().investigation_planner.plan(
        "Detect flooding globally last week"
    )

    assert plan.time_interpretation.resolution == "relative"
    assert plan.time_interpretation.start == datetime(2025, 3, 3, tzinfo=timezone.utc)
    assert plan.time_interpretation.end == datetime(2025, 3, 9, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert "hydrological" in plan.requested_modalities
    assert "disaster" in plan.requested_modalities
    assert {item.concept_id for item in plan.phenomena} >= {"flood"}
    assert plan.assumptions[0].field == "calendar_week_semantics"


def test_structured_query_is_preserved_and_part_of_reproducibility_digest():
    runtime = _runtime()
    query = EarthQuery(
        point=(80.15, 12.84),
        temporal_start=datetime(2025, 3, 1, tzinfo=timezone.utc),
        temporal_end=datetime(2025, 3, 2, tzinfo=timezone.utc),
        requested_variables=("air_temperature",),
    )
    plan = runtime.investigation_planner.plan("Review the temperature", earth_query=query)

    assert plan.candidate_plans[0].earth_query.point == query.point
    assert plan.candidate_plans[0].earth_query.temporal_start == query.temporal_start
    assert plan.geographic_entities[0].resolution == "explicit_coordinates"
    assert not plan.missing_information
    assert plan.status == "no_capability"
