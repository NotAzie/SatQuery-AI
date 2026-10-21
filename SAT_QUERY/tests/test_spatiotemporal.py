from datetime import datetime, timezone

from satquery.platform.contracts import (
    CanonicalMeasurement,
    DatasetReference,
    Observation,
)
from satquery.platform.spatiotemporal import (
    ConsecutiveTemporalDifferenceEngine,
    ExactSupportObservationStackBuilder,
)


def _sample(
    observation_id,
    day,
    *,
    value,
    support=None,
    unit="K",
    semantic_status="resolved",
):
    observed_at = (
        datetime(2025, 1, day, tzinfo=timezone.utc) if day is not None else None
    )
    return Observation(
        observation_id=observation_id,
        source_id=f"source-{observation_id}",
        dataset=DatasetReference(
            connector_id="sample-adapter", dataset_id="thermal-series"
        ),
        observed_at=observed_at,
        provenance={"satquery:asset_sampling": {"status": "sampled"}},
        uncertainty={},
        canonical_measurements=(CanonicalMeasurement(
            canonical_variable="surface_temperature",
            value=value,
            unit=unit,
            source_variable="LST",
            source_unit=unit,
            semantic_status=semantic_status,
            observation_id=observation_id,
            source_metadata={
                "sampling": "pixel_containing_point",
                "pixel_support_geometry": support or {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "pixel_support_crs": "OGC:CRS84",
            },
        ),),
    )


def test_builder_creates_deterministic_exact_support_time_series():
    builder = ExactSupportObservationStackBuilder()
    observations = (
        _sample("scene-b", 2, value=302.0),
        _sample("scene-a", 1, value=301.0),
    )

    first = builder.build(observations)
    second = builder.build(tuple(reversed(observations)))

    assert len(first.stacks) == 1
    stack = first.stacks[0]
    assert stack.stack_id == second.stacks[0].stack_id
    assert stack.canonical_variable == "surface_temperature"
    assert [member.observed_at.day for member in stack.members] == [1, 2]
    assert [member.value for member in stack.members] == [301.0, 302.0]
    assert all(member.uncertainty == {} for member in stack.members)
    assert stack.reproducibility["spatial_policy"] == (
        "exact_geometry_and_crs_no_resampling_or_reprojection"
    )
    assert not first.issues


def test_builder_does_not_stack_different_pixel_supports():
    second_support = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    }
    result = ExactSupportObservationStackBuilder().build((
        _sample("scene-a", 1, value=301.0),
        _sample("scene-b", 2, value=302.0, support=second_support),
    ))

    assert not result.stacks
    assert {issue.code for issue in result.issues} == {"support_not_shared"}


def test_builder_keeps_unresolved_variables_scoped_to_exact_dataset():
    first = _sample("scene-a", 1, value=301.0, semantic_status="unresolved")
    second = _sample("scene-b", 2, value=302.0, semantic_status="unresolved")

    result = ExactSupportObservationStackBuilder().build((first, second))

    assert len(result.stacks) == 1
    assert result.stacks[0].canonical_variable is None
    assert result.stacks[0].variable_key == (
        "source:sample-adapter:thermal-series:lst"
    )


def test_builder_refuses_unit_mismatch_and_missing_time():
    unit_result = ExactSupportObservationStackBuilder().build((
        _sample("scene-a", 1, value=301.0, unit="K"),
        _sample("scene-b", 2, value=28.0, unit="Cel"),
    ))
    time_result = ExactSupportObservationStackBuilder().build((
        _sample("scene-a", 1, value=301.0),
        _sample("scene-b", None, value=302.0),
    ))

    assert not unit_result.stacks
    assert {issue.code for issue in unit_result.issues} == {"unit_mismatch"}
    assert not time_result.stacks
    assert {issue.code for issue in time_result.issues} == {
        "missing_time", "insufficient_members"
    }


def test_builder_reports_acquired_scene_without_a_requested_measurement():
    empty_scene = Observation(
        observation_id="scene-empty",
        observed_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        provenance={
            "satquery:asset_sampling": {"requested_variables": ("LST",)}
        },
    )
    result = ExactSupportObservationStackBuilder().build((
        _sample("scene-valid", 1, value=301.0),
        empty_scene,
    ))

    assert not result.stacks
    assert {issue.code for issue in result.issues} == {
        "missing_measurement", "insufficient_members"
    }


def test_consecutive_difference_is_deterministic_descriptive_and_traceable():
    stack = ExactSupportObservationStackBuilder().build((
        _sample("scene-b", 2, value=302.0),
        _sample("scene-a", 1, value=301.0),
    )).stacks[0]
    engine = ConsecutiveTemporalDifferenceEngine()

    first, issues = engine.build((stack,))
    repeated, repeated_issues = engine.build((stack,))

    assert len(first) == 1
    diagnostic = first[0]
    assert diagnostic.diagnostic_id == repeated[0].diagnostic_id
    assert diagnostic.difference_value == 1.0
    assert diagnostic.elapsed_seconds == 24 * 60 * 60
    assert diagnostic.operation == "later_minus_earlier"
    assert diagnostic.interpretation_status == "descriptive_only"
    assert diagnostic.uncertainty_status == "not_propagated"
    assert diagnostic.earlier.provenance == stack.members[0].provenance
    assert diagnostic.later.source_measurement_metadata == stack.members[1].source_measurement_metadata
    assert diagnostic.reproducibility["scientific_interpretation"] == (
        "descriptive_only_no_trend_or_causal_inference"
    )
    assert not issues and not repeated_issues


def test_consecutive_difference_reports_non_finite_float_overflow():
    stack = ExactSupportObservationStackBuilder().build((
        _sample("scene-a", 1, value=-1e308),
        _sample("scene-b", 2, value=1e308),
    )).stacks[0]

    diagnostics, issues = ConsecutiveTemporalDifferenceEngine().build((stack,))

    assert not diagnostics
    assert len(issues) == 1
    assert issues[0].code == "non_finite_difference"


def test_consecutive_difference_refuses_unvalidated_cross_dataset_arithmetic():
    first = _sample("scene-a", 1, value=301.0)
    second = _sample("scene-b", 2, value=302.0).model_copy(update={
        "dataset": DatasetReference(
            connector_id="other-adapter", dataset_id="different-thermal-series"
        )
    })
    stack = ExactSupportObservationStackBuilder().build((first, second)).stacks[0]

    diagnostics, issues = ConsecutiveTemporalDifferenceEngine().build((stack,))

    assert not diagnostics
    assert len(issues) == 1
    assert issues[0].code == "dataset_mismatch"
    assert "validated compatibility method" in issues[0].message
