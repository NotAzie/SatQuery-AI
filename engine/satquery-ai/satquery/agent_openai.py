"""OpenAI Chat Completions adapter for SatQuery's provider-neutral Agent protocol."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from .agent import AgentImageData, AgentMessage, AgentModelEvent, AgentToolCall

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIChatAgentModel:
    """Streaming adapter for the OpenAI Chat Completions tool-calling protocol."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        supports_vision: bool = False,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("Agent model name must not be empty.")
        if not api_key.strip():
            raise ValueError("Agent API key must not be empty.")
        parsed_url = httpx.URL(base_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.host
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError("Agent base URL must be an HTTP(S) origin/path without credentials.")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Agent request timeout must be finite and greater than zero.")
        self.model = model.strip()
        self.model_id = f"openai/{self.model}"
        self.supports_vision = supports_vision
        self.api_key = api_key
        self.base_url = str(parsed_url).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @classmethod
    def from_environment(cls) -> OpenAIChatAgentModel | None:
        """Build the adapter only when its explicit model setting is present."""
        model = os.environ.get("SATQUERY_AGENT_OPENAI_MODEL", "").strip()
        if not model:
            return None
        api_key = (
            os.environ.get("SATQUERY_AGENT_OPENAI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        if not api_key.strip():
            raise ValueError(
                "SATQUERY_AGENT_OPENAI_MODEL is set but no Agent API key is configured; "
                "set SATQUERY_AGENT_OPENAI_API_KEY or OPENAI_API_KEY."
            )
        raw_timeout = os.environ.get("SATQUERY_AGENT_OPENAI_TIMEOUT", "120")
        try:
            timeout_seconds = float(raw_timeout)
        except ValueError as exc:
            raise ValueError("SATQUERY_AGENT_OPENAI_TIMEOUT must be a number.") from exc
        raw_vision = os.environ.get(
            "SATQUERY_AGENT_OPENAI_SUPPORTS_VISION", "false"
        ).strip().lower()
        if raw_vision not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError(
                "SATQUERY_AGENT_OPENAI_SUPPORTS_VISION must be true or false."
            )
        return cls(
            model=model,
            api_key=api_key,
            supports_vision=raw_vision in {"true", "1", "yes"},
            base_url=os.environ.get("SATQUERY_AGENT_OPENAI_BASE_URL", _DEFAULT_BASE_URL),
            timeout_seconds=timeout_seconds,
        )

    async def stream(
        self,
        messages: tuple[AgentMessage, ...],
        tools: tuple[dict[str, Any], ...],
        *,
        system_prompt: str,
        cancellation: asyncio.Event,
    ) -> AsyncIterator[AgentModelEvent]:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                *(_message_payload(message) for message in messages),
            ],
            "stream": True,
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "description": item["description"],
                        "parameters": item["input_schema"],
                    },
                }
                for item in tools
            ]

        tool_deltas: dict[int, dict[str, str]] = {}
        timeout = httpx.Timeout(self.timeout_seconds)
        async with (
            httpx.AsyncClient(
                timeout=timeout,
                transport=self.transport,
            ) as client,
            client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request,
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if cancellation.is_set():
                    return
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                chunk = json.loads(data)
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield AgentModelEvent(kind="text_delta", text=content)
                    for item in delta.get("tool_calls", []):
                        index = item.get("index")
                        if not isinstance(index, int):
                            raise TypeError("Provider returned a tool call without an index.")
                        target = tool_deltas.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        if item.get("id"):
                            target["id"] += item["id"]
                        function = item.get("function") or {}
                        if function.get("name"):
                            target["name"] += function["name"]
                        if function.get("arguments"):
                            target["arguments"] += function["arguments"]
                if cancellation.is_set():
                    return

        for index in sorted(tool_deltas):
            item = tool_deltas[index]
            if not item["id"] or not item["name"]:
                raise ValueError("Provider returned an incomplete tool call.")
            arguments = json.loads(item["arguments"] or "{}")
            if not isinstance(arguments, Mapping):
                raise TypeError("Provider tool arguments must be a JSON object.")
            yield AgentModelEvent(
                kind="tool_call",
                tool_call=AgentToolCall(
                    call_id=item["id"],
                    tool_id=item["name"],
                    arguments=dict(arguments),
                ),
            )
        if not cancellation.is_set():
            yield AgentModelEvent(kind="completed")


def _message_payload(message: AgentMessage) -> dict[str, Any]:
    if message.role == "tool":
        if message.tool_call_id is None:
            raise ValueError("Persisted tool messages must include their call ID.")
        payload: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }
        if message.tool_name:
            payload["name"] = message.tool_name
        return payload

    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.tool_id,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
                for call in message.tool_calls
            ],
        }

    if message.role == "user" and message.images:
        content: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": _image_data_url(image)},
            }
            for image in message.images
        )
        return {"role": "user", "content": content}
    return {"role": message.role, "content": message.content}


def _image_data_url(image: AgentImageData) -> str:
    mime_type = image.mime_type
    data = image.data
    if mime_type == "image/tiff":
        from PIL import Image

        with Image.open(io.BytesIO(data)) as decoded:
            output = io.BytesIO()
            decoded.convert("RGB").save(output, format="PNG")
        mime_type = "image/png"
        data = output.getvalue()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
