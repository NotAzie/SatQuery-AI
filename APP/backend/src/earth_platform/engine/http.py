"""HTTP adapter for SatQuery Engine's published Agent API."""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from earth_platform.engine.errors import EngineUnavailableError
from earth_platform.engine.models import EngineAgentEvent, EngineAgentSession, EngineHealth
from earth_platform.settings.models import EngineSettings


class HttpEngineClient:
    """Forward Platform requests to the Engine without reimplementing its agent loop."""

    def __init__(
        self,
        settings: EngineSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        base_url = settings.base_url
        if not base_url:
            raise EngineUnavailableError("engine.base_url is required for engine.kind 'http'")
        self._settings = settings
        self._base_url = f"{base_url.rstrip('/')}/"
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key := self._settings.api_key():
            headers["Authorization"] = f"Bearer {api_key.get_secret_value()}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(self._settings.timeout_s),
            transport=self._transport,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise EngineUnavailableError("SatQuery Engine HTTP client is not connected")
        return self._client

    async def health(self) -> EngineHealth:
        try:
            response = await self._http().get("api/v1/health")
        except httpx.RequestError as exc:
            return EngineHealth(status="unavailable", detail=str(exc))
        if not response.is_success:
            return EngineHealth(
                status="unavailable",
                detail=f"SatQuery Engine health endpoint returned HTTP {response.status_code}",
            )
        try:
            body: Any = response.json()
        except ValueError:
            return EngineHealth(status="unavailable", detail="Invalid Engine health response")
        if not isinstance(body, dict) or not isinstance(body.get("ready"), bool):
            return EngineHealth(status="unavailable", detail="Invalid Engine health response")
        version = body.get("version")
        return EngineHealth(
            status="ok" if body["ready"] else "degraded",
            version=version if isinstance(version, str) else None,
            detail=None if body["ready"] else "SatQuery Engine reports that it is not ready",
        )

    async def create_agent_session(self) -> EngineAgentSession:
        response = await self._request("POST", "api/v1/agent/sessions")
        return self._parse_session(response)

    async def get_agent_session(self, session_id: str) -> EngineAgentSession:
        response = await self._request("GET", f"api/v1/agent/sessions/{quote(session_id, safe='')}")
        return self._parse_session(response)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http().request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise EngineUnavailableError(f"Could not reach SatQuery Engine: {exc}") from exc
        if not response.is_success:
            detail = _response_detail(response)
            raise EngineUnavailableError(
                f"SatQuery Engine returned HTTP {response.status_code}: {detail}"
            )
        return response

    @staticmethod
    def _parse_session(response: httpx.Response) -> EngineAgentSession:
        try:
            return EngineAgentSession.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid Agent session response"
            ) from exc

    async def stream_agent_turn(
        self,
        session_id: str,
        *,
        message: str,
        model_id: str,
        execution_authorized: bool = False,
    ) -> AsyncIterator[EngineAgentEvent]:
        path = f"api/v1/agent/sessions/{quote(session_id, safe='')}/turns"
        body = {
            "message": message,
            "model_id": model_id,
            "execution_authorized": execution_authorized,
        }
        try:
            async with self._http().stream(
                "POST",
                path,
                json=body,
                headers={"Accept": "text/event-stream"},
                timeout=httpx.Timeout(
                    connect=self._settings.timeout_s,
                    read=None,
                    write=self._settings.timeout_s,
                    pool=self._settings.timeout_s,
                ),
            ) as response:
                if not response.is_success:
                    await response.aread()
                    detail = _response_detail(response)
                    raise EngineUnavailableError(
                        f"SatQuery Engine returned HTTP {response.status_code}: {detail}"
                    )
                async for event_data in _sse_data(response):
                    try:
                        yield EngineAgentEvent.model_validate_json(event_data)
                    except (ValueError, TypeError) as exc:
                        raise EngineUnavailableError(
                            "SatQuery Engine streamed an invalid Agent event"
                        ) from exc
        except httpx.RequestError as exc:
            raise EngineUnavailableError(f"Could not reach SatQuery Engine: {exc}") from exc

    async def cancel_agent_turn(self, session_id: str) -> None:
        await self._request(
            "POST",
            f"api/v1/agent/sessions/{quote(session_id, safe='')}/cancel",
        )


async def _sse_data(response: httpx.Response) -> AsyncIterator[str]:
    data: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data:
                yield "\n".join(data)
                data.clear()
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if field == "data" and separator:
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        yield "\n".join(data)


def _response_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "request was rejected"
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
    return "request was rejected"
