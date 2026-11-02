from collections.abc import AsyncIterator
from typing import NoReturn

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
    EngineImageCapability,
    EngineInvestigationEventPage,
    EngineInvestigationReport,
    EngineMission,
    EngineMissionCreate,
    EngineMonitoringComparison,
    EngineMonitoringNotification,
    EngineMonitoringRun,
    EngineMonitoringSchedule,
    EngineMonitoringScheduleCreate,
    EngineMonitoringScheduleUpdate,
    EngineMonitoringTriggerHistory,
)

_MESSAGE = "SatQuery Engine is not configured; set engine.kind and its connection settings"


class UnavailableEngineClient:
    """Explicit null object used until an Engine adapter is configured.

    It never fabricates results: every operation except ``health`` fails loudly.
    """

    async def connect(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def health(self) -> EngineHealth:
        return EngineHealth(status="unconfigured", detail=_MESSAGE)

    async def list_engine_datasets(self) -> list[EngineDatasetMetadata]:
        self._fail()

    async def list_engine_image_capabilities(self) -> list[EngineImageCapability]:
        self._fail()

    async def list_engine_agent_tools(self) -> list[EngineAgentToolDescriptor]:
        self._fail()

    async def get_engine_earth_capabilities(self) -> EngineEarthCapabilitySnapshot:
        self._fail()

    def _fail(self) -> NoReturn:
        raise EngineUnavailableError(_MESSAGE)

    async def create_agent_session(self) -> EngineAgentSession:
        self._fail()

    async def get_agent_session(self, session_id: str) -> EngineAgentSession:
        self._fail()

    async def get_investigation_report(
        self, investigation_id: str
    ) -> EngineInvestigationReport:
        self._fail()

    async def get_investigation_earth_objects(
        self, investigation_id: str
    ) -> EngineEarthObjectGeoJSON:
        self._fail()

    async def get_investigation_events(
        self,
        session_id: str,
        investigation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> EngineInvestigationEventPage:
        self._fail()

    async def list_missions(self) -> list[EngineMission]:
        self._fail()

    async def create_mission(self, mission: EngineMissionCreate) -> EngineMission:
        self._fail()

    async def list_monitoring_schedules(self) -> list[EngineMonitoringSchedule]:
        self._fail()

    async def create_monitoring_schedule(
        self, schedule: EngineMonitoringScheduleCreate
    ) -> EngineMonitoringSchedule:
        self._fail()

    async def revise_monitoring_schedule(
        self, schedule_id: str, update: EngineMonitoringScheduleUpdate
    ) -> EngineMonitoringSchedule:
        self._fail()

    async def set_monitoring_schedule_enabled(
        self, schedule_id: str, enabled: bool
    ) -> EngineMonitoringSchedule:
        self._fail()

    async def list_monitoring_runs(
        self, schedule_id: str
    ) -> list[EngineMonitoringRun]:
        self._fail()

    async def compare_monitoring_schedule(
        self, schedule_id: str, *, limit: int = 10
    ) -> EngineMonitoringComparison:
        self._fail()

    async def list_monitoring_notifications(
        self,
        *,
        schedule_id: str | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> list[EngineMonitoringNotification]:
        self._fail()

    async def acknowledge_monitoring_notification(
        self, notification_id: str
    ) -> EngineMonitoringNotification:
        self._fail()

    async def get_monitoring_triggers(
        self, schedule_id: str, *, limit: int = 100, cursor: str | None = None
    ) -> EngineMonitoringTriggerHistory:
        self._fail()

    def stream_agent_turn(
        self,
        session_id: str,
        *,
        message: str,
        model_id: str,
        execution_authorized: bool = False,
        earth_context: EngineEarthContext | None = None,
        attachments: list[EngineAgentImage] | None = None,
    ) -> AsyncIterator[EngineAgentEvent]:
        self._fail()

    async def cancel_agent_turn(self, session_id: str) -> None:
        self._fail()
