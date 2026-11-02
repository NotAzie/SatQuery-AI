"""Engine-owned mission and monitoring schedule operations."""

from fastapi import APIRouter, Query

from earth_platform.api.deps import EngineDep
from earth_platform.engine.models import (
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

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/missions", response_model=list[EngineMission])
async def list_missions(engine: EngineDep) -> list[EngineMission]:
    return await engine.list_missions()


@router.post("/missions", response_model=EngineMission, status_code=201)
async def create_mission(
    mission: EngineMissionCreate, engine: EngineDep
) -> EngineMission:
    return await engine.create_mission(mission)


@router.get("/schedules", response_model=list[EngineMonitoringSchedule])
async def list_schedules(engine: EngineDep) -> list[EngineMonitoringSchedule]:
    return await engine.list_monitoring_schedules()


@router.post("/schedules", response_model=EngineMonitoringSchedule, status_code=201)
async def create_schedule(
    schedule: EngineMonitoringScheduleCreate, engine: EngineDep
) -> EngineMonitoringSchedule:
    return await engine.create_monitoring_schedule(schedule)


@router.patch("/schedules/{schedule_id}", response_model=EngineMonitoringSchedule)
async def revise_schedule(
    schedule_id: str,
    update: EngineMonitoringScheduleUpdate,
    engine: EngineDep,
) -> EngineMonitoringSchedule:
    return await engine.revise_monitoring_schedule(schedule_id, update)


@router.post(
    "/schedules/{schedule_id}/enable", response_model=EngineMonitoringSchedule
)
async def enable_schedule(
    schedule_id: str, engine: EngineDep
) -> EngineMonitoringSchedule:
    return await engine.set_monitoring_schedule_enabled(schedule_id, enabled=True)


@router.post(
    "/schedules/{schedule_id}/disable", response_model=EngineMonitoringSchedule
)
async def disable_schedule(
    schedule_id: str, engine: EngineDep
) -> EngineMonitoringSchedule:
    return await engine.set_monitoring_schedule_enabled(schedule_id, enabled=False)


@router.get(
    "/schedules/{schedule_id}/runs", response_model=list[EngineMonitoringRun]
)
async def list_schedule_runs(
    schedule_id: str, engine: EngineDep
) -> list[EngineMonitoringRun]:
    return await engine.list_monitoring_runs(schedule_id)


@router.get(
    "/schedules/{schedule_id}/comparison",
    response_model=EngineMonitoringComparison,
)
async def compare_schedule(
    schedule_id: str,
    engine: EngineDep,
    limit: int = Query(default=10, ge=2, le=20),
) -> EngineMonitoringComparison:
    return await engine.compare_monitoring_schedule(schedule_id, limit=limit)


@router.get(
    "/notifications", response_model=list[EngineMonitoringNotification]
)
async def list_notifications(
    engine: EngineDep,
    schedule_id: str | None = None,
    unread_only: bool = False,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[EngineMonitoringNotification]:
    return await engine.list_monitoring_notifications(
        schedule_id=schedule_id,
        unread_only=unread_only,
        limit=limit,
    )


@router.post(
    "/notifications/{notification_id}/acknowledge",
    response_model=EngineMonitoringNotification,
)
async def acknowledge_notification(
    notification_id: str, engine: EngineDep
) -> EngineMonitoringNotification:
    return await engine.acknowledge_monitoring_notification(notification_id)


@router.get(
    "/schedules/{schedule_id}/triggers",
    response_model=EngineMonitoringTriggerHistory,
)
async def get_schedule_triggers(
    schedule_id: str,
    engine: EngineDep,
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = None,
) -> EngineMonitoringTriggerHistory:
    return await engine.get_monitoring_triggers(
        schedule_id, limit=limit, cursor=cursor
    )
