"""HTTP adapter for SatQuery Engine's published Agent API."""

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from earth_platform.engine.errors import EngineUnavailableError
from earth_platform.engine.models import (
    EngineAgentEvent,
    EngineAgentImage,
    EngineAgentSession,
    EngineAgentToolDescriptor,
    EngineDatasetMetadata,
    EngineEarthCapabilitySnapshot,
    EngineEarthContext,
    EngineEarthObjectGeoJSON,
    EngineHealth,
    EngineHypothesisCreateRequest,
    EngineHypothesisLifecycleResponse,
    EngineHypothesisMutationResponse,
    EngineHypothesisTransitionRequest,
    EngineImageCapability,
    EngineInvestigationComparison,
    EngineInvestigationComparisonRequest,
    EngineInvestigationEventPage,
    EngineInvestigationReasoningResponse,
    EngineInvestigationReport,
    EngineInvestigationReproducibilityBundle,
    EngineMission,
    EngineMissionCreate,
    EngineMonitoringComparison,
    EngineMonitoringNotification,
    EngineMonitoringRun,
    EngineMonitoringSchedule,
    EngineMonitoringScheduleCreate,
    EngineMonitoringScheduleUpdate,
    EngineMonitoringTriggerHistory,
    EngineObservation,
    EngineScientificReasoningReport,
)
from earth_platform.settings.models import EngineSettings
from earth_platform.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class HttpEngineClient:
    """Forward Agent turns and read Engine-authored reports without duplicating Engine logic."""

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

    async def list_engine_datasets(self) -> list[EngineDatasetMetadata]:
        response = await self._request("GET", "api/v1/platform/datasets")
        return self._parse_list(response, EngineDatasetMetadata, "dataset metadata")

    async def list_engine_image_capabilities(self) -> list[EngineImageCapability]:
        response = await self._request("GET", "api/v1/capabilities")
        return self._parse_list(response, EngineImageCapability, "image-analysis capability")

    async def list_engine_agent_tools(self) -> list[EngineAgentToolDescriptor]:
        response = await self._request("GET", "api/v1/agent/tools")
        return self._parse_list(response, EngineAgentToolDescriptor, "Agent tool descriptor")

    async def get_engine_earth_capabilities(self) -> EngineEarthCapabilitySnapshot:
        response = await self._request("GET", "api/v1/platform/earth/capabilities")
        try:
            return EngineEarthCapabilitySnapshot.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid Earth capability snapshot"
            ) from exc

    async def create_agent_session(self) -> EngineAgentSession:
        response = await self._request("POST", "api/v1/agent/sessions")
        return self._parse_session(response)

    async def get_agent_session(self, session_id: str) -> EngineAgentSession:
        response = await self._request("GET", f"api/v1/agent/sessions/{quote(session_id, safe='')}")
        return self._parse_session(response)

    async def get_investigation_report(self, investigation_id: str) -> EngineInvestigationReport:
        response = await self._request(
            "GET",
            f"api/v1/platform/investigations/{quote(investigation_id, safe='')}/report",
        )
        try:
            body: Any = response.json()
            if not isinstance(body, dict):
                raise TypeError("report response must be an object")
            investigation = body.get("investigation")
            if (
                not isinstance(investigation, dict)
                or investigation.get("investigation_id") != investigation_id
            ):
                raise ValueError("report investigation does not match the request")
            return EngineInvestigationReport.model_validate(
                {
                    "report_id": body.get("report_id"),
                    "report_sha256": body.get("report_sha256"),
                    "investigation_id": investigation_id,
                    "markdown": body.get("markdown"),
                }
            )
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid investigation report"
            ) from exc

    async def get_investigation_reasoning(
        self, investigation_id: str
    ) -> EngineInvestigationReasoningResponse:
        response = await self._request(
            "GET",
            f"api/v1/platform/investigations/{quote(investigation_id, safe='')}/reasoning",
        )
        try:
            body: Any = response.json()
            if (
                isinstance(body, dict)
                and body.get("status") == "not_evaluated"
                and body.get("reasoning") is None
            ):
                return EngineInvestigationReasoningResponse.model_validate(body)
            report = EngineScientificReasoningReport.model_validate(body)
            if report.investigation_id != investigation_id:
                raise ValueError("reasoning investigation does not match the request")
            return EngineInvestigationReasoningResponse(
                status=report.status,
                reasoning=report,
            )
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid investigation reasoning report"
            ) from exc

    async def get_investigation_reproducibility(
        self, investigation_id: str
    ) -> EngineInvestigationReproducibilityBundle:
        response = await self._request(
            "GET",
            f"api/v1/platform/investigations/{quote(investigation_id, safe='')}/reproducibility",
        )
        try:
            bundle = EngineInvestigationReproducibilityBundle.model_validate(response.json())
            if bundle.investigation_id != investigation_id:
                raise ValueError("reproducibility bundle investigation does not match the request")
            digest_payload = bundle.model_dump(
                mode="json", exclude={"bundle_sha256", "exported_at"}
            )
            canonical_payload = json.dumps(
                digest_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
                allow_nan=False,
            )
            actual_digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(actual_digest, bundle.bundle_sha256):
                raise ValueError("reproducibility bundle digest does not match its contents")
            return bundle
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid investigation reproducibility bundle"
            ) from exc

    async def create_investigation_comparison(
        self, request: EngineInvestigationComparisonRequest
    ) -> EngineInvestigationComparison:
        response = await self._request(
            "POST",
            "api/v1/platform/investigation-comparisons",
            json=request.model_dump(mode="json"),
        )
        try:
            return EngineInvestigationComparison.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid investigation comparison"
            ) from exc

    async def get_investigation_comparison(
        self, comparison_sha256: str
    ) -> EngineInvestigationComparison:
        response = await self._request(
            "GET",
            f"api/v1/platform/investigation-comparisons/{quote(comparison_sha256, safe='')}",
        )
        try:
            comparison = EngineInvestigationComparison.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid investigation comparison"
            ) from exc
        if comparison.comparison_sha256 != comparison_sha256:
            raise EngineUnavailableError(
                "SatQuery Engine returned a comparison with a different digest"
            )
        return comparison

    async def get_investigation_earth_objects(
        self, investigation_id: str
    ) -> EngineEarthObjectGeoJSON:
        response = await self._request(
            "GET",
            "api/v1/platform/earth-objects/geojson",
            params={"investigation_id": investigation_id},
        )
        try:
            return EngineEarthObjectGeoJSON.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned invalid investigation Earth Object GeoJSON"
            ) from exc

    async def get_investigation_observations(
        self, investigation_id: str
    ) -> list[EngineObservation]:
        response = await self._request(
            "GET",
            f"api/v1/platform/investigations/{quote(investigation_id, safe='')}/observations",
        )
        return self._parse_list(response, EngineObservation, "investigation observation")

    async def get_investigation_events(
        self,
        session_id: str,
        investigation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> EngineInvestigationEventPage:
        response = await self._request(
            "GET",
            (
                f"api/v1/agent/sessions/{quote(session_id, safe='')}"
                f"/investigations/{quote(investigation_id, safe='')}/events"
            ),
            params={"after_sequence": after_sequence, "limit": limit},
        )
        try:
            page = EngineInvestigationEventPage.model_validate(response.json())
            if page.investigation_id != investigation_id:
                raise ValueError("investigation id does not match the request")
            return page
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid investigation event page"
            ) from exc

    async def get_investigation_hypotheses(
        self, investigation_id: str
    ) -> EngineHypothesisLifecycleResponse:
        response = await self._request(
            "GET",
            f"api/v1/platform/investigations/{quote(investigation_id, safe='')}/hypotheses",
            accepted_statuses=frozenset({409}),
        )
        try:
            return EngineHypothesisLifecycleResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid hypothesis lifecycle"
            ) from exc

    async def add_investigation_hypothesis(
        self, investigation_id: str, request: EngineHypothesisCreateRequest
    ) -> EngineHypothesisMutationResponse:
        response = await self._request(
            "POST",
            f"api/v1/platform/investigations/{quote(investigation_id, safe='')}/hypotheses",
            json=request.model_dump(mode="json"),
        )
        try:
            return EngineHypothesisMutationResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid hypothesis creation response"
            ) from exc

    async def transition_investigation_hypothesis(
        self,
        investigation_id: str,
        hypothesis_id: str,
        request: EngineHypothesisTransitionRequest,
    ) -> EngineHypothesisMutationResponse:
        response = await self._request(
            "POST",
            "api/v1/platform/investigations/"
            f"{quote(investigation_id, safe='')}/hypotheses/"
            f"{quote(hypothesis_id, safe='')}/transitions",
            json=request.model_dump(mode="json"),
        )
        try:
            return EngineHypothesisMutationResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid hypothesis transition response"
            ) from exc

    async def list_missions(self) -> list[EngineMission]:
        response = await self._request("GET", "api/v1/platform/missions")
        return self._parse_list(response, EngineMission, "mission")

    async def create_mission(self, mission: EngineMissionCreate) -> EngineMission:
        response = await self._request(
            "POST",
            "api/v1/platform/missions",
            json=mission.model_dump(mode="json"),
        )
        try:
            return EngineMission.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid mission response"
            ) from exc

    async def list_monitoring_schedules(self) -> list[EngineMonitoringSchedule]:
        response = await self._request("GET", "api/v1/platform/monitoring/schedules")
        return self._parse_list(response, EngineMonitoringSchedule, "monitoring schedule")

    async def create_monitoring_schedule(
        self, schedule: EngineMonitoringScheduleCreate
    ) -> EngineMonitoringSchedule:
        response = await self._request(
            "POST",
            "api/v1/platform/monitoring/schedules",
            json=schedule.model_dump(mode="json"),
        )
        try:
            return EngineMonitoringSchedule.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid monitoring schedule response"
            ) from exc

    async def revise_monitoring_schedule(
        self, schedule_id: str, update: EngineMonitoringScheduleUpdate
    ) -> EngineMonitoringSchedule:
        response = await self._request(
            "PATCH",
            f"api/v1/platform/monitoring/schedules/{quote(schedule_id, safe='')}",
            json=update.model_dump(mode="json", exclude_unset=True),
        )
        try:
            return EngineMonitoringSchedule.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid monitoring schedule response"
            ) from exc

    async def set_monitoring_schedule_enabled(
        self, schedule_id: str, enabled: bool
    ) -> EngineMonitoringSchedule:
        action = "enable" if enabled else "disable"
        response = await self._request(
            "POST",
            f"api/v1/platform/monitoring/schedules/{quote(schedule_id, safe='')}/{action}",
        )
        try:
            return EngineMonitoringSchedule.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid monitoring schedule response"
            ) from exc

    async def list_monitoring_runs(self, schedule_id: str) -> list[EngineMonitoringRun]:
        response = await self._request(
            "GET",
            f"api/v1/platform/monitoring/schedules/{quote(schedule_id, safe='')}/runs",
        )
        return self._parse_list(response, EngineMonitoringRun, "monitoring run")

    async def compare_monitoring_schedule(
        self, schedule_id: str, *, limit: int = 10
    ) -> EngineMonitoringComparison:
        response = await self._request(
            "GET",
            f"api/v1/platform/monitoring/schedules/{quote(schedule_id, safe='')}/comparison",
            params={"limit": limit},
        )
        try:
            return EngineMonitoringComparison.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid monitoring comparison"
            ) from exc

    async def list_monitoring_notifications(
        self,
        *,
        schedule_id: str | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> list[EngineMonitoringNotification]:
        params: dict[str, str | int | bool] = {
            "unread_only": unread_only,
            "limit": limit,
        }
        if schedule_id is not None:
            params["schedule_id"] = schedule_id
        response = await self._request(
            "GET",
            "api/v1/platform/monitoring/notifications",
            params=params,
        )
        return self._parse_list(response, EngineMonitoringNotification, "monitoring notification")

    async def acknowledge_monitoring_notification(
        self, notification_id: str
    ) -> EngineMonitoringNotification:
        response = await self._request(
            "POST",
            "api/v1/platform/monitoring/notifications/"
            f"{quote(notification_id, safe='')}/acknowledge",
        )
        try:
            return EngineMonitoringNotification.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned an invalid monitoring notification"
            ) from exc

    async def get_monitoring_triggers(
        self, schedule_id: str, *, limit: int = 100, cursor: str | None = None
    ) -> EngineMonitoringTriggerHistory:
        params: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        response = await self._request(
            "GET",
            f"api/v1/platform/monitoring/schedules/{quote(schedule_id, safe='')}/triggers",
            params=params,
        )
        try:
            return EngineMonitoringTriggerHistory.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                "SatQuery Engine returned invalid monitoring trigger history"
            ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        accepted_statuses: frozenset[int] = frozenset(),
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            response = await self._http().request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise EngineUnavailableError(f"Could not reach SatQuery Engine: {exc}") from exc
        if not response.is_success and response.status_code not in accepted_statuses:
            detail = _response_detail(response)
            if response.status_code == 404:
                raise NotFoundError(detail)
            if response.status_code == 409:
                raise ConflictError(detail)
            if response.status_code == 422:
                raise ValidationFailedError(detail)
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

    @staticmethod
    def _parse_list(response: httpx.Response, model: type[ModelT], resource: str) -> list[ModelT]:
        try:
            body: Any = response.json()
            if not isinstance(body, list):
                raise TypeError("response must be a list")
            return [model.model_validate(item) for item in body]
        except (ValueError, TypeError) as exc:
            raise EngineUnavailableError(
                f"SatQuery Engine returned an invalid {resource} list"
            ) from exc

    async def stream_agent_turn(
        self,
        session_id: str,
        *,
        message: str,
        model_id: str,
        execution_authorized: bool = False,
        earth_context: EngineEarthContext | None = None,
        attachments: list[EngineAgentImage] | None = None,
    ) -> AsyncIterator[EngineAgentEvent]:
        path = f"api/v1/agent/sessions/{quote(session_id, safe='')}/turns"
        body: dict[str, object] = {
            "message": message,
            "model_id": model_id,
            "execution_authorized": execution_authorized,
        }
        if earth_context is not None:
            body["earth_context"] = earth_context.model_dump(mode="json")
        if attachments:
            body["attachments"] = [attachment.model_dump(mode="json") for attachment in attachments]
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
                    if response.status_code == 422:
                        raise ValidationFailedError(detail)
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
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
    return "request was rejected"
