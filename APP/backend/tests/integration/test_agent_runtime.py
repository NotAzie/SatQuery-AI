import io
import json
import sqlite3

import httpx
from fastapi.testclient import TestClient
from PIL import Image

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


def test_chat_stream_delegates_to_engine_and_persists_transcript_and_events(tmp_path, monkeypatch):
    requests: list[httpx.Request] = []
    timestamp = "2026-05-01T10:00:00Z"
    events = [
        {
            "kind": "turn.started",
            "session_id": "engine-session-1",
            "turn_id": "turn-1",
            "sequence": 1,
            "timestamp": timestamp,
            "payload": {"model_id": "registered-model", "execution_authorized": False},
        },
        {
            "kind": "assistant.delta",
            "session_id": "engine-session-1",
            "turn_id": "turn-1",
            "sequence": 2,
            "timestamp": timestamp,
            "payload": {"text": "Engine response"},
        },
        {
            "kind": "earth.command",
            "session_id": "engine-session-1",
            "turn_id": "turn-1",
            "sequence": 3,
            "timestamp": timestamp,
            "payload": {
                "command": {
                    "type": "fly_to",
                    "target": {"lng": -122.4, "lat": 37.8},
                }
            },
        },
        {
            "kind": "turn.completed",
            "session_id": "engine-session-1",
            "turn_id": "turn-1",
            "sequence": 4,
            "timestamp": timestamp,
            "payload": {"model_id": "registered-model", "rounds": 1},
        },
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/proxy/api/v1/agent/sessions" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "session_id": "engine-session-1",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                    "investigation_ids": [],
                },
            )
        if (
            request.url.path == "/proxy/api/v1/agent/sessions/engine-session-1"
            and request.method == "GET"
        ):
            return httpx.Response(
                200,
                json={
                    "session_id": "engine-session-1",
                    "revision": 2,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [
                        {"role": "user", "content": "Question", "turn_id": "turn-1"},
                        {"role": "assistant", "content": "Engine response", "turn_id": "turn-1"},
                    ],
                    "investigation_ids": [],
                },
            )
        if request.url.path.endswith("/turns") and request.method == "POST":
            body = json.loads(request.read())
            assert body == {
                "message": "Question",
                "model_id": "registered-model",
                "execution_authorized": False,
            }
            stream = "".join(f"data: {json.dumps(item)}\n\n" for item in events)
            return httpx.Response(
                200,
                content=stream,
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
        engine=EngineSettings(kind="http", base_url="http://satquery.test/proxy"),
        agent=AgentSettings(model_id="registered-model"),
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )

    with TestClient(create_app(settings)) as client:
        created = client.post("/api/v1/sessions", json={"title": "Test"})
        assert created.status_code == 201
        platform_session_id = created.json()["id"]

        streamed = client.post(
            f"/api/v1/chat/sessions/{platform_session_id}/turns",
            json={"message": "Question"},
        )
        assert streamed.status_code == 200
        assert streamed.headers["content-type"].startswith("text/event-stream")
        assert streamed.text.count('"type":"engine.event"') == 3
        assert streamed.text.count('"type":"earth.command"') == 1
        command_frame = next(
            frame
            for frame in streamed.text.split("\n\n")
            if '"type":"earth.command"' in frame
        )
        command_event = json.loads(command_frame.split("data: ", 1)[1])
        assert command_event["command"]["type"] == "fly_to"
        assert command_event["command"]["target"] == {"lat": 37.8, "lng": -122.4}
        assert '"engine_kind":"assistant.delta"' in streamed.text

        session = client.get(f"/api/v1/sessions/{platform_session_id}").json()
        assert session["engine_agent_session_id"] == "engine-session-1"
        transcript = client.get(f"/api/v1/chat/sessions/{platform_session_id}")
        assert transcript.status_code == 200
        assert transcript.json()["messages"][1]["content"] == "Engine response"
        deletion = client.delete(f"/api/v1/sessions/{platform_session_id}")
        assert deletion.status_code == 409
        assert deletion.json()["error"]["code"] == "conflict"

    assert [request.url.path for request in requests] == [
        "/proxy/api/v1/agent/sessions",
        "/proxy/api/v1/agent/sessions/engine-session-1",
        "/proxy/api/v1/agent/sessions/engine-session-1/turns",
        "/proxy/api/v1/agent/sessions/engine-session-1",
    ]
    with sqlite3.connect(tmp_path / "platform.sqlite3") as database:
        stored_events = database.execute(
            "SELECT seq, payload FROM events WHERE session_id = ? ORDER BY seq",
            (platform_session_id,),
        ).fetchall()
    assert [row[0] for row in stored_events] == [1, 2, 3, 4]
    assert json.loads(stored_events[1][1])["payload"]["text"] == "Engine response"
    stored_command = json.loads(stored_events[2][1])
    assert stored_command["type"] == "earth.command"
    assert stored_command["command"]["type"] == "fly_to"


def test_chat_requires_a_registered_engine_model(tmp_path):
    settings = Settings(
        _env_file=None,
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        response = client.post(
            f"/api/v1/chat/sessions/{session['id']}/turns",
            json={"message": "Question"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_chat_serves_only_engine_investigations_linked_to_the_session(tmp_path, monkeypatch):
    timestamp = "2026-05-01T10:00:00Z"
    report_sha256 = "b" * 64
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.method == "POST" and request.url.path.endswith("/api/v1/agent/sessions"):
            return httpx.Response(
                201,
                json={
                    "session_id": "engine-session-1",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                    "investigation_ids": [],
                },
            )
        if request.method == "GET" and request.url.path.endswith(
            "/api/v1/agent/sessions/engine-session-1"
        ):
            return httpx.Response(
                200,
                json={
                    "session_id": "engine-session-1",
                    "revision": 2,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                    "investigation_ids": ["investigation-1"],
                },
            )
        if request.method == "GET" and request.url.path.endswith(
            "/api/v1/platform/investigations/investigation-1/report"
        ):
            return httpx.Response(
                200,
                json={
                    "report_id": "report-1",
                    "report_sha256": report_sha256,
                    "investigation": {"investigation_id": "investigation-1"},
                    "markdown": "# Engine report",
                },
            )
        if (
            request.method == "GET"
            and request.url.path.endswith("/api/v1/platform/earth-objects/geojson")
            and request.url.params.get("investigation_id") == "investigation-1"
        ):
            return httpx.Response(
                200,
                json={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "object-1",
                            "geometry": {"type": "Point", "coordinates": [10, 20]},
                            "properties": {"evidence_ids": ["evidence-1"]},
                        }
                    ],
                    "satquery:omitted_objects": [],
                    "satquery:geometry_policy": "WGS 84 longitude/latitude only",
                },
            )
        if (
            request.method == "GET"
            and request.url.path.endswith(
                "/api/v1/agent/sessions/engine-session-1/investigations/"
                "investigation-1/events"
            )
        ):
            return httpx.Response(
                200,
                json={
                    "investigation_id": "investigation-1",
                    "plan_id": "plan-1",
                    "events": [
                        {
                            "sequence": 4,
                            "plan_id": "plan-1",
                            "event_type": "task.completed",
                            "timestamp": timestamp,
                            "payload": {"task_id": "acquire"},
                            "previous_event_sha256": "a" * 64,
                            "event_sha256": "b" * 64,
                        }
                    ],
                    "next_sequence": 4,
                    "has_more": False,
                },
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
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )

    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        report_url = (
            f"/api/v1/chat/sessions/{session['id']}/investigations/"
            "investigation-1/report"
        )
        response = client.get(report_url)
        assert response.status_code == 200
        assert response.json() == {
            "report_id": "report-1",
            "report_sha256": report_sha256,
            "investigation_id": "investigation-1",
            "markdown": "# Engine report",
        }

        earth_objects = client.get(
            f"/api/v1/chat/sessions/{session['id']}/investigations/"
            "investigation-1/earth-objects"
        )
        assert earth_objects.status_code == 200
        assert earth_objects.json()["features"][0]["id"] == "object-1"
        assert earth_objects.json()["satquery:omitted_objects"] == []

        events = client.get(
            f"/api/v1/chat/sessions/{session['id']}/investigations/"
            "investigation-1/events?after_sequence=2&limit=10"
        )
        assert events.status_code == 200
        assert events.json()["events"][0]["event_type"] == "task.completed"
        assert events.json()["next_sequence"] == 4

        unrelated = client.get(
            f"/api/v1/chat/sessions/{session['id']}/investigations/"
            "not-linked/report"
        )
        assert unrelated.status_code == 404

    assert requests.count(
        "/api/v1/platform/investigations/investigation-1/report"
    ) == 1
    assert requests.count("/api/v1/platform/earth-objects/geojson") == 1
    assert requests.count(
        "/api/v1/agent/sessions/engine-session-1/investigations/"
        "investigation-1/events"
    ) == 1


def test_chat_cancel_delegates_to_engine_session(tmp_path, monkeypatch):
    timestamp = "2026-05-01T10:00:00Z"
    requested_paths: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.method == "POST" and request.url.path == "/api/v1/agent/sessions":
            return httpx.Response(
                201,
                json={
                    "session_id": "engine-session-1",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                    "investigation_ids": [],
                },
            )
        if (
            request.method == "POST"
            and request.url.path == "/api/v1/agent/sessions/engine-session-1/cancel"
        ):
            return httpx.Response(204)
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
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
    )

    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        response = client.post(f"/api/v1/chat/sessions/{session['id']}/cancel")

    assert response.status_code == 204
    assert requested_paths == [
        "/api/v1/agent/sessions",
        "/api/v1/agent/sessions/engine-session-1/cancel",
    ]


def test_chat_stream_preserves_engine_image_capability_rejection(tmp_path, monkeypatch):
    timestamp = "2026-05-01T10:00:00Z"
    image_buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (25, 100, 200)).save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/agent/sessions"):
            return httpx.Response(
                201,
                json={
                    "session_id": "engine-session-1",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                    "investigation_ids": [],
                },
            )
        if request.method == "GET" and request.url.path.endswith(
            "/agent/sessions/engine-session-1"
        ):
            return httpx.Response(
                200,
                json={
                    "session_id": "engine-session-1",
                    "revision": 1,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "messages": [],
                    "investigation_ids": [],
                },
            )
        if request.method == "POST" and request.url.path.endswith("/turns"):
            return httpx.Response(
                422,
                json={
                    "error": "validation_error",
                    "detail": "Reasoning model does not support image attachments.",
                },
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
        agent=AgentSettings(model_id="text-model"),
        sessions=SessionSettings(dsn=str(tmp_path / "platform.sqlite3")),
        vision=VisionSettings(store_path=tmp_path / "images"),
    )

    with TestClient(create_app(settings)) as client:
        session = client.post("/api/v1/sessions", json={}).json()
        asset = client.post(
            f"/api/v1/vision/sessions/{session['id']}/assets",
            files={"upload": ("scene.png", image_bytes, "image/png")},
        ).json()
        response = client.post(
            f"/api/v1/chat/sessions/{session['id']}/turns",
            json={"message": "Describe this image", "asset_ids": [asset["id"]]},
        )

    assert response.status_code == 200
    assert '"type":"run.failed"' in response.text
    assert "Reasoning model does not support image attachments." in response.text
