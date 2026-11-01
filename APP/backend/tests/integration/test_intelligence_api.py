import json

import httpx
from fastapi.testclient import TestClient

from earth_platform.engine.factory import _ADAPTERS
from earth_platform.engine.http import HttpEngineClient
from earth_platform.main import create_app
from earth_platform.settings import Settings
from earth_platform.settings.models import (
    AgentSettings,
    EngineSettings,
    SessionSettings,
    VisionSettings,
)


def test_memory_and_capabilities_endpoints_report_platform_owned_facts(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
        vision=VisionSettings(store_path=tmp_path / "images"),
    )
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={"title": "Coastal workspace"}).json()
        capabilities = client.get("/api/v1/intelligence/capabilities")
        memory = client.get(
            f"/api/v1/intelligence/sessions/{session['id']}/memory",
            params={"query": "coastal"},
        )

    assert capabilities.status_code == 200
    snapshot = capabilities.json()
    assert snapshot["vision_ingestion"]["status"] == "available"
    assert snapshot["vision_engine_delivery"]["status"] == "unavailable"
    assert snapshot["engine_tool_discovery"]["status"] == "unknown"
    assert snapshot["dataset_discovery"]["status"] == "unknown"
    assert snapshot["earth_commands"]
    assert any(item["id"] == "camera" for item in snapshot["workspace_capabilities"])
    assert memory.status_code == 200
    assert memory.json()["results"][0]["record"]["title"] == "Coastal workspace"


def test_chat_plans_earth_context_before_forwarding_text_turn(tmp_path, monkeypatch):
    timestamp = "2026-11-01T10:00:00Z"
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/agent/sessions") and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "session_id": "engine-session",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                    "investigation_ids": [],
                },
            )
        if request.url.path.endswith("/agent/sessions/engine-session") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "session_id": "engine-session",
                    "revision": 1,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                    "investigation_ids": [],
                },
            )
        if request.url.path.endswith("/turns") and request.method == "POST":
            body = json.loads(request.read())
            assert body["message"].startswith(
                "Inspect this view\n\n--- Platform workspace context (JSON) ---\n"
            )
            assert '"lng":12.5' in body["message"]
            assert body["model_id"] == "registered-model"
            assert body["execution_authorized"] is False
            stream_events = [
                {
                    "kind": "turn.started",
                    "session_id": "engine-session",
                    "turn_id": "turn-1",
                    "sequence": 1,
                    "timestamp": timestamp,
                    "payload": {},
                },
                {
                    "kind": "turn.completed",
                    "session_id": "engine-session",
                    "turn_id": "turn-1",
                    "sequence": 2,
                    "timestamp": timestamp,
                    "payload": {},
                },
            ]
            content = "".join(f"data: {json.dumps(item)}\n\n" for item in stream_events)
            return httpx.Response(
                200,
                content=content,
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    monkeypatch.setitem(
        _ADAPTERS,
        "http",
        lambda settings: HttpEngineClient(settings, transport=transport),
    )
    settings = Settings(
        _env_file=None,
        engine=EngineSettings(kind="http", base_url="http://satquery.test"),
        agent=AgentSettings(model_id="registered-model"),
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
        vision=VisionSettings(store_path=tmp_path / "images"),
    )
    earth_context = {
        "camera": {
            "position": {"lng": 12.5, "lat": 45},
            "height_m": 500000,
            "heading_deg": 0,
            "pitch_deg": -90,
            "roll_deg": 0,
            "view_rect": None,
        },
        "layers": [],
        "time": None,
        "instant": None,
        "selection": None,
        "drawings": [],
        "captures": [],
        "selected_evidence_ids": [],
        "bookmarks": [],
        "camera_history": {"past": [], "present": None, "future": []},
        "split_view": {"enabled": False, "sync_cameras": False},
        "measurement": None,
    }

    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        plan = client.post(
            f"/api/v1/chat/sessions/{session['id']}/plan",
            json={"message": "Inspect this view", "earth_context": earth_context},
        )
        assert plan.status_code == 200
        assert plan.json()["engine_supports_earth_context"] is False
        assert plan.json()["request"]["earth_context"]["camera"]["position"]["lng"] == 12.5

        streamed = client.post(
            f"/api/v1/chat/sessions/{session['id']}/turns",
            json={"message": "Inspect this view", "earth_context": earth_context},
        )

    assert streamed.status_code == 200
    assert len([request for request in requests if request.url.path.endswith("/turns")]) == 1
