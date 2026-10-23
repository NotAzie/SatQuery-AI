"""Versioned synchronous client for the SatQuery platform API.

The client intentionally returns the server's JSON contracts without silently
coercing them into local models. This keeps newer server fields visible and
lets clients pin request/response validation to the API schema they need.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .errors import SatQueryError

CLIENT_API_VERSION = "1"


class PlatformAPIError(SatQueryError):
    """A transport or HTTP failure returned by the SatQuery platform API."""

    code = "platform_api_error"
    status_code = 502

    def __init__(
        self,
        message: str,
        *,
        method: str,
        url: str,
        status_code: int = 502,
        payload: Any = None,
        remediation: list[str] | None = None,
        recoverable: bool | None = None,
    ) -> None:
        super().__init__(
            message,
            remediation=remediation,
            context={
                "method": method,
                "url": url,
                "status_code": status_code,
                "payload": payload,
            },
            recoverable=recoverable,
        )
        self.status_code = status_code
        self.payload = payload


class SatQueryClient:
    """Synchronous client for a running SatQuery API.

    The client does not retry requests: repeating an acquisition or lifecycle
    mutation after an ambiguous network failure could create duplicate work.
    Callers can inject an ``httpx.Client`` or transport for controlled testing.
    """

    api_version = CLIENT_API_VERSION

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        timeout: float = 60.0,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        parsed_url = urlsplit(normalized_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(
                "base_url must be an absolute HTTP or HTTPS origin/path without credentials or query"
            )
        self.base_url = normalized_url
        self._owns_http_client = http_client is None
        if http_client is None:
            request_headers = {"Accept": "application/json"}
            request_headers.update(headers or {})
            if token:
                request_headers["Authorization"] = f"Bearer {token}"
            self._http = httpx.Client(
                base_url=self.base_url,
                timeout=timeout,
                headers=request_headers,
                transport=transport,
            )
        else:
            self._http = http_client
        # Resource groups are deliberately thin route clients. They share this
        # transport, path validation, JSON handling, and error contract rather
        # than maintaining a second implementation of platform behavior.
        from .client_resources import (
            EarthMemoryResource,
            EarthObjectsResource,
            EarthResource,
            InvestigationsResource,
            MissionsResource,
            MonitoringResource,
            PlatformResource,
            ScientificResource,
        )

        self.platform = PlatformResource(self)
        self.earth = EarthResource(self)
        self.missions = MissionsResource(self)
        self.investigations = InvestigationsResource(self)
        self.monitoring = MonitoringResource(self)
        self.objects = EarthObjectsResource(self)
        self.memory = EarthMemoryResource(self)
        self.science = ScientificResource(self)

    def close(self) -> None:
        """Close the underlying transport when this client created it."""
        if self._owns_http_client:
            self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Send one JSON API request and return its decoded response body."""
        method = method.upper()
        parsed_path = urlsplit(path)
        if (
            not path.startswith("/")
            or path.startswith("//")
            or parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.fragment
        ):
            raise ValueError(
                "path must be an absolute API path without a host or fragment"
            )
        url = f"{self.base_url}{path}"
        try:
            response = self._http.request(
                method,
                url,
                json=payload,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise PlatformAPIError(
                "The SatQuery platform API could not be reached.",
                method=method,
                url=url,
                remediation=[
                    "Start the platform with `python -m satquery serve`.",
                    "Check the API base URL and network connectivity.",
                ],
                recoverable=True,
            ) from exc

        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text} if response.text else None
        if response.is_success:
            return body

        error_body = body if isinstance(body, Mapping) else {}
        detail = (
            error_body.get("detail")
            or error_body.get("message")
            or error_body.get("error")
            or response.reason_phrase
        )
        remediation = error_body.get("remediation", [])
        if not isinstance(remediation, list) or not all(
            isinstance(item, str) for item in remediation
        ):
            remediation = []
        raise PlatformAPIError(
            str(detail),
            method=method,
            url=str(response.request.url),
            status_code=response.status_code,
            payload=body,
            remediation=remediation,
            recoverable=response.status_code == 429 or response.status_code >= 500,
        )

    def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(
        self, path: str, *, payload: Any = None, params: Mapping[str, Any] | None = None
    ) -> Any:
        return self.request("POST", path, payload=payload, params=params)

    def patch(
        self, path: str, *, payload: Any, params: Mapping[str, Any] | None = None
    ) -> Any:
        return self.request("PATCH", path, payload=payload, params=params)

    def stream_json_events(
        self, path: str, *, params: Mapping[str, Any] | None = None
    ) -> Iterator[Any]:
        """Yield JSON data frames from a Server-Sent Events endpoint."""
        parsed_path = urlsplit(path)
        if (
            not path.startswith("/")
            or path.startswith("//")
            or parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.fragment
        ):
            raise ValueError(
                "path must be an absolute API path without a host or fragment"
            )
        url = f"{self.base_url}{path}"
        try:
            with self._http.stream(
                "GET",
                url,
                params=params,
                headers={"Accept": "text/event-stream"},
            ) as response:
                if not response.is_success:
                    response.read()
                    try:
                        body = response.json()
                    except ValueError:
                        body = {"detail": response.text} if response.text else None
                    error_body = body if isinstance(body, Mapping) else {}
                    detail = (
                        error_body.get("detail")
                        or error_body.get("message")
                        or error_body.get("error")
                        or response.reason_phrase
                    )
                    raise PlatformAPIError(
                        str(detail),
                        method="GET",
                        url=str(response.request.url),
                        status_code=response.status_code,
                        payload=body,
                        recoverable=response.status_code == 429
                        or response.status_code >= 500,
                    )
                data_lines: list[str] = []
                for line in response.iter_lines():
                    if not line:
                        if data_lines:
                            yield json.loads("\n".join(data_lines))
                            data_lines.clear()
                    elif line.startswith(":"):
                        continue
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                if data_lines:
                    yield json.loads("\n".join(data_lines))
        except httpx.HTTPError as exc:
            raise PlatformAPIError(
                "The SatQuery platform event stream could not be reached.",
                method="GET",
                url=url,
                remediation=[
                    "Start the platform with `python -m satquery serve`.",
                    "Check the API base URL and network connectivity.",
                ],
                recoverable=True,
            ) from exc

    def _json_value(self, value: Any) -> Any:
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json")
        if isinstance(value, Mapping):
            return dict(value)
        raise TypeError("expected a mapping or a Pydantic model")

    @staticmethod
    def _path_segment(value: str) -> str:
        if not value:
            raise ValueError("resource identifier must not be empty")
        return quote(value, safe="")

    def health(self) -> Any:
        return self.platform.runtime_health()

    def capability_matrix(self) -> Any:
        return self.platform.capability_matrix()

    def plan_earth(self, query: Any, *, explain: bool = False) -> Any:
        return self.earth.plan(query, explain=explain)

    def observe_earth(self, query: Any) -> Any:
        return self.earth.observe(query)

    def create_investigation(
        self,
        question: str,
        *,
        earth_query: Any = None,
        mission_name: str | None = None,
        mission_id: str | None = None,
    ) -> Any:
        return self.investigations.start(
            question,
            earth_query=earth_query,
            mission_name=mission_name,
            mission_id=mission_id,
        )

    def execute_investigation(self, investigation_id: str) -> Any:
        return self.investigations.execute(investigation_id)

    def investigation_report(self, investigation_id: str) -> Any:
        return self.investigations.report(investigation_id)

    def investigation_audit(self, investigation_id: str) -> Any:
        return self.investigations.audit(investigation_id)

    def investigation_reproducibility(self, investigation_id: str) -> Any:
        return self.investigations.reproducibility(investigation_id)

    def earth_memory_search(self, query: Mapping[str, Any]) -> Any:
        return self.memory.search(query)
