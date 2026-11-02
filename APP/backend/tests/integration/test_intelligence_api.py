import base64
import hashlib
import io
import json

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from earth_platform.engine.factory import _ADAPTERS
from earth_platform.engine.http import HttpEngineClient
from earth_platform.engine.models import EngineDatasetMetadata, EngineImageCapability
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
    assert snapshot["vision_engine_delivery"]["status"] == "available"
    assert snapshot["engine_tool_discovery"]["status"] == "unknown"
    assert snapshot["dataset_discovery"]["status"] == "unknown"
    assert snapshot["earth_commands"]
    assert any(item["id"] == "camera" for item in snapshot["workspace_capabilities"])
    assert memory.status_code == 200
    assert memory.json()["results"][0]["record"]["title"] == "Coastal workspace"


def test_engine_discovery_endpoint_returns_validated_engine_metadata(
    tmp_path, monkeypatch
):
    async def list_datasets(_self):
        return [
            EngineDatasetMetadata(
                connector_id="stac",
                dataset_id="landsat",
                provider="USGS",
                modalities=["optical"],
                variables=["red", "green"],
            )
        ]

    async def list_image_capabilities(_self):
        return [
            EngineImageCapability(
                tool="caption",
                intent="CAPTION",
                description="Describe an image.",
                requires_images=1,
                backend_preference=["practical"],
                available=True,
            )
        ]

    async def get_earth_capabilities(_self):
        return {
            "revision": "a" * 64,
            "modalities": [
                {
                    "modality_id": "optical",
                    "label": "Optical",
                    "description": "Passive optical imagery.",
                    "status": "registered",
                    "implementation_ids": ["landsat"],
                    "dataset_ids": ["landsat"],
                    "variables": ["red"],
                }
            ],
            "snapshot_sha256": "b" * 64,
            "snapshot_schema_version": "1.0.0",
        }

    async def list_agent_tools(_self):
        return [
            {
                "tool_id": "investigation.execute",
                "description": "Execute an existing investigation.",
                "input_schema": {
                    "type": "object",
                    "properties": {"investigation_id": {"type": "string"}},
                    "required": ["investigation_id"],
                },
                "availability": "available",
                "requires_execution_authorization": True,
                "model_visible_without_consent": False,
                "model_visible_with_execution_consent": True,
            }
        ]

    monkeypatch.setattr(HttpEngineClient, "list_engine_datasets", list_datasets)
    monkeypatch.setattr(
        HttpEngineClient, "list_engine_image_capabilities", list_image_capabilities
    )
    monkeypatch.setattr(
        HttpEngineClient, "get_engine_earth_capabilities", get_earth_capabilities
    )
    monkeypatch.setattr(HttpEngineClient, "list_engine_agent_tools", list_agent_tools)
    settings = Settings(
        _env_file=None,
        engine=EngineSettings(kind="http", base_url="https://engine.test"),
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
        vision=VisionSettings(store_path=tmp_path / "images"),
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/intelligence/engine-discovery")

    assert response.status_code == 200
    body = response.json()
    assert [item["dataset_id"] for item in body["datasets"]] == ["landsat"]
    assert body["datasets"][0]["modalities"] == ["optical"]
    assert [item["tool"] for item in body["image_capabilities"]] == ["caption"]
    assert body["image_capabilities"][0]["available"] is True
    assert body["earth_capabilities"]["modalities"][0]["modality_id"] == "optical"
    assert body["agent_tools"][0]["tool_id"] == "investigation.execute"
    assert body["agent_tools"][0]["model_visible_without_consent"] is False


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
            assert '"lng":12.5' not in body["message"]
            assert body["model_id"] == "registered-model"
            assert body["execution_authorized"] is False
            assert body["earth_context"]["camera"]["position"] == {
                "lat": 45,
                "lng": 12.5,
            }
            assert body["earth_context"]["viewport"] == {
                "width_px": 1280,
                "height_px": 720,
                "pixel_ratio": 1.0,
            }
            assert body["earth_context"]["timeline_playback"] == {
                "playing": True,
                "speed": 2.0,
            }
            assert body["earth_context"]["investigations"] == {
                "known_ids": [],
                "visible_ids": ["investigation-1"],
            }
            assert body["earth_context"]["secondary_view"]["camera"]["position"] == {
                "lat": 35,
                "lng": 13,
            }
            assert body["earth_context"]["overlays"][0]["features"][0]["id"] == (
                "earth-object-1"
            )
            assert set(body["earth_context"]) == {
                "camera",
                "viewport",
                "layers",
                "time_range",
                "instant",
                "timeline_playback",
                "selection",
                "drawings",
                "imagery",
                "overlays",
                "secondary_view",
                "investigations",
                "selected_evidence_ids",
                "bookmarks",
                "camera_history",
                "split_view",
                "measurement",
            }
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
        "viewport": {"width_px": 1280, "height_px": 720, "pixel_ratio": 1},
        "layers": [],
        "time": None,
        "instant": None,
        "timeline_playback": {"playing": True, "speed": 2},
        "selection": None,
        "drawings": [],
        "captures": [],
        "imagery": [],
        "overlays": [
            {
                "id": "investigation:investigation-1",
                "label": "investigation-1",
                "investigation_id": "investigation-1",
                "features": [
                    {
                        "id": "earth-object-1",
                        "geometry": {"type": "Point", "coordinates": [12.5, 45]},
                        "properties": {"evidence_ids": ["evidence-1"]},
                    }
                ],
                "secondary_view": {
                    "camera": {
                        "position": {"lng": 13, "lat": 35},
                        "height_m": 800000,
                        "heading_deg": 0,
                        "pitch_deg": -90,
                        "roll_deg": 0,
                        "view_rect": None,
                    },
                    "viewport": {"width_px": 640, "height_px": 720, "pixel_ratio": 1},
                    "layers": [],
                    "overlays": [],
                    "selected_evidence_ids": [],
                },
                "omitted_objects": [],
                "geometry_policy": "WGS 84",
            }
        ],
        "investigations": {"known_ids": [], "visible_ids": ["investigation-1"]},
        "selected_evidence_ids": ["evidence-1"],
        "bookmarks": [],
        "camera_history": {"past": [], "present": None, "future": []},
        "split_view": {"enabled": True, "sync_cameras": False},
        "measurement": None,
    }

    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        plan = client.post(
            f"/api/v1/chat/sessions/{session['id']}/plan",
            json={"message": "Inspect this view", "earth_context": earth_context},
        )
        assert plan.status_code == 200
        assert plan.json()["engine_supports_earth_context"] is True
        assert plan.json()["request"]["earth_context"]["camera"]["position"]["lng"] == 12.5
        assert not any(
            "structured context field" in warning
            for warning in plan.json()["request"]["warnings"]
        )

        streamed = client.post(
            f"/api/v1/chat/sessions/{session['id']}/turns",
            json={"message": "Inspect this view", "earth_context": earth_context},
        )

    assert streamed.status_code == 200
    assert len([request for request in requests if request.url.path.endswith("/turns")]) == 1


def test_chat_delivers_platform_stored_image_bytes_to_engine_separately(tmp_path, monkeypatch):
    timestamp = "2026-11-01T10:00:00Z"
    requests: list[httpx.Request] = []
    image_buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (25, 100, 200)).save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/agent/sessions"):
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
        if request.method == "GET" and request.url.path.endswith(
            "/agent/sessions/engine-session"
        ):
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
        if request.method == "POST" and request.url.path.endswith("/turns"):
            body = json.loads(request.read())
            assert body["message"] == "Describe this image"
            assert len(body["attachments"]) == 1
            attachment = body["attachments"][0]
            assert attachment["asset_id"]
            assert attachment["mime_type"] == "image/png"
            assert attachment["size_bytes"] == len(image_bytes)
            assert attachment["sha256"] == hashlib.sha256(image_bytes).hexdigest()
            assert base64.b64decode(attachment["data_base64"]) == image_bytes
            assert "data_base64" not in body["message"]
            imagery_reference = body["earth_context"]["imagery"][0]
            assert imagery_reference["asset_id"] == attachment["asset_id"]
            assert imagery_reference["attached"] is True
            assert imagery_reference["mime_type"] == "image/png"
            events = [
                {
                    "kind": "turn.started",
                    "session_id": "engine-session",
                    "turn_id": "turn-image",
                    "sequence": 1,
                    "timestamp": timestamp,
                    "payload": {},
                },
                {
                    "kind": "turn.completed",
                    "session_id": "engine-session",
                    "turn_id": "turn-image",
                    "sequence": 2,
                    "timestamp": timestamp,
                    "payload": {},
                },
            ]
            return httpx.Response(
                200,
                content="".join(f"data: {json.dumps(item)}\n\n" for item in events),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(404)

    monkeypatch.setitem(
        _ADAPTERS,
        "http",
        lambda settings: HttpEngineClient(
            settings,
            transport=httpx.MockTransport(handle),
        ),
    )
    settings = Settings(
        _env_file=None,
        engine=EngineSettings(kind="http", base_url="http://satquery.test"),
        agent=AgentSettings(model_id="registered-model"),
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
        vision=VisionSettings(store_path=tmp_path / "images"),
    )

    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        uploaded = client.post(
            f"/api/v1/vision/sessions/{session['id']}/assets",
            files={"upload": ("coast.png", image_bytes, "image/png")},
        )
        assert uploaded.status_code == 201
        asset = uploaded.json()
        streamed = client.post(
            f"/api/v1/chat/sessions/{session['id']}/turns",
            json={
                "message": "Describe this image",
                "asset_ids": [asset["id"]],
                "earth_context": {
                    "camera": {
                        "position": {"lng": 0, "lat": 0},
                        "height_m": 500000,
                    }
                },
            },
        )

    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert len([request for request in requests if request.url.path.endswith("/turns")]) == 1
