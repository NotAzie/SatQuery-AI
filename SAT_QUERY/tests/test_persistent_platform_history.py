from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from satquery.api import create_app, set_engine
from satquery.config import get_settings
from satquery.orchestrator import SatQueryEngine
from satquery.platform.config import PlatformConfig
from satquery.platform.contracts import (
    ExecutionResult,
    ExecutionStatus,
    Mission,
    Observation,
    ObservationSearchResult,
    PerceptionResult,
    TaskExecution,
    TaskStatus,
)
from satquery.platform.runtime import PlatformRuntime, _execution_result_from_payload


def test_execution_rehydration_preserves_perception_fusion_diagnostics():
    result = ExecutionResult(
        plan_id="fusion-result",
        status=ExecutionStatus.PARTIAL,
        started_at=datetime.now(timezone.utc),
        tasks=(TaskExecution(
            task_id="observe-fused",
            status=TaskStatus.SUCCEEDED,
            attempts=1,
            duration_seconds=0.01,
            output=PerceptionResult(
                query_fingerprint="query-hash",
                conflicts=({"kind": "overlapping_measurements"},),
                status="partial",
            ),
        ),),
    )

    restored = _execution_result_from_payload(result.model_dump(mode="json"))

    assert isinstance(restored.tasks[0].output, PerceptionResult)
    assert restored.tasks[0].output.conflicts == ({"kind": "overlapping_measurements"},)


def test_durable_lifecycle_and_execution_outputs_survive_runtime_restart(tmp_path):
    database = tmp_path / "satquery.sqlite"
    config = PlatformConfig.load(overrides={
        "storage": {"earth_memory_path": str(database)},
    })
    first = PlatformRuntime(config=config)
    mission = Mission(name="River watch", objective="Inspect recorded river conditions")
    first.mission_service.create(mission)
    investigation = first.mission_service.create_investigation(mission.mission_id)
    first.investigation_service.start(investigation.investigation_id)

    observation = Observation(
        source_id="fixture-1",
        measured_variables={"discharge": {"value": 42.0, "unit": "m3/s"}},
    )
    result = ExecutionResult(
        plan_id="execution-1",
        status=ExecutionStatus.SUCCEEDED,
        started_at=datetime.now(timezone.utc),
        tasks=(TaskExecution(
            task_id="observe-1",
            status=TaskStatus.SUCCEEDED,
            attempts=1,
            duration_seconds=0.01,
            output=ObservationSearchResult(observations=(observation,), matched=1),
        ),),
    )
    first.record_execution_result(result, investigation_id=investigation.investigation_id)
    first.investigation_service.add_result(investigation.investigation_id, result.plan_id)
    first.investigation_service.complete(investigation.investigation_id, "Observation recorded.")

    restored = PlatformRuntime(config=config)
    restored_mission = restored.mission_service.get(mission.mission_id)
    restored_investigation = restored.investigation_service.get(investigation.investigation_id)
    restored_execution = restored.get_execution_result(result.plan_id)

    assert restored_mission.name == mission.name
    assert restored.investigation_service.list_for_mission(mission.mission_id) == (restored_investigation,)
    assert restored_investigation.report == "Observation recorded."
    assert restored_investigation.result_ids == (result.plan_id,)
    assert restored_execution.tasks[0].output.observations[0].observation_id == observation.observation_id


def test_api_and_workspace_expose_history_after_engine_restart(tmp_path, monkeypatch):
    config_path = tmp_path / "platform.json"
    config_path.write_text(
        '{"storage":{"earth_memory_path":"' + str(tmp_path / "history.sqlite").replace("\\", "\\\\") + '"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("SATQUERY_PLATFORM_CONFIG", str(config_path))

    first = SatQueryEngine(get_settings())
    mission = Mission(name="Drought watch", objective="Track regional drought evidence")
    first.platform_runtime.mission_service.create(mission)
    investigation = first.platform_runtime.mission_service.create_investigation(mission.mission_id)
    first.platform_runtime.index_investigation(investigation)
    set_engine(first)
    with TestClient(create_app(get_settings())) as client:
        assert client.get("/api/v1/platform/missions").json()[0]["mission_id"] == mission.mission_id
        assert client.get(
            f"/api/v1/platform/missions/{mission.mission_id}/investigations"
        ).json()[0]["investigation_id"] == investigation.investigation_id
        workspace = client.get("/").text
        assert 'id="missionExplorer"' in workspace
        assert 'id="investigationExplorer"' in workspace
        assert 'id="executionGraph"' in workspace

    second = SatQueryEngine(get_settings())
    set_engine(second)
    with TestClient(create_app(get_settings())) as client:
        assert client.get("/api/v1/platform/investigations/" + investigation.investigation_id).json()["status"] == "pending"
