from collections.abc import AsyncIterator
from typing import Protocol

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


class EngineClient(Protocol):
    """The Platform boundary to SatQuery Engine's published APIs.

    The Engine owns provider execution, tool routing, scientific work, and its
    conversation transcript. The Platform forwards turns/events and retrieves Engine-authored
    reports for investigations linked to an Engine session.
    """

    async def connect(self) -> None: ...

    async def aclose(self) -> None: ...

    async def health(self) -> EngineHealth: ...

    async def list_engine_datasets(self) -> list[EngineDatasetMetadata]: ...

    async def list_engine_image_capabilities(self) -> list[EngineImageCapability]: ...

    async def list_engine_agent_tools(self) -> list[EngineAgentToolDescriptor]: ...

    async def get_engine_earth_capabilities(self) -> EngineEarthCapabilitySnapshot: ...

    async def create_agent_session(self) -> EngineAgentSession: ...

    async def get_agent_session(self, session_id: str) -> EngineAgentSession: ...

    async def get_investigation_report(
        self, investigation_id: str
    ) -> EngineInvestigationReport: ...

    async def get_investigation_earth_objects(
        self, investigation_id: str
    ) -> EngineEarthObjectGeoJSON: ...

    async def get_investigation_events(
        self,
        session_id: str,
        investigation_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> EngineInvestigationEventPage: ...

    async def list_missions(self) -> list[EngineMission]: ...

    async def create_mission(self, mission: EngineMissionCreate) -> EngineMission: ...

    async def list_monitoring_schedules(self) -> list[EngineMonitoringSchedule]: ...

    async def create_monitoring_schedule(
        self, schedule: EngineMonitoringScheduleCreate
    ) -> EngineMonitoringSchedule: ...

    async def revise_monitoring_schedule(
        self, schedule_id: str, update: EngineMonitoringScheduleUpdate
    ) -> EngineMonitoringSchedule: ...

    async def set_monitoring_schedule_enabled(
        self, schedule_id: str, enabled: bool
    ) -> EngineMonitoringSchedule: ...

    async def list_monitoring_runs(
        self, schedule_id: str
    ) -> list[EngineMonitoringRun]: ...

    async def compare_monitoring_schedule(
        self, schedule_id: str, *, limit: int = 10
    ) -> EngineMonitoringComparison: ...

    async def list_monitoring_notifications(
        self,
        *,
        schedule_id: str | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> list[EngineMonitoringNotification]: ...

    async def acknowledge_monitoring_notification(
        self, notification_id: str
    ) -> EngineMonitoringNotification: ...

    async def get_monitoring_triggers(
        self, schedule_id: str, *, limit: int = 100, cursor: str | None = None
    ) -> EngineMonitoringTriggerHistory: ...

    def stream_agent_turn(
        self,
        session_id: str,
        *,
        message: str,
        model_id: str,
        execution_authorized: bool = False,
        earth_context: EngineEarthContext | None = None,
        attachments: list[EngineAgentImage] | None = None,
    ) -> AsyncIterator[EngineAgentEvent]: ...

    async def cancel_agent_turn(self, session_id: str) -> None: ...
