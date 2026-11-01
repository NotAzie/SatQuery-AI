from __future__ import annotations

import json
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from satquery.platform.config import PlatformConfig
from satquery.platform.contracts import (
    EarthQuery,
    Mission,
    ObservationStackMember,
    Task,
    TemporalDifferenceDiagnostic,
    utc_now,
)
from satquery.platform.investigations import (
    InMemoryInvestigationRepository,
    InMemoryMissionRepository,
    InvestigationService,
    MissionService,
)
from satquery.platform.monitoring import (
    InMemoryMonitoringRepository,
    MonitoringEvent,
    MonitoringRevisionConflict,
    MonitoringSchedule,
    MonitoringScheduleUpdate,
    MonitoringService,
    MonitoringTriggerPolicy,
    SQLiteMonitoringRepository,
)


def test_sqlite_monitoring_schedule_claim_is_atomic_and_survives_reopen():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", dir=Path.cwd(), delete=False) as handle:
        database_path = Path(handle.name)
    try:
        now = utc_now()
        schedule = MonitoringSchedule(
            schedule_id="schedule-atomic",
            mission_id="mission-atomic",
            name="Repeat observation",
            earth_query=EarthQuery(requested_variables=("air_temperature",)),
            interval_seconds=30,
            next_run_at=now - timedelta(seconds=65),
            created_at=now - timedelta(seconds=70),
            updated_at=now - timedelta(seconds=70),
        )
        first_repository = SQLiteMonitoringRepository(database_path)
        first_repository.create(schedule)
        second_repository = SQLiteMonitoringRepository(database_path)

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = tuple(pool.map(
                lambda repository: repository.claim_due(schedule.schedule_id, now),
                (first_repository, second_repository),
            ))
        claimed = tuple(item for item in claims if item is not None)
        assert len(claimed) == 1
        run = claimed[0]
        assert run.missed_intervals == 2
        assert run.schedule_revision == 1
        assert first_repository.get(schedule.schedule_id).revision == 1

        completed = run.model_copy(update={
            "status": "completed",
            "finished_at": now,
            "investigation_id": "investigation-atomic",
            "execution_id": "execution-atomic",
        })
        first_repository.finish(completed)

        reopened = SQLiteMonitoringRepository(database_path)
        assert reopened.runs(schedule.schedule_id) == (completed,)
        assert reopened.get(schedule.schedule_id).next_run_at > now
        assert reopened.get(schedule.schedule_id).revision == 1
        assert reopened.claim_due(schedule.schedule_id, now) is None
        events = reopened.events(schedule.schedule_id)
        assert [event.event_type for event in events] == [
            "schedule_created", "run_claimed", "run_completed"
        ]
    finally:
        database_path.unlink(missing_ok=True)


@pytest.mark.parametrize("repository_kind", ["memory", "sqlite"])
def test_monitoring_event_pages_are_stable_and_cover_same_timestamp_history(
    repository_kind,
):
    database_path = None
    if repository_kind == "memory":
        repository = InMemoryMonitoringRepository()
    else:
        with tempfile.NamedTemporaryFile(
            suffix=".sqlite", dir=Path.cwd(), delete=False
        ) as handle:
            database_path = Path(handle.name)
        repository = SQLiteMonitoringRepository(database_path)
    now = utc_now()
    schedule = MonitoringSchedule(
        schedule_id=f"event-pages-{repository_kind}",
        mission_id="mission-event-pages",
        name="Event page test",
        earth_query=EarthQuery(requested_variables=("air_temperature",)),
        interval_seconds=60,
        next_run_at=now,
        created_at=now,
        updated_at=now,
    )
    repository.create(schedule)
    expected_ids = [f"event-page-{index}" for index in range(7)]
    for event_id in expected_ids:
        assert repository.record_event(MonitoringEvent(
            event_id=event_id,
            event_type="trigger_evaluated",
            schedule_id=schedule.schedule_id,
            occurred_at=now,
            payload={},
        ))

    try:
        cursor = None
        pages = []
        while True:
            page = repository.event_page(schedule.schedule_id, limit=3, cursor=cursor)
            pages.append(page)
            if not page.has_more:
                break
            cursor = page.next_cursor
            assert cursor

        paged_ids = [event.event_id for page in pages for event in page.events]
        assert len(paged_ids) == len(set(paged_ids))
        assert set(paged_ids) == {
            *expected_ids, f"{schedule.schedule_id}:revision:1:created"
        }
        for page in pages:
            assert list(page.events) == sorted(
                page.events, key=lambda event: (event.occurred_at, event.event_id)
            )
        assert repository.get_event(expected_ids[3]).event_id == expected_ids[3]
        service = MonitoringService(repository, None, None)
        complete_history = service.all_events(schedule.schedule_id, page_size=3)
        assert len(complete_history) == len(paged_ids)
        assert tuple(service.iter_events(schedule.schedule_id, page_size=3)) == tuple(
            reversed(complete_history)
        )
        with pytest.raises(ValueError, match="cursor is invalid"):
            repository.event_page(schedule.schedule_id, cursor="not-a-cursor")
    finally:
        if database_path is not None:
            database_path.unlink(missing_ok=True)


def test_schedule_rejects_naive_times_and_nonpositive_intervals():
    common = {
        "schedule_id": "invalid",
        "mission_id": "mission",
        "name": "Invalid schedule",
        "earth_query": EarthQuery(),
        "interval_seconds": 1,
    }
    from pydantic import ValidationError

    try:
        MonitoringSchedule(**{**common, "interval_seconds": 0})
    except ValidationError:
        pass
    else:
        raise AssertionError("zero interval must be rejected")
    try:
        MonitoringSchedule(**{**common, "next_run_at": "2026-01-01T00:00:00"})
    except ValidationError:
        pass
    else:
        raise AssertionError("naive schedule timestamps must be rejected")


def test_monitoring_poller_configuration_requires_durable_storage_in_production():
    from satquery.errors import ConfigurationError

    config = PlatformConfig.load(
        environ={},
        overrides={"monitoring": {
            "enabled": True, "poll_interval_seconds": 2.5,
            "max_concurrency": 3, "lease_seconds": 45,
        }},
    )
    assert config.monitoring.enabled is True
    assert config.monitoring.poll_interval_seconds == 2.5
    assert config.monitoring.max_concurrency == 3
    assert config.monitoring.lease_seconds == 45

    try:
        PlatformConfig.load(
            environ={},
            overrides={"profile": "production", "monitoring": {"enabled": True}},
        )
    except ConfigurationError as exc:
        assert "durable storage path" in str(exc)
    else:
        raise AssertionError("production scheduler must require durable state")

    durable = PlatformConfig.load(
        environ={},
        overrides={
            "profile": "production",
            "monitoring": {"enabled": True},
            "storage": {"monitoring_path": "monitoring.sqlite"},
        },
    )
    assert durable.create_monitoring_repository().__class__.__name__ == "SQLiteMonitoringRepository"


def test_scheduler_cancellation_finalizes_claimed_run():
    import asyncio

    missions = MissionService(InMemoryMissionRepository(), InvestigationService(InMemoryInvestigationRepository()))
    mission = missions.create(Mission(name="Cancellation", objective="Test scheduler cancellation"))
    repository = InMemoryMonitoringRepository()
    schedule = MonitoringSchedule(
        schedule_id="schedule-cancel", mission_id=mission.mission_id,
        name="Cancellable", earth_query=EarthQuery(), interval_seconds=60,
        next_run_at=utc_now() - timedelta(seconds=1),
    )
    repository.create(schedule)
    service = MonitoringService(repository, missions, missions.investigations)

    async def pause(_investigation_id):
        await asyncio.Event().wait()

    async def exercise():
        task = asyncio.create_task(service.run_due(pause))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("scheduler cancellation must propagate")

    asyncio.run(exercise())
    run = repository.runs(schedule.schedule_id)[0]
    assert run.status == "failed"
    assert run.failure_type == "scheduler_cancelled"


def test_schedule_configuration_revisions_change_only_for_user_state_changes():
    repository = InMemoryMonitoringRepository()
    now = utc_now()
    schedule = MonitoringSchedule(
        schedule_id="schedule-revision", mission_id="mission-revision",
        name="Versioned schedule", earth_query=EarthQuery(), interval_seconds=60,
        next_run_at=now - timedelta(seconds=1),
    )
    repository.create(schedule)

    run = repository.claim_due(schedule.schedule_id, now)
    assert run is not None
    assert run.schedule_revision == 1
    assert repository.get(schedule.schedule_id).revision == 1

    enabled = repository.set_enabled(schedule.schedule_id, False, now)
    assert enabled.revision == 2
    assert repository.set_enabled(schedule.schedule_id, False, now) == enabled
    assert repository.get(schedule.schedule_id).revision == 2


def test_schedule_edits_are_optimistic_versioned_and_runs_keep_their_revision():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", dir=Path.cwd(), delete=False) as handle:
        database_path = Path(handle.name)
    try:
        repositories = (
            InMemoryMonitoringRepository(),
            SQLiteMonitoringRepository(database_path),
        )
        for index, repository in enumerate(repositories):
            now = utc_now()
            schedule = MonitoringSchedule(
                schedule_id=f"schedule-edit-{index}", mission_id="mission-edit",
                name="Original definition", earth_query=EarthQuery(), interval_seconds=60,
                next_run_at=now - timedelta(seconds=1),
                created_at=now - timedelta(seconds=2),
                updated_at=now - timedelta(seconds=2),
            )
            repository.create(schedule)
            update = MonitoringScheduleUpdate(
                expected_revision=1, name="Revised definition", interval_seconds=90,
            )
            revised = repository.revise(schedule.schedule_id, update, now)
            assert revised.revision == 2
            assert revised.name == "Revised definition"
            try:
                repository.revise(schedule.schedule_id, update, now)
            except MonitoringRevisionConflict:
                pass
            else:
                raise AssertionError("stale schedule edits must fail with a revision conflict")
            run = repository.claim_due(schedule.schedule_id, now)
            assert run is not None
            assert run.schedule_revision == 2
    finally:
        database_path.unlink(missing_ok=True)


def test_monitoring_runs_use_bounded_deterministic_concurrency():
    import asyncio

    missions = MissionService(InMemoryMissionRepository(), InvestigationService(InMemoryInvestigationRepository()))
    mission = missions.create(Mission(name="Concurrency", objective="Test bounded dispatch"))
    repository = InMemoryMonitoringRepository()
    now = utc_now()
    for index in range(3):
        repository.create(MonitoringSchedule(
            schedule_id=f"schedule-parallel-{index}", mission_id=mission.mission_id,
            name=f"Parallel schedule {index}", earth_query=EarthQuery(),
            interval_seconds=60, next_run_at=now - timedelta(seconds=1),
        ))
    service = MonitoringService(
        repository, missions, missions.investigations, max_concurrency=2
    )
    active = 0
    maximum_active = 0

    async def fail_after_delay(_investigation_id):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        raise RuntimeError("deterministic test failure")

    runs = asyncio.run(service.run_due(fail_after_delay, now=now, limit=3))
    assert len(runs) == 3
    assert all(run.status == "failed" for run in runs)
    assert maximum_active == 2


def test_expired_monitoring_lease_recovers_without_replaying_the_acquisition():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", dir=Path.cwd(), delete=False) as handle:
        database_path = Path(handle.name)
    try:
        repository = SQLiteMonitoringRepository(database_path)
        now = utc_now()
        schedule = MonitoringSchedule(
            schedule_id="schedule-expired", mission_id="mission-expired",
            name="Expired run", earth_query=EarthQuery(), interval_seconds=60,
            next_run_at=now - timedelta(seconds=1),
            created_at=now - timedelta(seconds=2),
            updated_at=now - timedelta(seconds=2),
        )
        repository.create(schedule)
        claimed = repository.claim_due(
            schedule.schedule_id, now, "worker-gone", now - timedelta(seconds=1)
        )
        assert claimed is not None

        recovered = repository.recover_expired(now)
        assert len(recovered) == 1
        assert recovered[0].status == "failed"
        assert recovered[0].failure_type == "worker_lease_expired"
        assert repository.claim_due(schedule.schedule_id, now, "worker-new") is None

        reopened = SQLiteMonitoringRepository(database_path)
        assert reopened.runs(schedule.schedule_id) == recovered
        assert [event.event_type for event in reopened.events(schedule.schedule_id)] == [
            "schedule_created", "run_claimed", "run_lease_expired"
        ]
        notifications = reopened.notifications(schedule.schedule_id, unread_only=True)
        assert len(notifications) == 1
        assert notifications[0].severity == "error"
        acknowledged = reopened.acknowledge_notification(
            notifications[0].notification_id, now
        )
        assert acknowledged.status == "acknowledged"
        final_repository = SQLiteMonitoringRepository(database_path)
        assert final_repository.notifications(
            schedule.schedule_id, unread_only=True
        ) == ()
        assert final_repository.events(schedule.schedule_id)[-1].event_type == "notification_acknowledged"
    finally:
        database_path.unlink(missing_ok=True)


def test_active_worker_heartbeat_prevents_expired_lease_recovery():
    repository = InMemoryMonitoringRepository()
    now = utc_now()
    schedule = MonitoringSchedule(
        schedule_id="schedule-heartbeat", mission_id="mission-heartbeat",
        name="Heartbeating run", earth_query=EarthQuery(), interval_seconds=60,
        next_run_at=now - timedelta(seconds=1),
    )
    repository.create(schedule)
    claimed = repository.claim_due(
        schedule.schedule_id, now, "worker-live", now + timedelta(seconds=1)
    )
    assert claimed is not None
    renewed = repository.heartbeat(
        claimed.run_id, "worker-live", now + timedelta(seconds=30)
    )
    assert renewed.lease_expires_at == now + timedelta(seconds=30)
    assert repository.recover_expired(now + timedelta(seconds=2)) == ()


def test_monitoring_health_reports_due_work_and_expired_claims():
    service_missions = MissionService(
        InMemoryMissionRepository(),
        InvestigationService(InMemoryInvestigationRepository()),
    )
    mission = service_missions.create(
        Mission(name="Health", objective="Inspect scheduler health")
    )
    repository = InMemoryMonitoringRepository()
    now = utc_now()
    schedule = MonitoringSchedule(
        schedule_id="schedule-health", mission_id=mission.mission_id,
        name="Health schedule", earth_query=EarthQuery(), interval_seconds=1,
        next_run_at=now - timedelta(seconds=1),
    )
    repository.create(schedule)
    repository.claim_due(
        schedule.schedule_id, now, "worker-stalled", now - timedelta(seconds=1)
    )
    repository.record_event(MonitoringEvent(
        event_id="trigger:health:evaluated", event_type="trigger_evaluated",
        schedule_id=schedule.schedule_id, occurred_at=now,
        payload={"evaluation_id": "health", "matched": True},
    ))
    repository.record_event(MonitoringEvent(
        event_id="trigger:health:matched", event_type="trigger_matched",
        schedule_id=schedule.schedule_id, occurred_at=now,
        payload={"evaluation_id": "health"},
    ))
    health = MonitoringService(repository, service_missions, service_missions.investigations).health(
        now + timedelta(seconds=2)
    )
    assert health.schedule_count == 1
    assert health.enabled_schedule_count == 1
    assert health.running_run_count == 1
    assert health.expired_lease_count == 1
    assert health.due_schedule_count == 1
    assert health.blocked_due_schedule_count == 1
    assert health.trigger_evaluation_count == 1
    assert health.trigger_match_count == 1


def test_trigger_policy_requires_exact_variable_unit_and_operator_supplied_threshold():
    from pydantic import ValidationError

    policy = MonitoringTriggerPolicy(
        policy_id="rain-change", name="Rain change review",
        canonical_variable="precipitation", unit="mm", operator="abs_gte",
        threshold=10, follow_up_query=EarthQuery(), cooldown_seconds=600,
    )
    geometry = {"type": "Point", "coordinates": [12.0, 34.0]}
    metadata = {
        "observation_support_geometry": geometry,
        "observation_support_crs": "EPSG:4326",
    }
    earlier_time = utc_now() - timedelta(hours=1)
    earlier = ObservationStackMember(
        observation_id="observation-before", observed_at=earlier_time,
        value=2, unit="mm", source_variable="precipitation",
        source_measurement_metadata=metadata,
    )
    later = ObservationStackMember(
        observation_id="observation-after", observed_at=earlier_time + timedelta(hours=1),
        value=14, unit="mm", source_variable="precipitation",
        source_measurement_metadata=metadata,
    )
    diagnostic = TemporalDifferenceDiagnostic(
        diagnostic_id="difference-1", stack_id="stack-1",
        variable_key="precipitation", canonical_variable="precipitation", unit="mm",
        spatial_support_geometry=geometry, spatial_support_crs="EPSG:4326",
        spatial_alignment="exact_point_support", earlier=earlier, later=later,
        elapsed_seconds=3600, difference_value=12, method_id="difference",
        method_version="1.0.0",
    )
    assert policy.matches(diagnostic)
    assert not policy.model_copy(update={"unit": "cm"}).matches(diagnostic)
    assert not policy.model_copy(update={"canonical_variable": "temperature"}).matches(diagnostic)
    with pytest.raises(ValidationError):
        MonitoringTriggerPolicy(
            policy_id="unsafe", name="Unsafe retry", canonical_variable="x",
            unit="1", operator="gt", threshold=0, follow_up_query=EarthQuery(),
            max_attempts=2,
        )


def test_trigger_event_append_is_idempotent_and_survives_sqlite_reopen():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", dir=Path.cwd(), delete=False) as handle:
        database_path = Path(handle.name)
    try:
        repository = SQLiteMonitoringRepository(database_path)
        schedule = MonitoringSchedule(
            schedule_id="schedule-trigger-journal", mission_id="mission-trigger-journal",
            name="Trigger journal", earth_query=EarthQuery(), interval_seconds=30,
        )
        repository.create(schedule)
        event = MonitoringEvent(
            event_id="trigger:evaluation-1:evaluated", event_type="trigger_evaluated",
            schedule_id=schedule.schedule_id, occurred_at=utc_now(),
            payload={"evaluation_id": "evaluation-1", "matched": True},
        )
        assert repository.record_event(event)
        assert not repository.record_event(event)
        reopened = SQLiteMonitoringRepository(database_path)
        assert reopened.events(schedule.schedule_id)[-1] == event
    finally:
        database_path.unlink(missing_ok=True)


def test_matching_monitoring_policy_chains_one_idempotent_investigation():
    import asyncio
    from types import SimpleNamespace

    from satquery.platform.config import PlatformConfig
    from satquery.platform.runtime import PlatformRuntime

    runtime = PlatformRuntime(config=PlatformConfig.load(overrides={"profile": "testing"}))
    try:
        mission = runtime.mission_service.create(Mission(
            mission_id="mission-trigger-chain", name="Trigger chain",
            objective="Verify deterministic follow-up orchestration",
        ))
        policy = MonitoringTriggerPolicy(
            policy_id="high-rain-change", name="Review high rain change",
            canonical_variable="precipitation", unit="mm", operator="gt",
            threshold=5, follow_up_query=EarthQuery(
                requested_variables=("precipitation",),
            ), cooldown_seconds=3600, max_attempts=2, retry_safe=True,
        )
        now = utc_now()
        schedule = MonitoringSchedule(
            schedule_id="schedule-trigger-chain", mission_id=mission.mission_id,
            name="Rain watch", earth_query=EarthQuery(), interval_seconds=60,
            trigger_policies=(policy,), next_run_at=now - timedelta(seconds=120),
        )
        runtime.create_monitoring_schedule(schedule)
        source_investigations = [
            runtime.mission_service.create_investigation(mission.mission_id)
            for _ in range(2)
        ]
        repository = runtime.monitoring_service.repository
        for index, source in enumerate(source_investigations):
            due = now + timedelta(seconds=60 * index)
            run = repository.claim_due(schedule.schedule_id, due)
            assert run is not None
            repository.finish(run.model_copy(update={
                "status": "completed", "finished_at": due,
                "investigation_id": source.investigation_id,
            }))

        geometry = {"type": "Point", "coordinates": [12.0, 34.0]}
        metadata = {
            "observation_support_geometry": geometry,
            "observation_support_crs": "EPSG:4326",
        }
        start = now - timedelta(hours=2)
        earlier = ObservationStackMember(
            observation_id="rain-before", observed_at=start, value=1, unit="mm",
            source_variable="precipitation", source_measurement_metadata=metadata,
        )
        later = ObservationStackMember(
            observation_id="rain-after", observed_at=start + timedelta(hours=1),
            value=9, unit="mm", source_variable="precipitation",
            source_measurement_metadata=metadata,
        )
        diagnostic = TemporalDifferenceDiagnostic(
            diagnostic_id="rain-difference", stack_id="rain-stack",
            variable_key="precipitation", canonical_variable="precipitation", unit="mm",
            spatial_support_geometry=geometry, spatial_support_crs="EPSG:4326",
            spatial_alignment="exact_point_support", earlier=earlier, later=later,
            elapsed_seconds=3600, difference_value=8, method_id="descriptive-difference",
            method_version="1.0.0",
        )
        runtime.compare_monitoring_schedule = lambda _schedule_id: SimpleNamespace(
            temporal_diagnostics=(diagnostic,), comparison_sha256="a" * 64,
        )

        async def complete_follow_up(investigation_id, *, resume=False):
            runtime.investigation_service.start(investigation_id)
            runtime.investigation_service.complete(investigation_id, "test execution")
            return SimpleNamespace(plan_id="test-execution")

        runtime.execute_investigation = complete_follow_up
        asyncio.run(runtime._run_monitoring_trigger_policies(now=now, limit=5))
        children = runtime.investigation_service.list_for_mission(mission.mission_id)
        triggered = [item for item in children if item.investigation_id.startswith("triggered-")]
        assert len(triggered) == 1, str(tuple(
            (event.event_type, event.payload)
            for event in runtime.monitoring_service.events(schedule.schedule_id, limit=100)
        ))
        assert triggered[0].status.value == "completed"
        trigger_context = triggered[0].tasks[0].parameters["monitoring_trigger"]
        assert triggered[0].tasks[0].max_attempts == 2
        assert triggered[0].tasks[0].retry_safe is True
        assert trigger_context["source_observation_ids"] == ["rain-before", "rain-after"]
        assert trigger_context["uncertainty_status"] == "not_propagated"
        asyncio.run(runtime._run_monitoring_trigger_policies(now=now, limit=5))
        assert len([
            item for item in runtime.investigation_service.list_for_mission(mission.mission_id)
            if item.investigation_id.startswith("triggered-")
        ]) == 1
        events = runtime.monitoring_service.events(schedule.schedule_id, limit=100)
        assert {item.event_type for item in events} >= {
            "trigger_evaluated", "trigger_matched", "trigger_investigation_created",
            "trigger_investigation_completed",
        }
        evaluated = next(item for item in events if item.event_type == "trigger_evaluated")
        assert evaluated.payload["source_observation_ids"] == [
            "rain-before", "rain-after",
        ]
        assert evaluated.payload["comparison_sha256"] == "a" * 64
        evaluated_artifact = runtime.earth_memory.get(
            f"monitor-event:{evaluated.event_id}"
        )
        assert evaluated_artifact is not None
        assert evaluated_artifact.source_artifact_ids
    finally:
        asyncio.run(runtime.close())


def test_monitoring_execution_respects_configured_per_tick_run_budget():
    import asyncio

    from satquery.platform.runtime import PlatformRuntime

    runtime = PlatformRuntime(config=PlatformConfig.load(overrides={
        "profile": "testing",
        "monitoring": {
            "max_runs_per_tick": 2,
            "max_triggered_investigations_per_tick": 2,
        },
    }))
    requested_limits = []

    async def no_runs(_execute, *, now=None, limit=100):
        requested_limits.append(limit)
        return ()

    runtime.monitoring_service.run_due = no_runs
    policy_limits = []

    async def one_recovery(*, limit, now):
        assert limit == 2
        return 1

    async def record_policy_budget(*, now, limit):
        policy_limits.append(limit)

    runtime._recover_monitoring_trigger_chains = one_recovery
    runtime._run_monitoring_trigger_policies = record_policy_budget
    try:
        assert asyncio.run(runtime.run_due_monitoring(limit=100)) == ()
        assert requested_limits == [2]
        assert policy_limits == [1]
    finally:
        asyncio.run(runtime.close())


def test_trigger_chain_recovers_same_investigation_after_runtime_restart():
    import asyncio
    from types import SimpleNamespace

    from satquery.platform.runtime import PlatformRuntime

    with tempfile.NamedTemporaryFile(suffix=".sqlite", dir=Path.cwd(), delete=False) as handle:
        database = Path(handle.name)
    overrides = {
        "profile": "testing",
        "storage": {
            "lifecycle_path": str(database),
            "monitoring_path": str(database),
        },
    }
    try:
        first_runtime = PlatformRuntime(config=PlatformConfig.load(overrides=overrides))
        now = utc_now()
        mission = first_runtime.mission_service.create(Mission(
            mission_id="mission-recovery",
            name="Recovery mission",
            objective="Resume a durable policy-triggered investigation",
        ))
        policy = MonitoringTriggerPolicy(
            policy_id="recovery-policy", name="Recovery policy",
            canonical_variable="precipitation", unit="mm", operator="gt",
            threshold=5, follow_up_query=EarthQuery(),
        )
        schedule = first_runtime.create_monitoring_schedule(MonitoringSchedule(
            schedule_id="schedule-recovery", mission_id=mission.mission_id,
            name="Recovery schedule", earth_query=EarthQuery(), interval_seconds=60,
            trigger_policies=(policy,),
        ))
        evaluation_id = "recovery-evaluation"
        investigation_id = "triggered-recovery-investigation"
        child = first_runtime.mission_service.create_investigation(
            mission.mission_id,
            (Task(
                task_id="trigger-task-recovery", handler="earth.observe",
                description="Recover persisted follow-up",
                parameters={"earth_query": EarthQuery().model_dump(mode="json")},
            ),),
            investigation_id=investigation_id,
        )
        first_runtime.monitoring_service.record_event(MonitoringEvent(
            event_id=f"trigger:{evaluation_id}:investigation-created",
            event_type="trigger_investigation_created",
            schedule_id=schedule.schedule_id,
            occurred_at=now,
            payload={
                "evaluation_id": evaluation_id,
                "policy_id": policy.policy_id,
                "policy": policy.model_dump(mode="json"),
                "investigation_id": child.investigation_id,
            },
        ))
        asyncio.run(first_runtime.close())

        restarted = PlatformRuntime(config=PlatformConfig.load(overrides=overrides))
        calls = []

        async def resume_existing(identifier, *, resume=False):
            calls.append((identifier, resume))
            restarted.investigation_service.start(identifier)
            restarted.investigation_service.complete(identifier, "recovered")
            return SimpleNamespace(plan_id="recovered-execution")

        restarted.execute_investigation = resume_existing
        try:
            recovered = asyncio.run(restarted._recover_monitoring_trigger_chains(
                limit=1, now=utc_now(),
            ))
            assert recovered == 1
            assert calls == [(investigation_id, False)]
            assert restarted.investigation_service.get(investigation_id).status.value == "completed"
            events = restarted.monitoring_service.events(schedule.schedule_id, limit=20)
            terminal = [
                event for event in events
                if event.event_id == f"trigger:{evaluation_id}:investigation-terminal"
            ]
            assert len(terminal) == 1
            assert terminal[0].event_type == "trigger_investigation_completed"
            assert asyncio.run(restarted._recover_monitoring_trigger_chains(
                limit=1, now=utc_now(),
            )) == 0
            assert len(calls) == 1
        finally:
            asyncio.run(restarted.close())
    finally:
        database.unlink(missing_ok=True)
def test_schema_migration_finalizes_legacy_unleased_runs_without_replaying_them():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", dir=Path.cwd(), delete=False) as handle:
        database_path = Path(handle.name)
    run_id = "monitor-run:legacy:2026-01-01T00:00:00+00:00"
    old_payload = {
        "run_id": run_id, "schedule_id": "legacy", "mission_id": "legacy-mission",
        "scheduled_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:01+00:00", "finished_at": None,
        "status": "running", "investigation_id": None, "execution_id": None,
        "missed_intervals": 0, "failure_type": None,
    }
    try:
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                "CREATE TABLE satquery_monitoring_schema (singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
            )
            connection.execute("INSERT INTO satquery_monitoring_schema VALUES (1, 1)")
            connection.execute(
                "CREATE TABLE satquery_monitoring_schedules (schedule_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, next_run_at TEXT NOT NULL, enabled INTEGER NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE satquery_monitoring_runs (run_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, scheduled_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(schedule_id, scheduled_at))"
            )
            connection.execute(
                "INSERT INTO satquery_monitoring_runs VALUES (?, ?, ?, 'running', ?)",
                (run_id, "legacy", "2026-01-01T00:00:00+00:00", json.dumps(old_payload)),
            )
            connection.commit()
        finally:
            connection.close()

        migrated = SQLiteMonitoringRepository(database_path)
        recovered = migrated.runs("legacy")
        assert len(recovered) == 1
        assert recovered[0].status == "failed"
        assert recovered[0].failure_type == "legacy_run_recovered_without_lease"
        assert recovered[0].schedule_revision == 1
        assert migrated.events("legacy")[-1].event_type == "run_lease_expired"
        assert migrated.notifications("legacy", unread_only=True)
    finally:
        database_path.unlink(missing_ok=True)


def test_default_schedule_policy_coalesces_due_work_until_active_run_finishes():
    repository = InMemoryMonitoringRepository()
    now = utc_now()
    schedule = MonitoringSchedule(
        schedule_id="schedule-no-overlap", mission_id="mission-no-overlap",
        name="No overlap", earth_query=EarthQuery(), interval_seconds=10,
        next_run_at=now,
    )
    repository.create(schedule)
    active = repository.claim_due(schedule.schedule_id, now)
    assert active is not None
    assert repository.claim_due(
        schedule.schedule_id, now + timedelta(seconds=35)
    ) is None
    assert repository.get(schedule.schedule_id).next_run_at <= now + timedelta(seconds=35)

    repository.finish(active.model_copy(update={
        "status": "completed", "finished_at": now + timedelta(seconds=35),
    }))
    coalesced = repository.claim_due(
        schedule.schedule_id, now + timedelta(seconds=35)
    )
    assert coalesced is not None
    assert coalesced.missed_intervals == 2
