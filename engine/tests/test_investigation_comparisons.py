from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from satquery.api import create_app, set_engine
from satquery.config import get_settings
from satquery.orchestrator import SatQueryEngine
from satquery.platform.comparisons import (
    InvestigationComparisonRequest,
    compare_investigations,
)
from satquery.platform.contracts import (
    CanonicalMeasurement,
    DatasetReference,
    ExecutionResult,
    ExecutionStatus,
    Mission,
    Observation,
    ObservationAlignmentIssue,
    ObservationStack,
    ObservationStackMember,
    PerceptionResult,
    TaskExecution,
    TaskStatus,
)
from satquery.platform.earth_memory import EarthMemoryQuery
from satquery.platform.reports import build_investigation_report


def _record_observation(
    engine, investigation_id, *, value, observed_at, source_id, support=None,
    observation_id=None,
):
    runtime = engine.platform_runtime
    observation = Observation(
        source_id=source_id,
        **({"observation_id": observation_id} if observation_id is not None else {}),
        dataset=DatasetReference(connector_id="fixture", dataset_id="surface-water"),
        observed_at=observed_at,
        measured_variables={"provider_value": {"value": value, "unit": "m"}},
        geometry=support,
        crs="OGC:CRS84" if support is not None else None,
        canonical_measurements=(CanonicalMeasurement(
            canonical_variable="earth:surface_water_level",
            value=value,
            unit="m",
            source_variable="provider_value",
            source_unit="m",
            semantic_status="resolved",
            source_metadata={
                "mapping_id": "fixture-map-v1",
                **({
                    "observation_support_geometry": support,
                    "observation_support_crs": "OGC:CRS84",
                } if support is not None else {}),
            },
        ),),
        provenance={"record": source_id},
    )
    runtime.investigation_service.start(investigation_id)
    result = ExecutionResult(
        plan_id=f"execution-{source_id}",
        status=ExecutionStatus.SUCCEEDED,
        started_at=observed_at,
        tasks=(TaskExecution(
            task_id=f"task-{source_id}",
            status=TaskStatus.SUCCEEDED,
            attempts=1,
            duration_seconds=0,
            output=PerceptionResult(
                query_fingerprint=f"query-{source_id}",
            observations=(observation,),
                status="complete",
            ),
        ),),
    )
    runtime.record_execution_result(result, investigation_id=investigation_id)
    runtime.investigation_service.add_result(investigation_id, result.plan_id)
    runtime.investigation_service.complete(investigation_id, "Execution completed.")
    return observation


def test_comparison_aligns_exact_semantic_keys_and_preserves_unknown_science():
    engine = SatQueryEngine(get_settings())
    runtime = engine.platform_runtime
    mission = Mission(name="Reservoir", objective="Inspect water level records")
    runtime.mission_service.create(mission)
    first = runtime.mission_service.create_investigation(mission.mission_id)
    second = runtime.mission_service.create_investigation(mission.mission_id)
    first_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    second_time = datetime(2025, 2, 1, tzinfo=timezone.utc)
    first_observation = _record_observation(
        engine, first.investigation_id, value=2.1, observed_at=first_time, source_id="a"
    )
    second_observation = _record_observation(
        engine, second.investigation_id, value=1.7, observed_at=second_time, source_id="b"
    )

    report = build_investigation_report(runtime, first.investigation_id)
    assert "earth:surface_water_level" in report.markdown
    assert "value `2.1`" in report.markdown
    assert "Execution trace" in report.markdown
    assert first_observation.observation_id in report.markdown

    comparison = compare_investigations(
        runtime,
        InvestigationComparisonRequest(
            investigation_ids=(first.investigation_id, second.investigation_id)
        ),
    )

    assert len(comparison.measurement_groups) == 1
    group = comparison.measurement_groups[0]
    assert group.coverage == "present_in_all_selected_investigations"
    assert [item.value for item in group.records] == [2.1, 1.7]
    assert {item.observation_id for item in group.records} == {
        first_observation.observation_id,
        second_observation.observation_id,
    }
    assert "No trends, statistical tests, or scientific conclusions were generated." in comparison.markdown
    assert "causation" in group.interpretation


def test_comparison_emits_only_exact_support_descriptive_temporal_diagnostics():
    engine = SatQueryEngine(get_settings())
    runtime = engine.platform_runtime
    mission = Mission(name="Gauge", objective="Compare point-supported measurements")
    runtime.mission_service.create(mission)
    first = runtime.mission_service.create_investigation(mission.mission_id)
    second = runtime.mission_service.create_investigation(mission.mission_id)
    support = {"type": "Point", "coordinates": (72.0, 19.0)}
    records = (
        (first.investigation_id, 1.5, datetime(2025, 1, 1, tzinfo=timezone.utc), "before"),
        (second.investigation_id, 2.0, datetime(2025, 1, 2, tzinfo=timezone.utc), "after"),
    )
    for investigation_id, value, observed_at, source_id in records:
        _record_observation(
            engine, investigation_id, value=value, observed_at=observed_at,
            source_id=source_id, support=support,
        )
    comparison = compare_investigations(runtime, InvestigationComparisonRequest(
        investigation_ids=(first.investigation_id, second.investigation_id),
    ))

    assert len(comparison.observation_stacks) == 1
    assert comparison.stack_builder_version == "1.1.0"
    assert comparison.temporal_method_id == "satquery.temporal.consecutive-difference"
    assert len(comparison.temporal_diagnostics) == 1
    diagnostic = comparison.temporal_diagnostics[0]
    assert diagnostic.difference_value == 0.5
    assert diagnostic.uncertainty_status == "not_propagated"
    assert diagnostic.interpretation_status == "descriptive_only"
    assert "No trends, statistical tests, or scientific conclusions were generated." in comparison.markdown


def test_conflicting_observation_identity_is_reported_and_excluded_from_alignment():
    engine = SatQueryEngine(get_settings())
    runtime = engine.platform_runtime
    mission = Mission(name="Identity", objective="Check canonical record identity")
    runtime.mission_service.create(mission)
    first = runtime.mission_service.create_investigation(mission.mission_id)
    second = runtime.mission_service.create_investigation(mission.mission_id)
    support = {"type": "Point", "coordinates": (72.0, 19.0)}
    _record_observation(
        engine, first.investigation_id, value=1.0,
        observed_at=datetime(2025, 1, 1, tzinfo=timezone.utc), source_id="source-a",
        support=support, observation_id="reused-id",
    )
    _record_observation(
        engine, second.investigation_id, value=2.0,
        observed_at=datetime(2025, 1, 2, tzinfo=timezone.utc), source_id="source-b",
        support=support, observation_id="reused-id",
    )

    comparison = compare_investigations(runtime, InvestigationComparisonRequest(
        investigation_ids=(first.investigation_id, second.investigation_id),
    ))

    assert not comparison.observation_stacks
    assert comparison.observation_identity_conflicts[0]["observation_id"] == "reused-id"
    assert set(comparison.observation_identity_conflicts[0]["investigation_ids"]) == {
        first.investigation_id, second.investigation_id,
    }


def test_investigation_report_preserves_temporal_stacks_and_alignment_issues():
    engine = SatQueryEngine(get_settings())
    runtime = engine.platform_runtime
    mission = Mission(name="Thermal", objective="Inspect sampled temperature scenes")
    runtime.mission_service.create(mission)
    investigation = runtime.mission_service.create_investigation(mission.mission_id)
    first_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    second_time = datetime(2025, 2, 1, tzinfo=timezone.utc)
    first = Observation(
        observation_id="pixel-first",
        source_id="scene-first",
        observed_at=first_time,
        dataset=DatasetReference(connector_id="fixture", dataset_id="thermal"),
        provenance={"satquery:asset_sampling": {"status": "sampled"}},
    )
    second = first.model_copy(update={
        "observation_id": "pixel-second",
        "source_id": "scene-second",
        "observed_at": second_time,
    })
    pixel_support = {"type": "Point", "coordinates": (1.0, 2.0)}
    source_measurement_metadata = {
        "pixel_support_geometry": pixel_support,
        "pixel_support_crs": "OGC:CRS84",
    }
    stack = ObservationStack(
        stack_id="obs-stack:test",
        variable_key="canonical:surface_temperature",
        canonical_variable="surface_temperature",
        unit="K",
        spatial_support_geometry=pixel_support,
        spatial_support_crs="OGC:CRS84",
        spatial_alignment="exact_pixel_support",
        temporal_alignment="source_acquisition_time",
        members=(
            ObservationStackMember(
                observation_id=first.observation_id,
                source_id=first.source_id,
                dataset=first.dataset,
                observed_at=first_time,
                value=300.0,
                unit="K",
                source_variable="LST",
                source_measurement_metadata=source_measurement_metadata,
            ),
            ObservationStackMember(
                observation_id=second.observation_id,
                source_id=second.source_id,
                dataset=second.dataset,
                observed_at=second_time,
                value=301.0,
                unit="K",
                source_variable="LST",
                source_measurement_metadata=source_measurement_metadata,
            ),
        ),
    )
    runtime.investigation_service.start(investigation.investigation_id)
    execution = ExecutionResult(
        plan_id="stack-execution",
        status=ExecutionStatus.SUCCEEDED,
        started_at=first_time,
        tasks=(TaskExecution(
            task_id="stack-task",
            status=TaskStatus.SUCCEEDED,
            attempts=1,
            duration_seconds=0,
            output=PerceptionResult(
                query_fingerprint="stack-query",
                observations=(first, second),
                observation_stacks=(stack,),
                alignment_issues=(ObservationAlignmentIssue(
                    observation_id="pixel-other",
                    code="support_not_shared",
                    message="Fixture spatial support does not match.",
                ),),
            ),
        ),),
    )
    runtime.record_execution_result(execution, investigation_id=investigation.investigation_id)
    runtime.investigation_service.add_result(investigation.investigation_id, execution.plan_id)
    memory = runtime.search_earth_memory(EarthMemoryQuery(
        artifact_types=("observation_stack",),
        investigation_id=investigation.investigation_id,
    ))

    report = build_investigation_report(runtime, investigation.investigation_id)

    assert [item.artifact_type for item in memory.artifacts] == ["observation_stack"]
    assert memory.artifacts[0].source_artifact_ids
    assert [item.stack_id for item in report.observation_stacks] == [stack.stack_id]
    assert report.alignment_issues[0].code == "support_not_shared"
    assert "Spatial-temporal observation stacks" in report.markdown
    assert "Alignment blockers" in report.markdown
    assert "exact pixel support" in report.markdown
    assert len(report.observations) == 2


def test_comparison_api_rejects_duplicate_ids_and_renders_markdown():
    with pytest.raises(ValueError, match="unique"):
        InvestigationComparisonRequest(investigation_ids=("same", "same"))

    engine = SatQueryEngine(get_settings())
    runtime = engine.platform_runtime
    mission = Mission(name="Coast", objective="Inspect coastal observations")
    runtime.mission_service.create(mission)
    first = runtime.mission_service.create_investigation(mission.mission_id)
    second = runtime.mission_service.create_investigation(mission.mission_id)
    support = {"type": "Point", "coordinates": (72.0, 19.0)}
    _record_observation(
        engine, first.investigation_id, value=12,
        observed_at=datetime(2025, 1, 1, tzinfo=timezone.utc), source_id="one",
        support=support,
    )
    _record_observation(
        engine, second.investigation_id, value=13,
        observed_at=datetime(2025, 1, 2, tzinfo=timezone.utc), source_id="two",
        support=support,
    )
    set_engine(engine)
    try:
        client = TestClient(create_app(get_settings()))
        response = client.post(
            "/api/v1/platform/investigation-comparisons",
            json={"investigation_ids": [first.investigation_id, second.investigation_id]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == "1.2"
        assert body["comparison_sha256"]
        assert "surface_water_level" in body["markdown"]
        assert "No trends, statistical tests, or scientific conclusions were generated." in body["markdown"]
        memory = client.post(
            "/api/v1/platform/earth-memory/search",
            json={
                "artifact_types": ["investigation_comparison"],
                "source_artifact_id": f"investigation:{first.investigation_id}",
            },
        )
        assert memory.status_code == 200
        assert memory.json()["total"] == 1
        temporal_memory = client.post(
            "/api/v1/platform/earth-memory/search",
            json={
                "artifact_types": ["temporal_difference"],
                "source_artifact_id": f"investigation:{first.investigation_id}",
            },
        )
        assert temporal_memory.status_code == 200
        assert temporal_memory.json()["total"] == 1
        assert temporal_memory.json()["artifacts"][0]["payload"]["difference_value"] == 1
        audit = client.get(
            f"/api/v1/platform/investigations/{first.investigation_id}/audit"
        )
        assert audit.status_code == 200
        assert any(
            event["event_type"] == "investigation_comparison"
            for chain in audit.json()["chains"].values()
            for event in chain["events"]
        )
        reproducibility = client.get(
            f"/api/v1/platform/investigations/{first.investigation_id}/reproducibility"
        )
        assert reproducibility.status_code == 200
        assert len(reproducibility.json()["investigation_comparisons"]) == 1
        linked_report = client.get(
            f"/api/v1/platform/investigations/{first.investigation_id}/report"
        )
        assert linked_report.status_code == 200
        assert len(linked_report.json()["comparison_artifacts"]) == 1
        assert "payload" not in linked_report.json()["comparison_artifacts"][0]
        assert "Linked cross-investigation comparisons" in linked_report.json()["markdown"]
        workspace = client.get("/")
        assert workspace.status_code == 200
        assert "investigation_comparison" in workspace.text
        assert "investigationCompareSelect" in client.get("/").text
    finally:
        set_engine(None)
