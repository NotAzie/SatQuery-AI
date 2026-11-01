from fastapi.testclient import TestClient
from satquery.api import create_app, set_engine
from satquery.config import get_settings
from satquery.orchestrator import SatQueryEngine
from satquery.platform.contracts import Mission


def test_report_endpoint_renders_recorded_scope_and_keeps_unknown_conclusion_explicit():
    engine = SatQueryEngine(get_settings())
    mission = Mission(
        name="Wetland evidence review",
        objective="Review available wetland observations",
    )
    engine.platform_runtime.mission_service.create(mission)
    investigation = engine.platform_runtime.mission_service.create_investigation(
        mission.mission_id
    )
    set_engine(engine)
    try:
        client = TestClient(create_app(get_settings()))
        workspace = client.get("/")
        assert workspace.status_code == 200
        assert 'id="investigationReport"' in workspace.text
        response = client.get(
            f"/api/v1/platform/investigations/{investigation.investigation_id}/report"
        )
        assert response.status_code == 200
        report = response.json()
        assert report["mission"]["objective"] == mission.objective
        assert report["reasoning"] is None
        assert report["report_sha256"]
        assert "No scientific reasoning report is available" in report["markdown"]

        repeated = client.get(
            f"/api/v1/platform/investigations/{investigation.investigation_id}/report"
        ).json()
        assert repeated["report_id"] == report["report_id"]
        assert repeated["markdown"] == report["markdown"]
    finally:
        set_engine(None)
