from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from satquery.api import create_app, set_engine
from satquery.config import get_settings
from satquery.connector_bootstrap import load_configured_connectors
from satquery.orchestrator import SatQueryEngine
from satquery.platform.connectors import PerceptionConnector
from satquery.platform.contracts import (
    ConnectorMetadata,
    DatasetReference,
    EarthQuery,
    ExecutionResult,
    ExecutionStatus,
    Mission,
    Observation,
    ObservationSearchResult,
    ObservationStack,
    ObservationStackMember,
    PerceptionResult,
    Task,
    TaskExecution,
    TaskStatus,
    utc_now,
)
from satquery.platform.earth_memory import artifact_from_payload
from satquery.platform.intelligence import EvidenceAssessment
from satquery.platform.reasoning import ScientificReasoningReport
from satquery.platform.runtime import PlatformRuntime
from satquery.schemas import BackendKind, Intent, QueryPlan, QueryResponse


class _AtmosphericFixture(PerceptionConnector):
    @property
    def metadata(self):
        return ConnectorMetadata(
            connector_id="fixture-atmosphere",
            name="Atmospheric fixture",
            version="1",
            capabilities=("observation",),
            modalities=("atmospheric",),
            supported_variables=("air_temperature",),
            supported_spatial_types=("point",),
            supports_temporal_query=True,
            supported_query_fields=("requested_dataset_ids",),
        )

    async def discover(self):
        return self.metadata.datasets

    async def acquire(self, request):
        return request

    async def observe(self, query):
        return ObservationSearchResult(
            observations=(
                Observation(
                    source_id="fixture-record-1",
                    measured_variables={
                        "air_temperature": {"value": 292.1, "unit": "K"}
                    },
                ),
            ),
            matched=1,
        )


class _FailingScientificOperator:
    operator_id = "fixture.failing-operator"
    version = "1"

    def evaluate(self, context):
        raise RuntimeError("extension failure must not escape reasoning")


def test_platform_api_exposes_modalities_and_perception_planning():
    engine = SatQueryEngine(get_settings())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            modalities = client.get("/api/v1/platform/modalities")
            assert modalities.status_code == 200
            assert "hydrological" in {item["modality_id"] for item in modalities.json()}

            capability_matrix = client.get("/api/v1/platform/earth/capabilities")
            assert capability_matrix.status_code == 200
            assert capability_matrix.json()["revision"]
            assert "ecological" in {
                item["modality_id"] for item in capability_matrix.json()["modalities"]
            }

            planned = client.post(
                "/api/v1/platform/earth/plan",
                json={"requested_variables": ["air_temperature"]},
            )
            assert planned.status_code == 200
            assert planned.json()["requested_modalities"] == ["atmospheric"]
            assert planned.json()["selected_modalities"] == []
            assert planned.json()["unavailable_modalities"] == ["atmospheric"]
            assert (
                planned.json()["capability_matrix_revision"]
                == capability_matrix.json()["revision"]
            )
            scientific_methods = client.get("/api/v1/platform/scientific-methods")
            assert scientific_methods.status_code == 200
            method_catalog = scientific_methods.json()
            assert method_catalog["rules"] == []
            assert "satquery.temporal-alignment" in {
                item["operator_id"] for item in method_catalog["operators"]
            }
            assert len(method_catalog["domains"]) == 10
            assert all(
                item["status"] == "no_validated_methods_registered"
                for item in method_catalog["domains"]
            )
            cited_library = client.get(
                "/api/v1/platform/scientific-knowledge/methods?domain=hydrology"
            )
            assert cited_library.status_code == 200
            assert cited_library.json()[0]["benchmark_status"] == "identified_not_materialized"
            assert cited_library.json()[0]["implementation_status"] == "reference_catalog_only"
            earth_memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"text": "Landsat", "artifact_types": ["scientific_method"]},
            )
            assert earth_memory.status_code == 200
            assert earth_memory.json()["total"] >= 1
            assert "search_text" not in earth_memory.json()["artifacts"][0]
            workflows = client.get("/api/v1/platform/scientific-workflows")
            assert workflows.status_code == 200
            assert len(workflows.json()) == 10
            assert all(not item["methods"] and not item["conclusions"] for item in workflows.json())
            instantiated = client.post(
                "/api/v1/platform/scientific-workflows/earth-investigation.drought/instantiate",
                json={"configuration": {"area_of_interest": "explicitly supplied"}},
            )
            assert instantiated.status_code == 200
            assert instantiated.json()["conclusions"] == []
            assert instantiated.json()["generated_method_ids"] == []
            assert "drought_definition" in instantiated.json()["unresolved_configuration"]
            missing_method = client.post(
                "/api/v1/platform/scientific-methods/assess",
                json={"method_id": "unknown", "version": "1", "earth_query": {}},
            )
            assert missing_method.status_code == 404
    finally:
        set_engine(None)


def test_platform_earth_memory_api_accepts_spatiotemporal_filters():
    engine = SatQueryEngine(get_settings())
    from datetime import datetime, timezone

    observed_at = datetime(2025, 4, 10, tzinfo=timezone.utc)
    observation = Observation(
        observation_id="memory-api-observation", bbox=(70, 10, 72, 12),
        crs="OGC:CRS84", observed_at=observed_at,
    )
    engine.platform_runtime.earth_memory.upsert(artifact_from_payload(
        artifact_id="observation:memory-api-observation", artifact_type="observation",
        payload=observation, indexed_at=observed_at.isoformat(),
    ))
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            workspace = client.get("/")
            assert workspace.status_code == 200
            assert 'id="searchEarthMemory"' in workspace.text
            response = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "spatial_bbox": [71, 11, 71.5, 11.5],
                    "spatial_crs": "OGC:CRS84",
                    "temporal_start": "2025-04-10T00:00:00Z",
                    "temporal_end": "2025-04-10T00:00:00Z",
                    "artifact_types": ["observation"],
                },
            )
            assert response.status_code == 200
            assert response.json()["total"] == 1
            assert response.json()["spatial_semantics"] == "inclusive_same_crs_bbox_overlap"
            assert response.json()["temporal_semantics"] == "inclusive_interval_overlap"
            assert response.json()["artifacts"][0]["artifact_id"] == "observation:memory-api-observation"
            rejected = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"spatial_bbox": [0, 0, 1, 1]},
            )
            assert rejected.status_code == 422
    finally:
        set_engine(None)


def test_temporal_differences_are_exposed_and_indexed_for_an_investigation():
    engine = SatQueryEngine(get_settings())
    runtime = engine.platform_runtime
    mission = runtime.mission_service.create(Mission(
        mission_id="mission-temporal-difference",
        name="Temporal raster inspection",
        objective="Compare exact-support samples",
    ))
    investigation = runtime.mission_service.create_investigation(mission.mission_id)
    runtime.investigation_service.start(investigation.investigation_id)
    support = {
        "type": "Polygon",
        "coordinates": [[[10, 20], [11, 20], [11, 21], [10, 21], [10, 20]]],
    }
    members = tuple(
        ObservationStackMember(
            observation_id=f"temporal-scene-{day}",
            measurement_observation_id=f"temporal-measurement-{day}",
            dataset=DatasetReference(connector_id="fixture-stac", dataset_id="thermal-collection"),
            observed_at=datetime(2025, 3, day, tzinfo=timezone.utc),
            value=value,
            unit="K",
            source_variable="surface_temperature",
            source_measurement_metadata={
                "pixel_support_geometry": support,
                "pixel_support_crs": "OGC:CRS84",
            },
            provenance={"source_item_id": f"item-{day}"},
        )
        for day, value in ((1, 290.0), (2, 291.5))
    )
    stack = ObservationStack(
        stack_id="api-test-stack",
        variable_key="canonical:surface_temperature",
        canonical_variable="surface_temperature",
        unit="K",
        spatial_support_geometry=support,
        spatial_support_crs="OGC:CRS84",
        spatial_alignment="exact_pixel_support",
        temporal_alignment="source_acquisition_time",
        members=members,
    )
    from satquery.platform.spatiotemporal import ConsecutiveTemporalDifferenceEngine

    diagnostic = ConsecutiveTemporalDifferenceEngine().build((stack,))[0][0]
    perception_result = PerceptionResult(
        query_fingerprint="api-test-query",
        observation_stacks=(stack,),
        temporal_differences=(diagnostic,),
    )
    now = utc_now()
    execution = ExecutionResult(
        plan_id="execution-temporal-test",
        status=ExecutionStatus.SUCCEEDED,
        started_at=now,
        tasks=(TaskExecution(
            task_id="observe",
            handler="earth.observe",
            status=TaskStatus.SUCCEEDED,
            attempts=1,
            output=perception_result,
            duration_seconds=0,
            finished_at=now,
        ),),
    )
    runtime.record_execution_result(execution, investigation_id=investigation.investigation_id)
    runtime.investigation_service.add_result(
        investigation.investigation_id, execution.plan_id
    )
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            stacks_response = client.get(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/observation-stacks"
            )
            assert stacks_response.status_code == 200
            assert stacks_response.json()[0]["stack_id"] == stack.stack_id
            assert len(stacks_response.json()[0]["members"]) == 2
            response = client.get(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/temporal-differences"
            )
            assert response.status_code == 200
            assert response.json()[0]["difference_value"] == 1.5
            assert response.json()[0]["interpretation_status"] == "descriptive_only"
            assert response.json()[0]["uncertainty_status"] == "not_propagated"
            report = client.get(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/report"
            )
            assert report.status_code == 200
            assert len(report.json()["temporal_differences"]) == 1
            assert "Descriptive only" in report.json()["markdown"]
            memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "investigation_id": investigation.investigation_id,
                    "artifact_types": ["temporal_difference"],
                    "spatial_bbox": [10.2, 20.2, 10.8, 20.8],
                    "spatial_crs": "OGC:CRS84",
                    "temporal_start": "2025-03-01T00:00:00Z",
                    "temporal_end": "2025-03-02T00:00:00Z",
                },
            )
            assert memory.status_code == 200
            assert memory.json()["total"] == 1
            assert memory.json()["artifacts"][0]["payload"]["stack_id"] == stack.stack_id
            workspace = client.get("/")
            assert "Temporal sample differences" in workspace.text
    finally:
        set_engine(None)


def test_platform_mission_investigation_executes_registered_tasks():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            created = client.post(
                "/api/v1/platform/missions",
                json={
                    "mission_id": "mission-1",
                    "name": "Flood watch",
                    "objective": "Observe river levels",
                },
            )
            assert created.status_code == 201

            investigation_response = client.post(
                "/api/v1/platform/missions/mission-1/investigations",
                json={"requested_variables": ["air_temperature"]},
            )
            assert investigation_response.status_code == 201
            investigation_id = investigation_response.json()["investigation_id"]

            executed = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/execute"
            )
            assert executed.status_code == 200
            assert executed.json()["status"] == "succeeded"
            assert (
                executed.json()["tasks"][0]["output"]["observations"][0]["source_id"]
                == "fixture-record-1"
            )

            inspected = client.get(
                f"/api/v1/platform/investigations/{investigation_id}"
            )
            assert inspected.status_code == 200
            assert inspected.json()["status"] == "completed"
            assert "not a scientific conclusion" in inspected.json()["report"]
            audit = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/audit"
            )
            assert audit.status_code == 200
            assert audit.json()["chains"][investigation_id]["valid"] is True
            assert audit.json()["chains"][investigation_id]["events"]
            reproducibility = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reproducibility"
            )
            assert reproducibility.status_code == 200
            bundle = reproducibility.json()
            assert bundle["capability_matrix_revision"]
            assert bundle["bundle_sha256"]
            assert bundle["observations"]
            assert bundle["provenance"]
    finally:
        set_engine(None)


def test_pending_investigation_can_be_cancelled_through_platform_api():
    engine = SatQueryEngine(get_settings())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            assert 'id="cancelInvestigation"' in client.get("/").text
            mission = client.post(
                "/api/v1/platform/missions",
                json={"name": "Cancel test", "objective": "Exercise lifecycle cancellation"},
            ).json()
            investigation = client.post(
                f"/api/v1/platform/missions/{mission['mission_id']}/investigations",
                json={"requested_variables": ["air_temperature"]},
            ).json()
            response = client.post(
                f"/api/v1/platform/investigations/{investigation['investigation_id']}/cancel"
            )

            assert response.status_code == 200
            assert response.json()["status"] == "cancelled"
            assert client.get(
                f"/api/v1/platform/investigations/{investigation['investigation_id']}"
            ).json()["status"] == "cancelled"
    finally:
        set_engine(None)


def test_failed_investigation_resumes_through_api_and_exposes_persisted_events():
    engine = SatQueryEngine(get_settings())
    attempts = 0

    def retryable_handler(_context):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("recoverable fixture failure")
        return {"result": "completed"}

    runtime = engine.platform_runtime
    runtime.register_task_handler("fixture.retryable", retryable_handler)
    mission = Mission(name="Resume test", objective="Validate restart-safe execution")
    runtime.mission_service.create(mission)
    investigation = runtime.mission_service.create_investigation(
        mission.mission_id,
        (Task(task_id="retry", handler="fixture.retryable", retry_safe=True),),
    )
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            first = client.post(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/execute"
            )
            assert first.status_code == 200
            assert first.json()["status"] == "failed"
            execution_id = first.json()["plan_id"]

            resumed = client.post(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/resume"
            )
            assert resumed.status_code == 200
            assert resumed.json()["status"] == "succeeded"
            assert resumed.json()["plan_id"] == execution_id
            assert attempts == 2

            journal = client.get(
                f"/api/v1/platform/executions/{execution_id}/events"
            ).json()
            assert any(
                event["event_type"] == "execution.resumed"
                for event in journal["events"]
            )
            assert journal["next_sequence"] == journal["events"][-1]["sequence"]
    finally:
        set_engine(None)


def test_reasoning_extension_failure_does_not_fail_observation_execution():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    engine.platform_runtime.scientific_reasoning.operators.register(
        _FailingScientificOperator()
    )
    set_engine(engine)
    query = {
        "point": [80.15, 12.84],
        "temporal_start": "2024-01-01T00:00:00Z",
        "temporal_end": "2024-01-31T23:59:59Z",
        "requested_variables": ["air_temperature"],
    }
    try:
        with TestClient(create_app(get_settings())) as client:
            created = client.post(
                "/api/v1/platform/investigate",
                json={"question": "Measure air temperature", "earth_query": query},
            )
            investigation_id = created.json()["investigation"]["investigation_id"]

            executed = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/execute"
            )
            assert executed.status_code == 200
            inspected = client.get(
                f"/api/v1/platform/investigations/{investigation_id}"
            )
            assert inspected.json()["status"] == "completed"

            reasoning = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reasoning"
            ).json()
            failure = next(
                item
                for item in reasoning["operator_results"]
                if item["operator_id"] == "fixture.failing-operator"
            )
            assert failure["status"] == "error"
            assert failure["statement"].startswith("Operator failed with RuntimeError")
    finally:
        set_engine(None)


def test_scientific_planner_creates_reviewable_plan_then_executable_investigation():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    query = {
        "point": [80.15, 12.84],
        "temporal_start": "2024-01-01T00:00:00Z",
        "temporal_end": "2024-01-31T23:59:59Z",
        "requested_variables": ["air_temperature"],
    }
    try:
        with TestClient(create_app(get_settings())) as client:
            assert 'id="executionGraph"' in client.get("/").text
            registered_workflows = client.get(
                "/api/v1/platform/execution/workflows"
            ).json()
            assert registered_workflows["workflow_compilers"] == [{
                "workflow_id": "satquery.scientific-investigation",
                "version": "1.0.0",
            }]
            planned = client.post(
                "/api/v1/platform/planning/investigations",
                json={
                    "question": "Measure air temperature near the study site",
                    "earth_query": query,
                },
            )
            assert planned.status_code == 200
            plan = planned.json()
            assert plan["status"] == "ready"
            assert plan["candidate_plans"][0]["selected_implementations"] == [
                "fixture-atmosphere"
            ]
            assert (
                plan["candidate_plans"][0]["provider_assessments"][0]["confidence"]
                is None
            )
            assert plan["candidate_plans"][0]["cost_estimate"]["status"] == "unknown"
            assert plan["reproducibility"]["capability_matrix_revision"]

            created = client.post(
                "/api/v1/platform/investigate",
                json={
                    "question": "Test whether air temperature increased near the study site",
                    "earth_query": query,
                },
            )
            assert created.status_code == 201
            body = created.json()
            assert body["state"] == "ready"
            assert (
                body["investigation"]["investigation_plan_id"]
                == body["plan"]["plan_id"]
            )
            assert (
                body["investigation"]["investigation_design_id"]
                == body["design"]["design_id"]
            )
            assert body["design"]["status"] == "ready_for_acquisition"
            assert len(body["investigation"]["tasks"]) == 1

            investigation_id = body["investigation"]["investigation_id"]
            executed = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/execute"
            )
            assert executed.status_code == 200
            assert executed.json()["metadata"]["workflow_id"] == (
                "satquery.scientific-investigation"
            )
            workflow_tasks = {
                item["handler"]: item
                for item in executed.json()["tasks"]
            }
            assert set(workflow_tasks) == {
                "earth.observe", "earth.assess", "earth.reason"
            }
            assert workflow_tasks["earth.assess"]["depends_on"] == [
                body["investigation"]["tasks"][0]["task_id"]
            ]
            assert workflow_tasks["earth.reason"]["depends_on"][-1] == (
                workflow_tasks["earth.assess"]["task_id"]
            )
            assert workflow_tasks["earth.assess"]["status"] == "succeeded"
            assert workflow_tasks["earth.reason"]["status"] == "succeeded"
            execution_id = executed.json()["plan_id"]
            journal = client.get(
                f"/api/v1/platform/executions/{execution_id}/events"
            )
            assert journal.status_code == 200
            assert any(
                item["event_type"] == "task.checkpointed"
                for item in journal.json()["events"]
            )
            runtime = engine.platform_runtime
            runtime._execution_results.clear()
            replayed = runtime.get_execution_result(execution_id)
            assert isinstance(replayed.tasks[1].output, EvidenceAssessment)
            assert isinstance(replayed.tasks[2].output, ScientificReasoningReport)
            assert (
                client.get(f"/api/v1/platform/executions/{execution_id}").status_code
                == 200
            )
            observations = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/observations"
            )
            assert observations.status_code == 200
            assert observations.json()[0]["source_id"] == "fixture-record-1"
            provenance = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/provenance"
            )
            assert provenance.status_code == 200
            intelligence = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/intelligence"
            )
            assert intelligence.status_code == 200
            assert len(intelligence.json()["assessment"]["hypotheses"]) == 1
            assert (
                intelligence.json()["assessment"]["hypotheses"][0]["status"]
                == "not_evaluated"
            )
            assert intelligence.json()["assessment"]["status"] == "coverage_partial"
            reasoning = intelligence.json()["reasoning"]
            assert reasoning["conclusion"]["status"] == "unresolved"
            assert reasoning["conclusion"]["confidence"] is None
            hypothesis_lifecycle = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses"
            )
            assert hypothesis_lifecycle.status_code == 200
            lifecycle_body = hypothesis_lifecycle.json()
            assert len(lifecycle_body["graph"]["hypotheses"]) == 1
            hypothesis = lifecycle_body["graph"]["hypotheses"][0]
            assert hypothesis["lifecycle"] == "active"
            assert len(lifecycle_body["events"]) == 2
            transitioned = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses/{hypothesis['hypothesis_id']}/transitions",
                json={
                    "expected_version": hypothesis["version"],
                    "status": "under_review",
                    "actor": "test-reviewer",
                    "rationale": "Reviewing evidence sufficiency.",
                },
            )
            assert transitioned.status_code == 200
            assert transitioned.json()["hypothesis"]["version"] == hypothesis["version"] + 1
            assert transitioned.json()["hypothesis"]["lifecycle"] == "under_review"
            added_hypothesis = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses",
                json={
                    "hypothesis_id": "review-alternative",
                    "proposition": "The observed change reflects sampling variability.",
                    "source_text": "Explicit reviewer hypothesis",
                    "origin": "explicit",
                    "competing_group_id": "temperature-change-alternatives",
                    "actor": "test-reviewer",
                    "rationale": "Record an explicit alternative for review.",
                },
            )
            assert added_hypothesis.status_code == 201
            assert added_hypothesis.json()["hypothesis"]["lifecycle"] == "proposed"
            current_hypotheses = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses"
            ).json()["graph"]["hypotheses"]
            assert {item["hypothesis_id"] for item in current_hypotheses} == {
                hypothesis["hypothesis_id"],
                "review-alternative",
            }
            composite = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses",
                json={
                    "hypothesis_id": "composite-review",
                    "proposition": "The temperature change and sampling explanation jointly apply.",
                    "source_text": "Explicit composite hypothesis",
                    "origin": "composite",
                    "parent_hypothesis_ids": [
                        hypothesis["hypothesis_id"],
                        "review-alternative",
                    ],
                    "composition": "all",
                    "actor": "test-reviewer",
                    "rationale": "Preserve a declared composite without evaluating its truth.",
                },
            )
            assert composite.status_code == 201
            assert composite.json()["hypothesis"]["origin"] == "composite"
            standalone = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reasoning"
            )
            assert standalone.status_code == 200
            assert standalone.json()["reasoning_id"] == reasoning["reasoning_id"]
    finally:
        set_engine(None)


def test_investigation_with_partial_observation_coverage_is_not_executable():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    query = {
        "point": [80.15, 12.84],
        "temporal_start": "2024-01-01T00:00:00Z",
        "temporal_end": "2024-01-31T23:59:59Z",
        "requested_variables": ["air_temperature", "precipitation"],
    }
    try:
        with TestClient(create_app(get_settings())) as client:
            created = client.post(
                "/api/v1/platform/investigate",
                json={
                    "question": "Measure air temperature and precipitation",
                    "earth_query": query,
                },
            )

            assert created.status_code == 201
            body = created.json()
            assert body["state"] == "no_capability"
            assert body["plan"]["candidate_plans"][0]["perception_plan"][
                "unavailable_variables"
            ] == ["precipitation_amount"]
            assert body["investigation"]["tasks"] == []
    finally:
        set_engine(None)


def test_intelligence_design_api_returns_graph_without_acquiring_observations():
    engine = SatQueryEngine(get_settings())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            designed = client.post(
                "/api/v1/platform/intelligence/design",
                json={
                    "question": "Measure air temperature globally during 2024",
                    "earth_query": {
                        "region": "*",
                        "temporal_start": "2024-01-01T00:00:00Z",
                        "temporal_end": "2024-12-31T23:59:59Z",
                        "requested_variables": ["air_temperature"],
                    },
                },
            )

            assert designed.status_code == 200
            body = designed.json()
            assert body["design"]["plan_id"] == body["plan"]["plan_id"]
            assert body["design"]["evidence_graph"]["nodes"]
            assert all(
                edge["source_node_id"]
                in {
                    node["node_id"]
                    for node in body["design"]["evidence_graph"]["nodes"]
                }
                for edge in body["design"]["evidence_graph"]["edges"]
            )
            assert engine.platform_runtime.execution_results() == ()
    finally:
        set_engine(None)


def test_connector_health_api_separates_local_status_from_explicit_probes():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            local = client.get("/api/v1/platform/connectors/health")
            assert local.status_code == 200
            assert local.json()[0]["connector_id"] == "fixture-atmosphere"
            assert "last_error" not in local.json()[0]

            probed = client.post(
                "/api/v1/platform/connectors/fixture-atmosphere/health-check"
            )
            assert probed.status_code == 200
            assert probed.json()["connector_id"] == "fixture-atmosphere"
    finally:
        set_engine(None)


def test_legacy_image_analysis_runs_as_a_platform_investigation():
    engine = SatQueryEngine(get_settings())
    response = QueryResponse.model_construct(
        request_id="sq-test",
        query="describe this image",
        answer="A fixture response.",
        intent=Intent.CAPTION,
        tools_used=[],
        backend=BackendKind.PRACTICAL,
        images=[],
        results=[],
        plan=object(),
        latency_ms=0,
    )
    engine.answer = lambda **_kwargs: response

    result = asyncio.run(
        engine.answer_on_platform("describe this image", image_paths=("image.png",))
    )

    assert result.answer == response.answer
    assert result.platform_mission_id
    assert result.platform_investigation_id
    assert result.platform_execution_id
    mission = engine.platform_runtime.mission_service.list()[0]
    investigations = engine.platform_runtime.investigation_service.list_for_mission(
        mission.mission_id
    )
    assert mission.status.value == "completed"
    assert mission.finished_at is not None
    assert len(investigations) == 1
    assert investigations[0].status.value == "completed"
    assert investigations[0].result_ids
    asyncio.run(engine.close())


def test_image_api_executes_through_platform_and_returns_lifecycle_ids():
    engine = SatQueryEngine(get_settings())
    response = QueryResponse(
        request_id="sq-api-test",
        query="describe this image",
        answer="A fixture response.",
        intent=Intent.CAPTION,
        tools_used=[],
        backend=BackendKind.PRACTICAL,
        images=[],
        results=[],
        plan=QueryPlan(
            intent=Intent.CAPTION,
            steps=[],
            router="fixture",
            rationale="deterministic API integration fixture",
        ),
        latency_ms=0,
    )
    engine.answer = lambda **_kwargs: response
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            result = client.post(
                "/api/v1/query",
                data={"query": "describe this image"},
                files={"files": ("scene.png", b"fixture image bytes", "image/png")},
            )
            assert result.status_code == 200
            body = result.json()
            assert body["platform_mission_id"]
            assert body["platform_investigation_id"]
            assert body["platform_execution_id"]
            inspection = client.get(
                f"/api/v1/platform/investigations/{body['platform_investigation_id']}"
            )
            assert inspection.status_code == 200
            assert inspection.json()["status"] == "completed"
    finally:
        set_engine(None)


def test_connector_manifest_registers_adapters_without_opening_network_clients():
    runtime = PlatformRuntime()
    manifest = Path(__file__).parents[1] / "configs" / "connectors.example.json"

    registered = load_configured_connectors(runtime, config_path=manifest)

    assert registered == (
        "earth-search",
        "nasa-earthdata",
        "noaa-coops-water-level",
        "open-meteo.climate",
        "open-meteo.historical_weather",
        "open-meteo.hydrology",
        "open-meteo.weather",
        "openstreetmap-overpass",
        "usgs-3dep-epqs",
        "usgs-water-daily",
    )
    declared_weather = runtime.registries.datasets.get(
        "open-meteo.weather", "weather-forecast"
    )
    assert declared_weather.variables
    assert declared_weather.modalities == ("atmospheric",)
    assert declared_weather.units["air_temperature_2m"] == "°C"
    assert declared_weather.supports_forecast is True
    assert declared_weather.supports_historical is False
    noaa_dataset = runtime.registries.datasets.get(
        "noaa-coops-water-level", "noaa-coops-water-level"
    )
    assert noaa_dataset.modalities == ("oceanic",)
    assert noaa_dataset.variables == ("coastal_water_level",)
    assert noaa_dataset.units["coastal_water_level"] == "m"
    assert noaa_dataset.access_policy["station_id_required"] is True
    assert runtime.perception_engine.plan(
        EarthQuery(point=(80.15, 12.84), requested_variables=("air_temperature_2m",))
    ).selected_modalities == ("atmospheric",)
    asyncio.run(runtime.close())
