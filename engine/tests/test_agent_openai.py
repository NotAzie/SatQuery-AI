import asyncio
import json

import httpx
import pytest
from satquery.agent import (
    AgentImageData,
    AgentMessage,
    AgentToolCall,
)
from satquery.agent_openai import OpenAIChatAgentModel


def _sse(*payloads: dict) -> bytes:
    serialized = [
        b"data: " + json.dumps(payload).encode() + b"\n\n"
        for payload in payloads
    ]
    return b"".join((*serialized, b"data: [DONE]\n\n"))


def test_stream_translates_text_and_incremental_tool_calls():
    async def run():
        captured = {}

        async def respond(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            captured["authorization"] = request.headers["authorization"]
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse(
                    {"choices": [{"delta": {"content": "Checking "}}]},
                    {
                        "choices": [{
                            "delta": {
                                "tool_calls": [{
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "platform.capabilities",
                                        "arguments": "{\"detail\":",
                                    },
                                }]
                            }
                        }]
                    },
                    {
                        "choices": [{
                            "delta": {
                                "tool_calls": [{
                                    "index": 0,
                                    "function": {"arguments": " true}"},
                                }]
                            }
                        }]
                    },
                ),
            )

        model = OpenAIChatAgentModel(
            model="gpt-example",
            api_key="test-key",
            supports_vision=True,
            transport=httpx.MockTransport(respond),
        )
        events = [
            event
            async for event in model.stream(
                (
                    AgentMessage(
                        role="user",
                        content="What can you do?",
                        turn_id="turn-1",
                    ),
                ),
                ({
                    "name": "platform.capabilities",
                    "description": "List capabilities.",
                    "input_schema": {"type": "object"},
                },),
                system_prompt="Use Engine tools.",
                cancellation=asyncio.Event(),
            )
        ]

        assert [event.kind for event in events] == [
            "text_delta",
            "tool_call",
            "completed",
        ]
        assert events[0].text == "Checking "
        assert events[1].tool_call == AgentToolCall(
            call_id="call_1",
            tool_id="platform.capabilities",
            arguments={"detail": True},
        )
        assert captured["authorization"] == "Bearer test-key"
        assert captured["payload"]["messages"][0] == {
            "role": "system",
            "content": "Use Engine tools.",
        }
        assert captured["payload"]["tools"][0]["function"]["name"] == (
            "platform.capabilities"
        )

    asyncio.run(run())


def test_stream_serializes_prior_tool_exchange_and_vision_image():
    async def run():
        captured = {}
        image_bytes = b"\x89PNG\r\n\x1a\nimage"

        async def respond(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse({"choices": [{"delta": {"content": "Seen."}}]}),
            )

        model = OpenAIChatAgentModel(
            model="gpt-example",
            api_key="test-key",
            transport=httpx.MockTransport(respond),
        )
        messages = (
            AgentMessage(
                role="assistant",
                content="",
                turn_id="turn-1",
                tool_calls=(
                    AgentToolCall(
                        call_id="call_1",
                        tool_id="platform.capabilities",
                        arguments={},
                    ),
                ),
            ),
            AgentMessage(
                role="tool",
                content='{"ok":true}',
                turn_id="turn-1",
                tool_call_id="call_1",
                tool_name="platform.capabilities",
            ),
            AgentMessage(
                role="user",
                content="Describe this image.",
                turn_id="turn-2",
                images=(
                    AgentImageData(
                        asset_id="image-1",
                        mime_type="image/png",
                        size_bytes=len(image_bytes),
                        sha256="a" * 64,
                        data=image_bytes,
                    ),
                ),
            ),
        )
        events = [
            event
            async for event in model.stream(
                messages,
                (),
                system_prompt="system",
                cancellation=asyncio.Event(),
            )
        ]

        payload_messages = captured["payload"]["messages"]
        assert payload_messages[1]["tool_calls"][0]["id"] == "call_1"
        assert payload_messages[2]["tool_call_id"] == "call_1"
        image_url = payload_messages[3]["content"][1]["image_url"]["url"]
        assert image_url.startswith("data:image/png;base64,")
        assert events[-1].kind == "completed"

    asyncio.run(run())


def test_environment_registration_requires_model_and_key(monkeypatch):
    monkeypatch.delenv("SATQUERY_AGENT_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("SATQUERY_AGENT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert OpenAIChatAgentModel.from_environment() is None

    monkeypatch.setenv("SATQUERY_AGENT_OPENAI_MODEL", "gpt-example")
    with pytest.raises(ValueError, match="no Agent API key"):
        OpenAIChatAgentModel.from_environment()

    monkeypatch.setenv("SATQUERY_AGENT_OPENAI_API_KEY", "secret")
    model = OpenAIChatAgentModel.from_environment()
    assert model is not None
    assert model.model_id == "openai/gpt-example"
    assert model.supports_vision is False

    monkeypatch.setenv("SATQUERY_AGENT_OPENAI_SUPPORTS_VISION", "true")
    model = OpenAIChatAgentModel.from_environment()
    assert model is not None
    assert model.supports_vision is True


def test_engine_registers_openai_agent_only_when_explicitly_configured(monkeypatch):
    from satquery.config import Settings
    from satquery.orchestrator import SatQueryEngine

    monkeypatch.setenv("SATQUERY_AGENT_OPENAI_MODEL", "gpt-example")
    monkeypatch.setenv("SATQUERY_AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SATQUERY_AGENT_OPENAI_SUPPORTS_VISION", raising=False)
    engine = SatQueryEngine(Settings.from_env(dotenv_path=None))
    assert engine.platform_registries.reasoners.names() == ("openai/gpt-example",)

    monkeypatch.delenv("SATQUERY_AGENT_OPENAI_MODEL")
    monkeypatch.delenv("SATQUERY_AGENT_OPENAI_API_KEY")
    unconfigured = SatQueryEngine(Settings.from_env(dotenv_path=None))
    assert unconfigured.platform_registries.reasoners.names() == ()
