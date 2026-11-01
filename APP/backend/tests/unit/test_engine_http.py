import json

import httpx
import pytest

from earth_platform.engine.errors import EngineUnavailableError
from earth_platform.engine.http import HttpEngineClient
from earth_platform.settings.models import EngineSettings


@pytest.mark.asyncio
async def test_http_engine_client_reads_agent_sse_and_forwards_authorization(monkeypatch):
    requested: list[httpx.Request] = []
    monkeypatch.setenv("TEST_ENGINE_KEY", "test-token")

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if request.url.path.endswith("/turns"):
            event = {
                "kind": "assistant.delta",
                "session_id": "agent-1",
                "turn_id": "turn-1",
                "sequence": 1,
                "timestamp": "2026-05-01T10:00:00Z",
                "payload": {"text": "hello"},
            }
            return httpx.Response(
                200,
                content=f"event: assistant.delta\nid: turn-1:1\ndata: {json.dumps(event)}\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json={"session_id": "agent-1"})

    client = HttpEngineClient(
        EngineSettings(
            kind="http",
            base_url="https://engine.test",
            api_key_env="TEST_ENGINE_KEY",
        ),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        streamed = [
            event
            async for event in client.stream_agent_turn(
                "agent-1",
                message="question",
                model_id="registered-model",
                execution_authorized=True,
            )
        ]
    finally:
        await client.aclose()

    assert len(streamed) == 1
    assert streamed[0].kind == "assistant.delta"
    assert streamed[0].payload == {"text": "hello"}
    assert requested[0].headers["authorization"] == "Bearer test-token"
    assert json.loads(requested[0].content) == {
        "message": "question",
        "model_id": "registered-model",
        "execution_authorized": True,
    }


@pytest.mark.asyncio
async def test_http_engine_client_reports_rejected_agent_session():
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"message": "agent service unavailable"}},
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        with pytest.raises(EngineUnavailableError, match="agent service unavailable"):
            await client.create_agent_session()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_engine_health_uses_engine_readiness_and_preserves_base_path():
    requested: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(
            200,
            json={"ready": False, "version": "1.2.3", "status": "degraded"},
        )

    client = HttpEngineClient(
        EngineSettings(kind="http", base_url="https://engine.test/proxy"),
        transport=httpx.MockTransport(handle),
    )
    await client.connect()
    try:
        health = await client.health()
    finally:
        await client.aclose()

    assert health.status == "degraded"
    assert health.version == "1.2.3"
    assert requested == ["/proxy/api/v1/health"]
