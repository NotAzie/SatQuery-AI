import json
import sqlite3

import httpx
from fastapi.testclient import TestClient

from earth_platform.engine.factory import _ADAPTERS
from earth_platform.engine.http import HttpEngineClient
from earth_platform.main import create_app
from earth_platform.settings import Settings
from earth_platform.settings.models import AgentSettings, EngineSettings, SessionSettings


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
            "kind": "turn.completed",
            "session_id": "engine-session-1",
            "turn_id": "turn-1",
            "sequence": 3,
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
    assert [row[0] for row in stored_events] == [1, 2, 3]
    assert json.loads(stored_events[1][1])["payload"]["text"] == "Engine response"


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
