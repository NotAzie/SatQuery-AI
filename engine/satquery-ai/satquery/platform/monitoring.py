"""Persistent, deterministic scheduling for repeat Earth investigations.

The scheduler creates ordinary investigations and delegates all acquisition and
analysis to the registered investigation workflow. It does not infer changes or
run scientific methods of its own.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import sqlite3
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from .contracts import (
    Contract,
    EarthQuery,
    InvestigationStatus,
    MissionStatus,
    Task,
    utc_now,
)

logger = logging.getLogger(__name__)


class MonitoringSchedule(Contract):
    """A user-declared recurring EarthQuery attached to an active mission."""

    schedule_id: str = Field(default_factory=lambda: f"monitor-{uuid4().hex}", min_length=1)
    mission_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    earth_query: EarthQuery
    interval_seconds: int = Field(gt=0)
    priority: int = Field(default=0, ge=0, le=100)
    overlap_policy: Literal["skip_while_running", "allow"] = "skip_while_running"
    trigger_policies: tuple[MonitoringTriggerPolicy, ...] = ()
    enabled: bool = True
    next_run_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    revision: int = Field(default=1, ge=1)

    @field_validator("next_run_at", "created_at", "updated_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("monitoring schedule timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def unique_trigger_policy_ids(self) -> MonitoringSchedule:
        identifiers = [policy.policy_id for policy in self.trigger_policies]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("monitoring trigger policy identifiers must be unique")
        return self


class MonitoringTriggerPolicy(Contract):
    """Operator-authored rule over exact-support descriptive differences.

    A policy match is an operational condition only. It does not represent a
    significance test or a scientific conclusion.
    """

    policy_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    canonical_variable: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    operator: Literal["gt", "gte", "lt", "lte", "abs_gt", "abs_gte"]
    threshold: float
    follow_up_query: EarthQuery
    cooldown_seconds: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1, le=5)
    retry_safe: bool = False

    @field_validator("threshold")
    @classmethod
    def threshold_is_finite(cls, value: float) -> float:
        import math

        if not math.isfinite(value):
            raise ValueError("monitoring trigger threshold must be finite")
        return value

    @model_validator(mode="after")
    def retries_require_explicit_safety(self) -> MonitoringTriggerPolicy:
        if self.max_attempts > 1 and not self.retry_safe:
            raise ValueError("retries require explicit retry_safe=true")
        return self

    def matches(self, diagnostic) -> bool:
        """Return whether the configured scalar predicate matches a diagnostic."""
        if (
            diagnostic.interpretation_status != "descriptive_only"
            or diagnostic.uncertainty_status != "not_propagated"
            or diagnostic.canonical_variable != self.canonical_variable
            or diagnostic.unit != self.unit
        ):
            return False
        value = diagnostic.difference_value
        return {
            "gt": lambda: value > self.threshold,
            "gte": lambda: value >= self.threshold,
            "lt": lambda: value < self.threshold,
            "lte": lambda: value <= self.threshold,
            "abs_gt": lambda: abs(value) > self.threshold,
            "abs_gte": lambda: abs(value) >= self.threshold,
        }[self.operator]()


class MonitoringTriggerEvaluation(Contract):
    """Reproducible outcome of applying one policy to one diagnostic."""

    evaluation_id: str = Field(min_length=1)
    schedule_id: str = Field(min_length=1)
    schedule_revision: int = Field(ge=1)
    policy_id: str = Field(min_length=1)
    policy_name: str | None = None
    diagnostic_id: str = Field(min_length=1)
    source_observation_ids: tuple[str, str] | None = None
    source_run_id: str | None = None
    comparison_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    matched: bool
    reason: str = Field(min_length=1)
    evaluated_at: datetime


class MonitoringScheduleDefinition(Contract):
    """Immutable user-declared configuration for one schedule revision.

    ``next_run_at`` is scheduler state and is intentionally excluded. A due-run
    claim must not create a new scientific schedule version.
    """

    schedule_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    earth_query: EarthQuery
    interval_seconds: int = Field(gt=0)
    priority: int = Field(default=0, ge=0, le=100)
    overlap_policy: Literal["skip_while_running", "allow"]
    trigger_policies: tuple[MonitoringTriggerPolicy, ...] = ()
    enabled: bool
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class MonitoringScheduleUpdate(Contract):
    """Partial user edit guarded by the revision the operator inspected."""

    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1)
    earth_query: EarthQuery | None = None
    interval_seconds: int | None = Field(default=None, gt=0)
    priority: int | None = Field(default=None, ge=0, le=100)
    overlap_policy: Literal["skip_while_running", "allow"] | None = None
    trigger_policies: tuple[MonitoringTriggerPolicy, ...] | None = None

    @model_validator(mode="after")
    def _require_update_fields(self) -> MonitoringScheduleUpdate:
        changed = self.model_fields_set - {"expected_revision"}
        if not changed:
            raise ValueError("at least one schedule field must be updated")
        if any(getattr(self, field) is None for field in changed):
            raise ValueError("updated schedule fields cannot be null")
        return self


class MonitoringRevisionConflict(ValueError):
    """Raised when a schedule changed since the caller inspected it."""


class MonitoringRun(Contract):
    """Immutable record for one claimed schedule occurrence."""

    run_id: str = Field(min_length=1)
    schedule_id: str = Field(min_length=1)
    schedule_revision: int = Field(default=1, ge=1)
    mission_id: str = Field(min_length=1)
    scheduled_at: datetime
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "completed", "partial", "failed", "skipped"]
    investigation_id: str | None = None
    execution_id: str | None = None
    missed_intervals: int = Field(default=0, ge=0)
    failure_type: str | None = None
    worker_id: str | None = None
    lease_expires_at: datetime | None = None

    @field_validator("scheduled_at", "started_at", "finished_at", "lease_expires_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("monitoring run timestamps must be timezone-aware")
        return value


class MonitoringEvent(Contract):
    """Append-only operational event for schedule and run lifecycle changes."""

    event_id: str = Field(min_length=1)
    event_type: Literal[
        "schedule_created", "schedule_enabled", "schedule_disabled", "schedule_revised",
        "run_claimed", "run_completed", "run_partial", "run_failed",
        "run_skipped", "run_lease_expired", "notification_acknowledged",
        "trigger_evaluated", "trigger_matched", "trigger_suppressed_cooldown",
        "trigger_investigation_created", "trigger_investigation_completed",
        "trigger_investigation_failed",
    ]
    schedule_id: str = Field(min_length=1)
    run_id: str | None = None
    occurred_at: datetime
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("monitoring event timestamps must be timezone-aware")
        return value


class MonitoringEventPage(Contract):
    """A bounded, stable page of append-only events, newest page first."""

    events: tuple[MonitoringEvent, ...] = ()
    next_cursor: str | None = None
    has_more: bool = False


def _encode_event_cursor(event: MonitoringEvent) -> str:
    payload = json.dumps(
        [_time(event.occurred_at), event.event_id], separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_event_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        occurred_at, event_id = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii"))
        )
        timestamp = datetime.fromisoformat(occurred_at)
        if timestamp.tzinfo is None or not isinstance(event_id, str) or not event_id:
            raise ValueError
        return timestamp, event_id
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise ValueError("monitoring event cursor is invalid") from exc


class MonitoringHealth(Contract):
    """Operational scheduler snapshot; it contains no scientific assessment."""

    observed_at: datetime
    schedule_count: int = Field(ge=0)
    enabled_schedule_count: int = Field(ge=0)
    due_schedule_count: int = Field(ge=0)
    blocked_due_schedule_count: int = Field(ge=0)
    running_run_count: int = Field(ge=0)
    expired_lease_count: int = Field(ge=0)
    completed_run_count: int = Field(ge=0)
    partial_run_count: int = Field(ge=0)
    failed_run_count: int = Field(ge=0)
    trigger_evaluation_count: int = Field(ge=0)
    trigger_match_count: int = Field(ge=0)
    trigger_cooldown_suppression_count: int = Field(ge=0)
    triggered_investigation_completed_count: int = Field(ge=0)
    triggered_investigation_failed_count: int = Field(ge=0)
    last_run_at: datetime | None = None


class MonitoringNotification(Contract):
    """Local inbox projection for operationally important monitoring outcomes."""

    notification_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    schedule_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    severity: Literal["warning", "error"]
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    status: Literal["unread", "acknowledged"] = "unread"
    created_at: datetime
    acknowledged_at: datetime | None = None

    @field_validator("created_at", "acknowledged_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("monitoring notification timestamps must be timezone-aware")
        return value


class MonitoringRepository(Protocol):
    def create(self, schedule: MonitoringSchedule) -> None: ...
    def get(self, schedule_id: str) -> MonitoringSchedule: ...
    def list(self, mission_id: str | None = None) -> tuple[MonitoringSchedule, ...]: ...
    def set_enabled(self, schedule_id: str, enabled: bool, now: datetime) -> MonitoringSchedule: ...
    def revise(
        self, schedule_id: str, update: MonitoringScheduleUpdate, now: datetime
    ) -> MonitoringSchedule: ...
    def claim_due(
        self,
        schedule_id: str,
        now: datetime,
        worker_id: str = "monitoring:direct",
        lease_expires_at: datetime | None = None,
    ) -> MonitoringRun | None: ...
    def heartbeat(self, run_id: str, worker_id: str, lease_expires_at: datetime) -> MonitoringRun: ...
    def recover_expired(self, now: datetime) -> tuple[MonitoringRun, ...]: ...
    def finish(self, run: MonitoringRun) -> None: ...
    def runs(self, schedule_id: str) -> tuple[MonitoringRun, ...]: ...
    def all_runs(self) -> tuple[MonitoringRun, ...]: ...
    def events(
        self, schedule_id: str | None = None, limit: int = 100,
        run_id: str | None = None,
    ) -> tuple[MonitoringEvent, ...]: ...
    def event_page(
        self, schedule_id: str | None = None, limit: int = 100,
        run_id: str | None = None, cursor: str | None = None,
    ) -> MonitoringEventPage: ...
    def get_event(self, event_id: str) -> MonitoringEvent | None: ...
    def event_counts(self) -> dict[str, int]: ...
    def notifications(
        self, schedule_id: str | None = None, unread_only: bool = False,
        limit: int = 100,
    ) -> tuple[MonitoringNotification, ...]: ...
    def get_notification(self, notification_id: str) -> MonitoringNotification: ...
    def acknowledge_notification(
        self, notification_id: str, now: datetime
    ) -> MonitoringNotification: ...
    def record_event(self, event: MonitoringEvent) -> bool: ...


class InMemoryMonitoringRepository:
    """Thread-safe scheduler repository for local and deterministic tests."""

    def __init__(self) -> None:
        self._schedules: dict[str, MonitoringSchedule] = {}
        self._runs: dict[str, MonitoringRun] = {}
        self._events: list[MonitoringEvent] = []
        self._event_ids: set[str] = set()
        self._notifications: dict[str, MonitoringNotification] = {}
        self._lock = threading.RLock()

    def create(self, schedule: MonitoringSchedule) -> None:
        with self._lock:
            if schedule.schedule_id in self._schedules:
                raise ValueError("monitoring schedule identifier already exists")
            self._schedules[schedule.schedule_id] = schedule
            self._append_event(MonitoringEvent(
                event_id=f"{schedule.schedule_id}:revision:{schedule.revision}:created",
                event_type="schedule_created", schedule_id=schedule.schedule_id,
                occurred_at=schedule.created_at,
                payload={"revision": schedule.revision, "mission_id": schedule.mission_id},
            ))

    def get(self, schedule_id: str) -> MonitoringSchedule:
        with self._lock:
            try:
                return self._schedules[schedule_id]
            except KeyError as exc:
                raise KeyError(f"monitoring schedule {schedule_id!r} was not found") from exc

    def list(self, mission_id: str | None = None) -> tuple[MonitoringSchedule, ...]:
        with self._lock:
            return tuple(
                self._schedules[key]
                for key in sorted(self._schedules)
                if mission_id is None or self._schedules[key].mission_id == mission_id
            )

    def set_enabled(self, schedule_id: str, enabled: bool, now: datetime) -> MonitoringSchedule:
        with self._lock:
            current = self.get(schedule_id)
            if current.enabled == enabled:
                return current
            updated = current.model_copy(update={
                "enabled": enabled,
                "updated_at": now,
                "revision": current.revision + 1,
                "next_run_at": max(current.next_run_at, now) if enabled else current.next_run_at,
            })
            self._schedules[schedule_id] = updated
            self._append_event(MonitoringEvent(
                event_id=f"{schedule_id}:revision:{updated.revision}:enabled:{str(enabled).lower()}",
                event_type="schedule_enabled" if enabled else "schedule_disabled",
                schedule_id=schedule_id, occurred_at=now,
                payload={"revision": updated.revision},
            ))
            return updated

    def revise(
        self, schedule_id: str, update: MonitoringScheduleUpdate, now: datetime
    ) -> MonitoringSchedule:
        with self._lock:
            current = self.get(schedule_id)
            if current.revision != update.expected_revision:
                raise MonitoringRevisionConflict(
                    f"schedule revision is {current.revision}; expected {update.expected_revision}"
                )
            changes = update.model_dump(exclude={"expected_revision"}, exclude_unset=True)
            revised = current.model_copy(update={
                **changes, "updated_at": now, "revision": current.revision + 1,
            })
            self._schedules[schedule_id] = revised
            self._append_event(MonitoringEvent(
                event_id=f"{schedule_id}:revision:{revised.revision}:revised",
                event_type="schedule_revised", schedule_id=schedule_id,
                occurred_at=now,
                payload={"revision": revised.revision, "changed_fields": sorted(changes)},
            ))
            return revised

    def claim_due(
        self,
        schedule_id: str,
        now: datetime,
        worker_id: str = "monitoring:direct",
        lease_expires_at: datetime | None = None,
    ) -> MonitoringRun | None:
        with self._lock:
            schedule = self.get(schedule_id)
            if not schedule.enabled or schedule.next_run_at > now:
                return None
            if (
                schedule.overlap_policy == "skip_while_running"
                and any(
                    run.schedule_id == schedule_id and run.status == "running"
                    for run in self._runs.values()
                )
            ):
                return None
            scheduled_at = schedule.next_run_at
            missed = int((now - scheduled_at).total_seconds() // schedule.interval_seconds)
            run_id = _run_id(schedule_id, scheduled_at)
            if run_id in self._runs:
                return None
            next_run_at = scheduled_at + timedelta(seconds=(missed + 1) * schedule.interval_seconds)
            self._schedules[schedule_id] = schedule.model_copy(update={
                "next_run_at": next_run_at,
            })
            run = MonitoringRun(
                run_id=run_id,
                schedule_id=schedule_id,
                schedule_revision=schedule.revision,
                mission_id=schedule.mission_id,
                scheduled_at=scheduled_at,
                started_at=now,
                status="running",
                missed_intervals=missed,
                worker_id=worker_id,
                lease_expires_at=lease_expires_at or now + timedelta(seconds=120),
            )
            self._runs[run_id] = run
            self._append_event(MonitoringEvent(
                event_id=f"{run_id}:claimed", event_type="run_claimed",
                schedule_id=schedule_id, run_id=run_id, occurred_at=now,
                payload={"schedule_revision": schedule.revision, "worker_id": worker_id},
            ))
            return run

    def heartbeat(
        self, run_id: str, worker_id: str, lease_expires_at: datetime
    ) -> MonitoringRun:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None or current.status != "running" or current.worker_id != worker_id:
                raise ValueError("monitoring run lease is absent or owned by another worker")
            updated = current.model_copy(update={"lease_expires_at": lease_expires_at})
            self._runs[run_id] = updated
            return updated

    def recover_expired(self, now: datetime) -> tuple[MonitoringRun, ...]:
        with self._lock:
            recovered = []
            for run_id in sorted(self._runs):
                current = self._runs[run_id]
                if (
                    current.status != "running" or current.lease_expires_at is None
                    or current.lease_expires_at > now
                ):
                    continue
                failed = current.model_copy(update={
                    "status": "failed", "finished_at": now,
                    "failure_type": "worker_lease_expired",
                })
                self._runs[run_id] = failed
                self._append_event(MonitoringEvent(
                    event_id=f"{run_id}:lease-expired",
                    event_type="run_lease_expired", schedule_id=current.schedule_id,
                    run_id=run_id, occurred_at=now,
                    payload={"worker_id": current.worker_id},
                ))
                recovered.append(failed)
            return tuple(recovered)

    def finish(self, run: MonitoringRun) -> None:
        with self._lock:
            current = self._runs.get(run.run_id)
            if current is None or current.status != "running":
                raise ValueError("monitoring run is absent or no longer running")
            self._runs[run.run_id] = run
            event_type = {
                "completed": "run_completed", "partial": "run_partial",
                "failed": "run_failed", "skipped": "run_skipped",
            }[run.status]
            self._append_event(MonitoringEvent(
                event_id=f"{run.run_id}:finished", event_type=event_type,
                schedule_id=run.schedule_id, run_id=run.run_id,
                occurred_at=run.finished_at or utc_now(),
                payload={
                    "status": run.status, "failure_type": run.failure_type,
                    "investigation_id": run.investigation_id,
                },
            ))

    def runs(self, schedule_id: str) -> tuple[MonitoringRun, ...]:
        with self._lock:
            return tuple(sorted(
                (run for run in self._runs.values() if run.schedule_id == schedule_id),
                key=lambda run: (run.scheduled_at, run.run_id),
            ))

    def all_runs(self) -> tuple[MonitoringRun, ...]:
        with self._lock:
            return tuple(sorted(
                self._runs.values(), key=lambda run: (run.scheduled_at, run.run_id)
            ))

    def events(
        self, schedule_id: str | None = None, limit: int = 100,
        run_id: str | None = None,
    ) -> tuple[MonitoringEvent, ...]:
        if limit < 1:
            raise ValueError("monitoring event limit must be positive")
        with self._lock:
            filtered = [
                event for event in self._events
                if schedule_id is None or event.schedule_id == schedule_id
                if run_id is None or event.run_id == run_id
            ]
            return tuple(filtered[-limit:])

    def event_page(
        self, schedule_id: str | None = None, limit: int = 100,
        run_id: str | None = None, cursor: str | None = None,
    ) -> MonitoringEventPage:
        if limit < 1:
            raise ValueError("monitoring event limit must be positive")
        before = _decode_event_cursor(cursor) if cursor else None
        with self._lock:
            filtered = sorted((
                event for event in self._events
                if (schedule_id is None or event.schedule_id == schedule_id)
                and (run_id is None or event.run_id == run_id)
                and (before is None or (event.occurred_at, event.event_id) < before)
            ), key=lambda event: (event.occurred_at, event.event_id), reverse=True)
            selected = filtered[:limit + 1]
        has_more = len(selected) > limit
        page = tuple(reversed(selected[:limit]))
        return MonitoringEventPage(
            events=page,
            next_cursor=_encode_event_cursor(page[0]) if has_more and page else None,
            has_more=has_more,
        )

    def get_event(self, event_id: str) -> MonitoringEvent | None:
        with self._lock:
            return next((event for event in self._events if event.event_id == event_id), None)

    def event_counts(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {}
            for event in self._events:
                counts[event.event_type] = counts.get(event.event_type, 0) + 1
            return counts

    def notifications(
        self,
        schedule_id: str | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> tuple[MonitoringNotification, ...]:
        if limit < 1:
            raise ValueError("monitoring notification limit must be positive")
        with self._lock:
            items = [
                item for item in self._notifications.values()
                if (schedule_id is None or item.schedule_id == schedule_id)
                and (not unread_only or item.status == "unread")
            ]
            return tuple(sorted(
                items, key=lambda item: (item.created_at, item.notification_id)
            )[-limit:])

    def get_notification(self, notification_id: str) -> MonitoringNotification:
        with self._lock:
            try:
                return self._notifications[notification_id]
            except KeyError as exc:
                raise KeyError(
                    f"monitoring notification {notification_id!r} was not found"
                ) from exc

    def acknowledge_notification(
        self, notification_id: str, now: datetime
    ) -> MonitoringNotification:
        with self._lock:
            current = self._notifications.get(notification_id)
            if current is None:
                raise KeyError(f"monitoring notification {notification_id!r} was not found")
            if current.status == "acknowledged":
                return current
            updated = current.model_copy(update={
                "status": "acknowledged", "acknowledged_at": now,
            })
            self._notifications[notification_id] = updated
            self._append_event(MonitoringEvent(
                event_id=f"notification-ack:{notification_id}",
                event_type="notification_acknowledged", schedule_id=current.schedule_id,
                run_id=current.run_id, occurred_at=now,
                payload={"notification_id": notification_id},
            ))
            return updated

    def _append_event(self, event: MonitoringEvent) -> None:
        if event.event_id not in self._event_ids:
            self._events.append(event)
            self._event_ids.add(event.event_id)
        notification = _notification_for_event(event)
        if notification is not None:
            self._notifications.setdefault(notification.notification_id, notification)

    def record_event(self, event: MonitoringEvent) -> bool:
        """Append an idempotent lifecycle event; return whether it was new."""
        with self._lock:
            if event.event_id in self._event_ids:
                return False
            self._append_event(event)
            return True


class SQLiteMonitoringRepository(InMemoryMonitoringRepository):
    """SQLite-backed schedule and run journal sharing SatQuery's storage file."""

    SCHEMA_VERSION = 4

    def __init__(self, path: str | Path, *, busy_timeout_seconds: float = 5.0) -> None:
        if busy_timeout_seconds <= 0:
            raise ValueError("monitoring repository busy timeout must be positive")
        self.path = Path(path).expanduser().resolve()
        self.busy_timeout_seconds = busy_timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_monitoring_schema (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_monitoring_schedules (schedule_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, next_run_at TEXT NOT NULL, enabled INTEGER NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_due ON satquery_monitoring_schedules(enabled, next_run_at, schedule_id)")
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_monitoring_runs (run_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, scheduled_at TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(schedule_id, scheduled_at))")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_runs_schedule ON satquery_monitoring_runs(schedule_id, scheduled_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_runs_status ON satquery_monitoring_runs(status, schedule_id, scheduled_at)")
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_monitoring_events (event_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, run_id TEXT, occurred_at TEXT NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_events_schedule ON satquery_monitoring_events(schedule_id, occurred_at, event_id)")
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_monitoring_notifications (notification_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, run_id TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_notifications_status ON satquery_monitoring_notifications(status, created_at, notification_id)")
            row = connection.execute("SELECT version FROM satquery_monitoring_schema WHERE singleton=1").fetchone()
            if row is None:
                connection.execute("INSERT INTO satquery_monitoring_schema(singleton, version) VALUES (1, ?)", (self.SCHEMA_VERSION,))
            elif row[0] in {1, 2, 3}:
                # Version 2 adds append-only lifecycle events. Existing run
                # payloads remain readable because lease fields are optional.
                # Legacy in-progress runs have no lease owner, so fail them
                # closed instead of pretending they can be safely resumed.
                if row[0] == 1:
                    rows = connection.execute(
                        "SELECT payload FROM satquery_monitoring_runs WHERE status='running'"
                    ).fetchall()
                    recovered_at = utc_now()
                    for legacy_row in rows:
                        legacy = MonitoringRun.model_validate_json(legacy_row["payload"])
                        failed = legacy.model_copy(update={
                            "status": "failed", "finished_at": recovered_at,
                            "failure_type": "legacy_run_recovered_without_lease",
                        })
                        connection.execute(
                            "UPDATE satquery_monitoring_runs SET status='failed', payload=? WHERE run_id=?",
                            (_json(failed), failed.run_id),
                        )
                        self._insert_event(connection, MonitoringEvent(
                            event_id=f"{failed.run_id}:legacy-recovery",
                            event_type="run_lease_expired", schedule_id=failed.schedule_id,
                            run_id=failed.run_id, occurred_at=recovered_at,
                            payload={"failure_type": failed.failure_type},
                        ))
                event_columns = {
                    item[1] for item in connection.execute(
                        "PRAGMA table_info(satquery_monitoring_events)"
                    ).fetchall()
                }
                if "run_id" not in event_columns:
                    connection.execute(
                        "ALTER TABLE satquery_monitoring_events ADD COLUMN run_id TEXT"
                    )
                connection.execute(
                    "UPDATE satquery_monitoring_schema SET version=? WHERE singleton=1",
                    (self.SCHEMA_VERSION,),
                )
            elif row[0] != self.SCHEMA_VERSION:
                raise ValueError("unsupported monitoring repository schema version")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_monitoring_events_run ON satquery_monitoring_events(run_id, occurred_at, event_id)"
            )
            historical_events = connection.execute(
                "SELECT payload FROM satquery_monitoring_events WHERE event_type IN ('run_partial', 'run_failed', 'run_lease_expired')"
            ).fetchall()
            for historical_event in historical_events:
                event = MonitoringEvent.model_validate_json(historical_event["payload"])
                notification = _notification_for_event(event)
                if notification is not None:
                    self._insert_notification(connection, notification)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(str(self.path), timeout=self.busy_timeout_seconds, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}")
        try:
            yield connection
        finally:
            connection.close()

    def create(self, schedule: MonitoringSchedule) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("INSERT INTO satquery_monitoring_schedules VALUES (?, ?, ?, ?, ?, ?)", (schedule.schedule_id, schedule.mission_id, _time(schedule.next_run_at), int(schedule.enabled), schedule.revision, _json(schedule)))
                event = MonitoringEvent(
                    event_id=f"{schedule.schedule_id}:revision:{schedule.revision}:created",
                    event_type="schedule_created", schedule_id=schedule.schedule_id,
                    occurred_at=schedule.created_at,
                    payload={"revision": schedule.revision, "mission_id": schedule.mission_id},
                )
                self._insert_event(connection, event)
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ValueError("monitoring schedule identifier already exists") from exc

    def get(self, schedule_id: str) -> MonitoringSchedule:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM satquery_monitoring_schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
        if row is None:
            raise KeyError(f"monitoring schedule {schedule_id!r} was not found")
        return MonitoringSchedule.model_validate_json(row["payload"])

    def list(self, mission_id: str | None = None) -> tuple[MonitoringSchedule, ...]:
        with self._connection() as connection:
            if mission_id is None:
                rows = connection.execute("SELECT payload FROM satquery_monitoring_schedules ORDER BY schedule_id").fetchall()
            else:
                rows = connection.execute("SELECT payload FROM satquery_monitoring_schedules WHERE mission_id=? ORDER BY schedule_id", (mission_id,)).fetchall()
        return tuple(MonitoringSchedule.model_validate_json(row["payload"]) for row in rows)

    def set_enabled(self, schedule_id: str, enabled: bool, now: datetime) -> MonitoringSchedule:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM satquery_monitoring_schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(f"monitoring schedule {schedule_id!r} was not found")
            current = MonitoringSchedule.model_validate_json(row["payload"])
            if current.enabled == enabled:
                connection.rollback()
                return current
            updated = current.model_copy(update={
                "enabled": enabled, "updated_at": now, "revision": current.revision + 1,
                "next_run_at": max(current.next_run_at, now) if enabled else current.next_run_at,
            })
            connection.execute("UPDATE satquery_monitoring_schedules SET next_run_at=?, enabled=?, revision=?, payload=? WHERE schedule_id=?", (_time(updated.next_run_at), int(enabled), updated.revision, _json(updated), schedule_id))
            event = MonitoringEvent(
                event_id=f"{schedule_id}:revision:{updated.revision}:enabled:{str(enabled).lower()}",
                event_type="schedule_enabled" if enabled else "schedule_disabled",
                schedule_id=schedule_id, occurred_at=now,
                payload={"revision": updated.revision},
            )
            self._insert_event(connection, event)
            connection.commit()
            return updated

    def revise(
        self, schedule_id: str, update: MonitoringScheduleUpdate, now: datetime
    ) -> MonitoringSchedule:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM satquery_monitoring_schedules WHERE schedule_id=?",
                (schedule_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(f"monitoring schedule {schedule_id!r} was not found")
            current = MonitoringSchedule.model_validate_json(row["payload"])
            if current.revision != update.expected_revision:
                connection.rollback()
                raise MonitoringRevisionConflict(
                    f"schedule revision is {current.revision}; expected {update.expected_revision}"
                )
            changes = update.model_dump(exclude={"expected_revision"}, exclude_unset=True)
            revised = current.model_copy(update={
                **changes, "updated_at": now, "revision": current.revision + 1,
            })
            connection.execute(
                "UPDATE satquery_monitoring_schedules SET next_run_at=?, enabled=?, revision=?, payload=? WHERE schedule_id=?",
                (_time(revised.next_run_at), int(revised.enabled), revised.revision,
                 _json(revised), schedule_id),
            )
            self._insert_event(connection, MonitoringEvent(
                event_id=f"{schedule_id}:revision:{revised.revision}:revised",
                event_type="schedule_revised", schedule_id=schedule_id,
                occurred_at=now,
                payload={"revision": revised.revision, "changed_fields": sorted(changes)},
            ))
            connection.commit()
            return revised

    def claim_due(
        self,
        schedule_id: str,
        now: datetime,
        worker_id: str = "monitoring:direct",
        lease_expires_at: datetime | None = None,
    ) -> MonitoringRun | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM satquery_monitoring_schedules WHERE schedule_id=? AND enabled=1", (schedule_id,)).fetchone()
            if row is None:
                connection.rollback()
                return None
            schedule = MonitoringSchedule.model_validate_json(row["payload"])
            if schedule.next_run_at > now:
                connection.rollback()
                return None
            if schedule.overlap_policy == "skip_while_running" and connection.execute(
                "SELECT 1 FROM satquery_monitoring_runs WHERE schedule_id=? AND status='running' LIMIT 1",
                (schedule_id,),
            ).fetchone():
                connection.rollback()
                return None
            scheduled_at = schedule.next_run_at
            missed = int((now - scheduled_at).total_seconds() // schedule.interval_seconds)
            run_id = _run_id(schedule_id, scheduled_at)
            if connection.execute("SELECT 1 FROM satquery_monitoring_runs WHERE run_id=?", (run_id,)).fetchone():
                connection.rollback()
                return None
            run = MonitoringRun(
                run_id=run_id, schedule_id=schedule_id,
                schedule_revision=schedule.revision, mission_id=schedule.mission_id,
                scheduled_at=scheduled_at, started_at=now, status="running", missed_intervals=missed,
                worker_id=worker_id,
                lease_expires_at=lease_expires_at or now + timedelta(seconds=120),
            )
            next_run_at = scheduled_at + timedelta(seconds=(missed + 1) * schedule.interval_seconds)
            updated = schedule.model_copy(update={"next_run_at": next_run_at})
            connection.execute("UPDATE satquery_monitoring_schedules SET next_run_at=?, payload=? WHERE schedule_id=?", (_time(next_run_at), _json(updated), schedule_id))
            connection.execute("INSERT INTO satquery_monitoring_runs VALUES (?, ?, ?, ?, ?)", (run.run_id, run.schedule_id, _time(run.scheduled_at), run.status, _json(run)))
            self._insert_event(connection, MonitoringEvent(
                event_id=f"{run.run_id}:claimed", event_type="run_claimed",
                schedule_id=schedule_id, run_id=run.run_id, occurred_at=now,
                payload={"schedule_revision": schedule.revision, "worker_id": worker_id},
            ))
            connection.commit()
            return run

    def heartbeat(
        self, run_id: str, worker_id: str, lease_expires_at: datetime
    ) -> MonitoringRun:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM satquery_monitoring_runs WHERE run_id=? AND status='running'",
                (run_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ValueError("monitoring run lease is absent or no longer running")
            current = MonitoringRun.model_validate_json(row["payload"])
            if current.worker_id != worker_id:
                connection.rollback()
                raise ValueError("monitoring run lease is owned by another worker")
            updated = current.model_copy(update={"lease_expires_at": lease_expires_at})
            connection.execute(
                "UPDATE satquery_monitoring_runs SET payload=? WHERE run_id=? AND status='running'",
                (_json(updated), run_id),
            )
            connection.commit()
            return updated

    def recover_expired(self, now: datetime) -> tuple[MonitoringRun, ...]:
        recovered = []
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT payload FROM satquery_monitoring_runs WHERE status='running' ORDER BY scheduled_at, run_id"
            ).fetchall()
            for row in rows:
                current = MonitoringRun.model_validate_json(row["payload"])
                if current.lease_expires_at is None or current.lease_expires_at > now:
                    continue
                failed = current.model_copy(update={
                    "status": "failed", "finished_at": now,
                    "failure_type": "worker_lease_expired",
                })
                connection.execute(
                    "UPDATE satquery_monitoring_runs SET status=?, payload=? WHERE run_id=? AND status='running'",
                    (failed.status, _json(failed), failed.run_id),
                )
                self._insert_event(connection, MonitoringEvent(
                    event_id=f"{failed.run_id}:lease-expired",
                    event_type="run_lease_expired", schedule_id=failed.schedule_id,
                    run_id=failed.run_id, occurred_at=now,
                    payload={"worker_id": current.worker_id},
                ))
                recovered.append(failed)
            connection.commit()
        return tuple(recovered)

    def finish(self, run: MonitoringRun) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM satquery_monitoring_runs WHERE run_id=? AND status='running'",
                (run.run_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ValueError("monitoring run is absent or no longer running")
            current = MonitoringRun.model_validate_json(row["payload"])
            if current.worker_id != run.worker_id:
                connection.rollback()
                raise ValueError("monitoring run lease is owned by another worker")
            connection.execute(
                "UPDATE satquery_monitoring_runs SET status=?, payload=? WHERE run_id=? AND status='running'",
                (run.status, _json(run), run.run_id),
            )
            event_type = {
                "completed": "run_completed", "partial": "run_partial",
                "failed": "run_failed", "skipped": "run_skipped",
            }[run.status]
            self._insert_event(connection, MonitoringEvent(
                event_id=f"{run.run_id}:finished", event_type=event_type,
                schedule_id=run.schedule_id, run_id=run.run_id,
                occurred_at=run.finished_at or utc_now(),
                payload={"status": run.status, "failure_type": run.failure_type,
                         "investigation_id": run.investigation_id},
            ))
            connection.commit()

    def runs(self, schedule_id: str) -> tuple[MonitoringRun, ...]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM satquery_monitoring_runs WHERE schedule_id=? ORDER BY scheduled_at, run_id", (schedule_id,)).fetchall()
        return tuple(MonitoringRun.model_validate_json(row["payload"]) for row in rows)

    def all_runs(self) -> tuple[MonitoringRun, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM satquery_monitoring_runs ORDER BY scheduled_at, run_id"
            ).fetchall()
        return tuple(MonitoringRun.model_validate_json(row["payload"]) for row in rows)

    def events(
        self, schedule_id: str | None = None, limit: int = 100,
        run_id: str | None = None,
    ) -> tuple[MonitoringEvent, ...]:
        if limit < 1:
            raise ValueError("monitoring event limit must be positive")
        with self._connection() as connection:
            filters = []
            parameters: list[object] = []
            if schedule_id is not None:
                filters.append("schedule_id=?")
                parameters.append(schedule_id)
            if run_id is not None:
                filters.append("run_id=?")
                parameters.append(run_id)
            clause = " WHERE " + " AND ".join(filters) if filters else ""
            rows = connection.execute(
                "SELECT payload FROM satquery_monitoring_events" + clause
                + " ORDER BY occurred_at DESC, event_id DESC LIMIT ?",
                (*parameters, limit),
            ).fetchall()
        return tuple(
            MonitoringEvent.model_validate_json(row["payload"])
            for row in reversed(rows)
        )

    def event_page(
        self, schedule_id: str | None = None, limit: int = 100,
        run_id: str | None = None, cursor: str | None = None,
    ) -> MonitoringEventPage:
        if limit < 1:
            raise ValueError("monitoring event limit must be positive")
        before = _decode_event_cursor(cursor) if cursor else None
        filters: list[str] = []
        parameters: list[object] = []
        if schedule_id is not None:
            filters.append("schedule_id=?")
            parameters.append(schedule_id)
        if run_id is not None:
            filters.append("run_id=?")
            parameters.append(run_id)
        if before is not None:
            filters.append("(occurred_at < ? OR (occurred_at = ? AND event_id < ?))")
            encoded_time = _time(before[0])
            parameters.extend((encoded_time, encoded_time, before[1]))
        clause = " WHERE " + " AND ".join(filters) if filters else ""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM satquery_monitoring_events" + clause
                + " ORDER BY occurred_at DESC, event_id DESC LIMIT ?",
                (*parameters, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        page = tuple(
            MonitoringEvent.model_validate_json(row["payload"])
            for row in reversed(selected)
        )
        return MonitoringEventPage(
            events=page,
            next_cursor=_encode_event_cursor(page[0]) if has_more and page else None,
            has_more=has_more,
        )

    def get_event(self, event_id: str) -> MonitoringEvent | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM satquery_monitoring_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
        return MonitoringEvent.model_validate_json(row["payload"]) if row else None

    def event_counts(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT event_type, COUNT(*) AS event_count "
                "FROM satquery_monitoring_events GROUP BY event_type"
            ).fetchall()
        return {str(row["event_type"]): int(row["event_count"]) for row in rows}

    def notifications(
        self,
        schedule_id: str | None = None,
        unread_only: bool = False,
        limit: int = 100,
    ) -> tuple[MonitoringNotification, ...]:
        if limit < 1:
            raise ValueError("monitoring notification limit must be positive")
        where = []
        parameters: list[object] = []
        if schedule_id is not None:
            where.append("schedule_id=?")
            parameters.append(schedule_id)
        if unread_only:
            where.append("status='unread'")
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM satquery_monitoring_notifications" + clause
                + " ORDER BY created_at DESC, notification_id DESC LIMIT ?",
                (*parameters, limit),
            ).fetchall()
        return tuple(
            MonitoringNotification.model_validate_json(row["payload"])
            for row in reversed(rows)
        )

    def get_notification(self, notification_id: str) -> MonitoringNotification:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM satquery_monitoring_notifications WHERE notification_id=?",
                (notification_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"monitoring notification {notification_id!r} was not found")
        return MonitoringNotification.model_validate_json(row["payload"])

    def acknowledge_notification(
        self, notification_id: str, now: datetime
    ) -> MonitoringNotification:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM satquery_monitoring_notifications WHERE notification_id=?",
                (notification_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(f"monitoring notification {notification_id!r} was not found")
            current = MonitoringNotification.model_validate_json(row["payload"])
            if current.status == "acknowledged":
                connection.rollback()
                return current
            updated = current.model_copy(update={
                "status": "acknowledged", "acknowledged_at": now,
            })
            connection.execute(
                "UPDATE satquery_monitoring_notifications SET status=?, payload=? WHERE notification_id=?",
                (updated.status, _json(updated), notification_id),
            )
            self._insert_event(connection, MonitoringEvent(
                event_id=f"notification-ack:{notification_id}",
                event_type="notification_acknowledged", schedule_id=current.schedule_id,
                run_id=current.run_id, occurred_at=now,
                payload={"notification_id": notification_id},
            ))
            connection.commit()
            return updated

    def record_event(self, event: MonitoringEvent) -> bool:
        """Durably append an event once, including its notification projection."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "INSERT OR IGNORE INTO satquery_monitoring_events "
                "(event_id, schedule_id, run_id, occurred_at, event_type, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event.event_id, event.schedule_id, event.run_id,
                 _time(event.occurred_at), event.event_type, _json(event)),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                notification = _notification_for_event(event)
                if notification is not None:
                    self._insert_notification(connection, notification)
            connection.commit()
            return inserted

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, event: MonitoringEvent) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO satquery_monitoring_events (event_id, schedule_id, run_id, occurred_at, event_type, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (event.event_id, event.schedule_id, event.run_id, _time(event.occurred_at),
             event.event_type, _json(event)),
        )
        notification = _notification_for_event(event)
        if notification is not None:
            SQLiteMonitoringRepository._insert_notification(connection, notification)

    @staticmethod
    def _insert_notification(
        connection: sqlite3.Connection, notification: MonitoringNotification
    ) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO satquery_monitoring_notifications (notification_id, schedule_id, run_id, status, created_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
            (notification.notification_id, notification.schedule_id,
             notification.run_id, notification.status,
             _time(notification.created_at), _json(notification)),
        )


class MonitoringService:
    """Create schedules and run due entries through ordinary investigation DAGs."""

    def __init__(
        self,
        repository: MonitoringRepository,
        mission_service,
        investigation_service,
        *,
        max_concurrency: int = 1,
        lease_seconds: float = 120.0,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("monitoring concurrency must be positive")
        if lease_seconds <= 0:
            raise ValueError("monitoring lease duration must be positive")
        self.repository = repository
        self.mission_service = mission_service
        self.investigation_service = investigation_service
        self.max_concurrency = max_concurrency
        self.lease_seconds = lease_seconds
        self.worker_id = f"monitoring-worker:{uuid4().hex}"
        self._run_lock = asyncio.Lock()

    def create(self, schedule: MonitoringSchedule) -> MonitoringSchedule:
        mission = self.mission_service.get(schedule.mission_id)
        if mission.status != MissionStatus.ACTIVE:
            raise ValueError("monitoring schedules require an active mission")
        self.repository.create(schedule)
        return schedule

    def get(self, schedule_id: str) -> MonitoringSchedule:
        return self.repository.get(schedule_id)

    def list(self, mission_id: str | None = None) -> tuple[MonitoringSchedule, ...]:
        return self.repository.list(mission_id)

    def set_enabled(self, schedule_id: str, enabled: bool, now: datetime | None = None) -> MonitoringSchedule:
        return self.repository.set_enabled(schedule_id, enabled, now or utc_now())

    def revise(
        self,
        schedule_id: str,
        update: MonitoringScheduleUpdate,
        now: datetime | None = None,
    ) -> MonitoringSchedule:
        return self.repository.revise(schedule_id, update, now or utc_now())

    def runs(self, schedule_id: str) -> tuple[MonitoringRun, ...]:
        self.repository.get(schedule_id)
        return self.repository.runs(schedule_id)

    def runs_for_investigation(
        self, investigation_id: str
    ) -> tuple[MonitoringRun, ...]:
        return tuple(
            run for run in self.repository.all_runs()
            if run.investigation_id == investigation_id
        )

    def events(
        self, schedule_id: str | None = None, *, limit: int = 100,
        run_id: str | None = None,
    ) -> tuple[MonitoringEvent, ...]:
        if schedule_id is not None:
            self.repository.get(schedule_id)
        return self.repository.events(schedule_id, limit, run_id)

    def event_page(
        self, schedule_id: str | None = None, *, limit: int = 100,
        run_id: str | None = None, cursor: str | None = None,
    ) -> MonitoringEventPage:
        if schedule_id is not None:
            self.repository.get(schedule_id)
        return self.repository.event_page(schedule_id, limit, run_id, cursor)

    def all_events(
        self, schedule_id: str | None = None, *, run_id: str | None = None,
        page_size: int = 1000,
    ) -> tuple[MonitoringEvent, ...]:
        """Read full history in bounded repository pages, without a truncation cap."""
        if page_size < 1:
            raise ValueError("monitoring event page size must be positive")
        if schedule_id is not None:
            self.repository.get(schedule_id)
        return tuple(sorted(
            self.iter_events(schedule_id, run_id=run_id, page_size=page_size),
            key=lambda event: (event.occurred_at, event.event_id),
        ))

    def iter_events(
        self, schedule_id: str | None = None, *, run_id: str | None = None,
        page_size: int = 1000,
    ) -> Iterator[MonitoringEvent]:
        """Stream newest-to-oldest without materializing the event history."""
        if page_size < 1:
            raise ValueError("monitoring event page size must be positive")
        if schedule_id is not None:
            self.repository.get(schedule_id)
        cursor = None
        while True:
            page = self.repository.event_page(schedule_id, page_size, run_id, cursor)
            yield from reversed(page.events)
            if not page.has_more or page.next_cursor is None:
                break
            cursor = page.next_cursor

    def get_event(self, event_id: str) -> MonitoringEvent | None:
        return self.repository.get_event(event_id)

    def notifications(
        self,
        schedule_id: str | None = None,
        *,
        unread_only: bool = False,
        limit: int = 100,
    ) -> tuple[MonitoringNotification, ...]:
        if schedule_id is not None:
            self.repository.get(schedule_id)
        return self.repository.notifications(schedule_id, unread_only, limit)

    def acknowledge_notification(
        self, notification_id: str, now: datetime | None = None
    ) -> MonitoringNotification:
        return self.repository.acknowledge_notification(
            notification_id, now or utc_now()
        )

    def record_event(self, event: MonitoringEvent) -> bool:
        self.repository.get(event.schedule_id)
        return self.repository.record_event(event)

    def get_notification(self, notification_id: str) -> MonitoringNotification:
        return self.repository.get_notification(notification_id)

    def health(self, now: datetime | None = None) -> MonitoringHealth:
        instant = now or utc_now()
        schedules = self.repository.list()
        runs = self.repository.all_runs()
        event_counts = self.repository.event_counts()
        finished = [run for run in runs if run.finished_at is not None]
        return MonitoringHealth(
            observed_at=instant,
            schedule_count=len(schedules),
            enabled_schedule_count=sum(schedule.enabled for schedule in schedules),
            due_schedule_count=sum(
                schedule.enabled and schedule.next_run_at <= instant
                for schedule in schedules
            ),
            blocked_due_schedule_count=sum(
                schedule.enabled and schedule.next_run_at <= instant
                and schedule.overlap_policy == "skip_while_running"
                and any(
                    run.schedule_id == schedule.schedule_id and run.status == "running"
                    for run in runs
                )
                for schedule in schedules
            ),
            running_run_count=sum(run.status == "running" for run in runs),
            expired_lease_count=sum(
                run.status == "running" and run.lease_expires_at is not None
                and run.lease_expires_at <= instant for run in runs
            ),
            completed_run_count=sum(run.status == "completed" for run in runs),
            partial_run_count=sum(run.status == "partial" for run in runs),
            failed_run_count=sum(run.status == "failed" for run in runs),
            trigger_evaluation_count=event_counts.get("trigger_evaluated", 0),
            trigger_match_count=event_counts.get("trigger_matched", 0),
            trigger_cooldown_suppression_count=event_counts.get(
                "trigger_suppressed_cooldown", 0
            ),
            triggered_investigation_completed_count=event_counts.get(
                "trigger_investigation_completed", 0
            ),
            triggered_investigation_failed_count=event_counts.get(
                "trigger_investigation_failed", 0
            ),
            last_run_at=max(finished, key=lambda run: run.finished_at).finished_at
            if finished else None,
        )

    async def run_due(
        self,
        execute: Callable[[str], Awaitable[object]],
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> tuple[MonitoringRun, ...]:
        if limit < 1:
            raise ValueError("monitoring run limit must be positive")
        instant = now or utc_now()
        if instant.tzinfo is None:
            raise ValueError("monitoring scheduler clock must be timezone-aware")
        results: list[MonitoringRun] = []
        async with self._run_lock:
            results.extend(self.repository.recover_expired(instant))
            claimed: list[tuple[MonitoringSchedule, MonitoringRun]] = []
            schedules = sorted(
                self.repository.list(),
                key=lambda item: (-item.priority, item.next_run_at, item.schedule_id),
            )
            for schedule in schedules:
                if len(claimed) >= limit:
                    break
                run = self.repository.claim_due(
                    schedule.schedule_id,
                    instant,
                    self.worker_id,
                    instant + timedelta(seconds=self.lease_seconds),
                )
                if run is not None:
                    claimed.append((schedule, run))

            semaphore = asyncio.Semaphore(self.max_concurrency)

            async def dispatch(schedule: MonitoringSchedule, run: MonitoringRun):
                async with semaphore:
                    return await self._execute_claim(schedule, run, execute)

            tasks = [
                asyncio.create_task(dispatch(schedule, run))
                for schedule, run in claimed
            ]
            try:
                results.extend(await asyncio.gather(*tasks))
            except asyncio.CancelledError:
                # gather cancels started and semaphore-waiting dispatches. Each
                # started execution finalizes itself; finalize claims that never
                # entered execution so a restart cannot strand them as running.
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                for schedule, run in claimed:
                    stored = next(
                        item for item in self.repository.runs(schedule.schedule_id)
                        if item.run_id == run.run_id
                    )
                    if stored.status == "running":
                        self.repository.finish(stored.model_copy(update={
                            "status": "failed",
                            "finished_at": utc_now(),
                            "failure_type": "scheduler_cancelled",
                        }))
                raise
        return tuple(results)

    async def _execute_claim(
        self,
        schedule: MonitoringSchedule,
        run: MonitoringRun,
        execute: Callable[[str], Awaitable[object]],
    ) -> MonitoringRun:
        investigation_id = None
        execution_id = None
        cancelled = False
        heartbeat = asyncio.create_task(self._renew_lease(run))
        try:
            mission = self.mission_service.get(schedule.mission_id)
            if mission.status != MissionStatus.ACTIVE:
                completed = run.model_copy(update={
                    "status": "skipped", "finished_at": utc_now(),
                    "failure_type": "mission_not_active",
                })
            else:
                investigation = self.mission_service.create_investigation(
                    schedule.mission_id,
                    (Task(
                        handler="earth.observe",
                        description=f"Scheduled Earth observation: {schedule.name}",
                        parameters={
                            "earth_query": schedule.earth_query.model_dump(mode="json"),
                            "monitoring_schedule_id": schedule.schedule_id,
                            "monitoring_run_id": run.run_id,
                            "schedule_revision": run.schedule_revision,
                            "scheduled_at": run.scheduled_at.isoformat(),
                            "missed_intervals": run.missed_intervals,
                        },
                    ),),
                )
                investigation_id = investigation.investigation_id
                execution = await execute(investigation_id)
                execution_id = execution.plan_id
                status = {
                    InvestigationStatus.COMPLETED: "completed",
                    InvestigationStatus.PARTIAL: "partial",
                }.get(self.investigation_service.get(investigation_id).status, "failed")
                completed = run.model_copy(update={
                    "status": status, "finished_at": utc_now(),
                    "investigation_id": investigation_id, "execution_id": execution_id,
                })
        except asyncio.CancelledError:
            completed = run.model_copy(update={
                "status": "failed", "finished_at": utc_now(),
                "investigation_id": investigation_id, "execution_id": execution_id,
                "failure_type": "scheduler_cancelled",
            })
            cancelled = True
        except Exception as exc:
            logger.exception(
                "monitoring investigation failed",
                extra={
                    "schedule_id": schedule.schedule_id,
                    "run_id": run.run_id,
                    "investigation_id": investigation_id,
                },
            )
            completed = run.model_copy(update={
                "status": "failed", "finished_at": utc_now(),
                "investigation_id": investigation_id, "execution_id": execution_id,
                "failure_type": type(exc).__name__,
            })
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        self.repository.finish(completed)
        if cancelled:
            raise asyncio.CancelledError
        return completed

    async def _renew_lease(self, run: MonitoringRun) -> None:
        delay = max(0.05, self.lease_seconds / 3)
        while True:
            await asyncio.sleep(delay)
            self.repository.heartbeat(
                run.run_id,
                self.worker_id,
                utc_now() + timedelta(seconds=self.lease_seconds),
            )


def monitoring_schedule_identity(schedule: MonitoringSchedule) -> str:
    """Stable identity for Earth Memory's immutable schedule revisions."""
    return f"monitoring-schedule:{schedule.schedule_id}:revision:{schedule.revision}"


def monitoring_schedule_definition(
    schedule: MonitoringSchedule,
) -> MonitoringScheduleDefinition:
    """Project mutable scheduler state onto the immutable schedule contract."""
    return MonitoringScheduleDefinition(
        schedule_id=schedule.schedule_id,
        mission_id=schedule.mission_id,
        name=schedule.name,
        earth_query=schedule.earth_query,
        interval_seconds=schedule.interval_seconds,
        priority=schedule.priority,
        overlap_policy=schedule.overlap_policy,
        trigger_policies=schedule.trigger_policies,
        enabled=schedule.enabled,
        revision=schedule.revision,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def monitoring_run_identity(run: MonitoringRun) -> str:
    """Stable identity for one scheduled occurrence."""
    return run.run_id


def monitoring_schedule_revision_identity(schedule_id: str, revision: int) -> str:
    """Stable identity for the schedule definition that produced a run."""
    return f"monitoring-schedule:{schedule_id}:revision:{revision}"


def _notification_for_event(event: MonitoringEvent) -> MonitoringNotification | None:
    if event.event_type not in {
        "run_partial", "run_failed", "run_lease_expired",
        "trigger_matched", "trigger_investigation_failed",
    }:
        return None
    if event.run_id is None:
        return None
    failure_type = event.payload.get("failure_type")
    if event.event_type == "trigger_matched":
        severity = "warning"
        title = "Monitoring policy matched"
        detail = str(event.payload.get("detail") or "An operator-defined monitoring rule matched.")
    elif event.event_type == "run_partial":
        severity = "warning"
        title = "Monitoring investigation completed with partial coverage"
        detail = "Inspect the linked investigation to review which observations were available."
    else:
        severity = "error"
        title = "Monitoring investigation requires attention"
        detail = str(failure_type or "The scheduled run did not complete.")
    return MonitoringNotification(
        notification_id=f"monitor-notification:{event.event_id}",
        event_id=event.event_id,
        schedule_id=event.schedule_id,
        run_id=event.run_id,
        severity=severity,
        title=title,
        detail=detail,
        created_at=event.occurred_at,
    )


def _run_id(schedule_id: str, scheduled_at: datetime) -> str:
    return f"monitor-run:{schedule_id}:{_time(scheduled_at)}"


def _time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("monitoring timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _json(value: Contract) -> str:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
