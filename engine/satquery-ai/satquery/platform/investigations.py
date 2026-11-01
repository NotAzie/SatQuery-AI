"""Investigation lifecycle and replaceable persistence contracts."""

from __future__ import annotations

import threading
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, Protocol, Tuple

from ..errors import ValidationError
from .contracts import (
    Evidence,
    ExecutionPlan,
    Investigation,
    InvestigationStatus,
    Mission,
    MissionStatus,
    Task,
    utc_now,
)


class InvestigationRepository(Protocol):
    def create(self, investigation: Investigation) -> None: ...

    def get(self, investigation_id: str) -> Investigation: ...

    def update(self, investigation: Investigation) -> None: ...

    def list_for_mission(self, mission_id: str) -> Tuple[Investigation, ...]: ...


class MissionRepository(Protocol):
    """Persistence boundary for mission lifecycle state."""

    def create(self, mission: Mission) -> None: ...

    def get(self, mission_id: str) -> Mission: ...

    def update(self, mission: Mission) -> None: ...

    def list(self) -> Tuple[Mission, ...]: ...


class InMemoryMissionRepository:
    """Thread-safe local mission store; callers can replace it with persistence."""

    def __init__(self) -> None:
        self._items: Dict[str, Mission] = {}
        self._lock = threading.RLock()

    def create(self, mission: Mission) -> None:
        with self._lock:
            if mission.mission_id in self._items:
                raise ValidationError(
                    "Mission identifier already exists.",
                    context={"mission_id": mission.mission_id},
                )
            self._items[mission.mission_id] = mission

    def get(self, mission_id: str) -> Mission:
        with self._lock:
            try:
                return self._items[mission_id]
            except KeyError as exc:
                raise ValidationError(
                    "Mission was not found.", context={"mission_id": mission_id}
                ) from exc

    def update(self, mission: Mission) -> None:
        with self._lock:
            if mission.mission_id not in self._items:
                raise ValidationError(
                    "Mission was not found.",
                    context={"mission_id": mission.mission_id},
                )
            self._items[mission.mission_id] = mission

    def list(self) -> Tuple[Mission, ...]:
        with self._lock:
            return tuple(
                self._items[key] for key in sorted(self._items)
            )


class InMemoryInvestigationRepository:
    """Local repository adapter; production persistence can implement the protocol."""

    def __init__(self) -> None:
        self._items: Dict[str, Investigation] = {}
        self._lock = threading.RLock()

    def create(self, investigation: Investigation) -> None:
        with self._lock:
            if investigation.investigation_id in self._items:
                raise ValidationError(
                    "Investigation identifier already exists.",
                    context={"investigation_id": investigation.investigation_id},
                )
            self._items[investigation.investigation_id] = investigation

    def get(self, investigation_id: str) -> Investigation:
        with self._lock:
            try:
                return self._items[investigation_id]
            except KeyError as exc:
                raise ValidationError(
                    "Investigation was not found.",
                    context={"investigation_id": investigation_id},
                ) from exc

    def update(self, investigation: Investigation) -> None:
        with self._lock:
            if investigation.investigation_id not in self._items:
                raise ValidationError(
                    "Investigation was not found.",
                    context={"investigation_id": investigation.investigation_id},
                )
            self._items[investigation.investigation_id] = investigation

    def list_for_mission(self, mission_id: str) -> Tuple[Investigation, ...]:
        with self._lock:
            return tuple(
                item
                for item in self._items.values()
                if item.mission_id == mission_id
            )


class SQLiteLifecycleRepository:
    """Durable local mission and investigation snapshots.

    This adapter implements both repository protocols in one SQLite file so a
    mission and its investigation history share one lifecycle boundary. The
    contracts stay independent from SQLite and remain replaceable.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, busy_timeout_seconds: float = 5.0) -> None:
        if busy_timeout_seconds <= 0:
            raise ValueError("lifecycle store busy timeout must be positive")
        self.path = Path(path).expanduser().resolve()
        self.busy_timeout_seconds = busy_timeout_seconds
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS satquery_lifecycle_schema ("
                "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), version INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS satquery_missions ("
                "mission_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, mission_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS satquery_investigations ("
                "investigation_id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, created_at TEXT NOT NULL, "
                "status TEXT NOT NULL, investigation_json TEXT NOT NULL, "
                "FOREIGN KEY (mission_id) REFERENCES satquery_missions(mission_id))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_satquery_investigations_mission "
                "ON satquery_investigations(mission_id, created_at, investigation_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_satquery_investigations_status "
                "ON satquery_investigations(status, created_at)"
            )
            row = connection.execute(
                "SELECT version FROM satquery_lifecycle_schema WHERE singleton = 1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO satquery_lifecycle_schema(singleton, version) VALUES (1, ?)",
                    (self.SCHEMA_VERSION,),
                )
            elif row["version"] != self.SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported lifecycle schema version {row['version']}; "
                    f"this runtime supports {self.SCHEMA_VERSION}"
                )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(
            str(self.path), timeout=self.busy_timeout_seconds, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}"
        )
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _created_at(item) -> str:
        return item.created_at.isoformat()

    def create(self, item) -> None:
        from ..errors import ValidationError

        if isinstance(item, Mission):
            table, identifier, timestamp, encoded = (
                "satquery_missions", item.mission_id, self._created_at(item), item.model_dump_json()
            )
            columns = "mission_id, created_at, mission_json"
            values = (identifier, timestamp, encoded)
        elif isinstance(item, Investigation):
            table, identifier, timestamp, encoded = (
                "satquery_investigations", item.investigation_id, self._created_at(item), item.model_dump_json()
            )
            columns = "investigation_id, mission_id, created_at, status, investigation_json"
            values = (identifier, item.mission_id, timestamp, item.status.value, encoded)
        else:
            raise TypeError("SQLiteLifecycleRepository accepts Mission or Investigation")
        placeholders = ", ".join("?" for _ in values)
        with self._lock, self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                context_key = "mission_id" if isinstance(item, Mission) else "investigation_id"
                raise ValidationError(
                    f"{type(item).__name__} identifier already exists or its mission is missing.",
                    context={context_key: identifier},
                ) from exc
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def get(self, identifier: str):
        from ..errors import ValidationError

        with self._connection() as connection:
            mission = connection.execute(
                "SELECT mission_json FROM satquery_missions WHERE mission_id = ?", (identifier,)
            ).fetchone()
            if mission is not None:
                return Mission.model_validate_json(mission["mission_json"])
            investigation = connection.execute(
                "SELECT investigation_json FROM satquery_investigations WHERE investigation_id = ?",
                (identifier,),
            ).fetchone()
        if investigation is not None:
            return Investigation.model_validate_json(investigation["investigation_json"])
        raise ValidationError(
            "Mission or investigation was not found.", context={"identifier": identifier}
        )

    def get_mission(self, mission_id: str) -> Mission:
        from ..errors import ValidationError

        with self._connection() as connection:
            row = connection.execute(
                "SELECT mission_json FROM satquery_missions WHERE mission_id = ?",
                (mission_id,),
            ).fetchone()
        if row is None:
            raise ValidationError("Mission was not found.", context={"mission_id": mission_id})
        return Mission.model_validate_json(row["mission_json"])

    def get_investigation(self, investigation_id: str) -> Investigation:
        from ..errors import ValidationError

        with self._connection() as connection:
            row = connection.execute(
                "SELECT investigation_json FROM satquery_investigations WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
        if row is None:
            raise ValidationError(
                "Investigation was not found.",
                context={"investigation_id": investigation_id},
            )
        return Investigation.model_validate_json(row["investigation_json"])

    def update(self, item) -> None:
        from ..errors import ValidationError

        if isinstance(item, Mission):
            sql = "UPDATE satquery_missions SET mission_json = ? WHERE mission_id = ?"
            values = (item.model_dump_json(), item.mission_id)
        elif isinstance(item, Investigation):
            sql = (
                "UPDATE satquery_investigations SET status = ?, investigation_json = ? "
                "WHERE investigation_id = ? AND mission_id = ?"
            )
            values = (item.status.value, item.model_dump_json(), item.investigation_id, item.mission_id)
        else:
            raise TypeError("SQLiteLifecycleRepository accepts Mission or Investigation")
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(sql, values)
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise ValidationError(
                    f"{type(item).__name__} was not found or its mission identity changed."
                )
            connection.execute("COMMIT")

    def list(self) -> Tuple[Mission, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT mission_json FROM satquery_missions ORDER BY created_at, mission_id"
            ).fetchall()
        return tuple(Mission.model_validate_json(row["mission_json"]) for row in rows)

    def list_for_mission(self, mission_id: str) -> Tuple[Investigation, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT investigation_json FROM satquery_investigations "
                "WHERE mission_id = ? ORDER BY created_at, investigation_id",
                (mission_id,),
            ).fetchall()
        return tuple(Investigation.model_validate_json(row["investigation_json"]) for row in rows)


class SQLiteMissionRepository:
    """Typed MissionRepository view over a shared lifecycle database."""

    def __init__(self, store: SQLiteLifecycleRepository) -> None:
        self.store = store

    def create(self, mission: Mission) -> None:
        self.store.create(mission)

    def get(self, mission_id: str) -> Mission:
        return self.store.get_mission(mission_id)

    def update(self, mission: Mission) -> None:
        self.store.update(mission)

    def list(self) -> Tuple[Mission, ...]:
        return self.store.list()


class SQLiteInvestigationRepository:
    """Typed InvestigationRepository view over a shared lifecycle database."""

    def __init__(self, store: SQLiteLifecycleRepository) -> None:
        self.store = store

    def create(self, investigation: Investigation) -> None:
        self.store.create(investigation)

    def get(self, investigation_id: str) -> Investigation:
        return self.store.get_investigation(investigation_id)

    def update(self, investigation: Investigation) -> None:
        self.store.update(investigation)

    def list_for_mission(self, mission_id: str) -> Tuple[Investigation, ...]:
        return self.store.list_for_mission(mission_id)


class InvestigationService:
    """Enforce Mission → Investigation → Tasks → Evidence → Results → Report."""

    def __init__(self, repository: InvestigationRepository) -> None:
        self.repository = repository
        self._lock = threading.RLock()

    def create(
        self,
        mission: Mission,
        tasks: Tuple[Task, ...] = (),
        *,
        investigation_plan_id: Optional[str] = None,
        investigation_design_id: Optional[str] = None,
        investigation_id: Optional[str] = None,
    ) -> Investigation:
        if mission.status != MissionStatus.ACTIVE:
            raise ValidationError(
                "An investigation requires an active mission.",
                context={"mission_id": mission.mission_id, "status": mission.status.value},
            )
        if tasks:
            ExecutionPlan(mission_id=mission.mission_id, tasks=tasks)
        investigation = Investigation(
            **({"investigation_id": investigation_id} if investigation_id else {}),
            mission_id=mission.mission_id,
            investigation_plan_id=investigation_plan_id,
            investigation_design_id=investigation_design_id,
            tasks=tasks,
        )
        self.repository.create(investigation)
        return investigation

    def get(self, investigation_id: str) -> Investigation:
        return self.repository.get(investigation_id)

    def list_for_mission(self, mission_id: str) -> Tuple[Investigation, ...]:
        return self.repository.list_for_mission(mission_id)

    def start(self, investigation_id: str) -> Investigation:
        with self._lock:
            current = self.repository.get(investigation_id)
            self._require_status(current, InvestigationStatus.PENDING)
            updated = current.model_copy(
                update={
                    "status": InvestigationStatus.RUNNING,
                    "started_at": current.started_at or datetime.now(timezone.utc),
                }
            )
            self.repository.update(updated)
            return updated

    def resume_start(self, investigation_id: str) -> Investigation:
        """Reopen a terminal execution only through an explicit recovery request."""
        with self._lock:
            current = self.repository.get(investigation_id)
            if current.status not in {
                InvestigationStatus.RUNNING,
                InvestigationStatus.PARTIAL,
                InvestigationStatus.FAILED,
                InvestigationStatus.CANCELLED,
            }:
                raise ValidationError(
                    "Only partial, failed, or cancelled investigations can be resumed.",
                    context={
                        "investigation_id": investigation_id,
                        "status": current.status.value,
                    },
                )
            updated = current.model_copy(update={
                "status": InvestigationStatus.RUNNING,
                "finished_at": None,
            })
            self.repository.update(updated)
            return updated

    def add_task(self, investigation_id: str, task: Task) -> Investigation:
        with self._lock:
            current = self._running(investigation_id)
            if any(existing.task_id == task.task_id for existing in current.tasks):
                raise ValidationError(
                    "Task identifier already exists in this investigation.",
                    context={
                        "investigation_id": investigation_id,
                        "task_id": task.task_id,
                    },
                )
            tasks = current.tasks + (task,)
            ExecutionPlan(
                mission_id=current.mission_id,
                investigation_id=current.investigation_id,
                tasks=tasks,
            )
            updated = current.model_copy(update={"tasks": tasks})
            self.repository.update(updated)
            return updated

    def add_evidence(self, investigation_id: str, evidence: Evidence) -> Investigation:
        with self._lock:
            current = self._running(investigation_id)
            if evidence.investigation_id != investigation_id:
                raise ValidationError(
                    "Evidence belongs to a different investigation.",
                    context={
                        "investigation_id": investigation_id,
                        "evidence_investigation_id": evidence.investigation_id,
                    },
                )
            if evidence.evidence_id in current.evidence_ids:
                raise ValidationError(
                    "Evidence identifier already exists in this investigation.",
                    context={"evidence_id": evidence.evidence_id},
                )
            updated = current.model_copy(
                update={"evidence_ids": current.evidence_ids + (evidence.evidence_id,)}
            )
            self.repository.update(updated)
            return updated

    def add_result(self, investigation_id: str, result_id: str) -> Investigation:
        with self._lock:
            current = self._running(investigation_id)
            if not result_id.strip():
                raise ValidationError("A result identifier must not be empty.")
            if result_id in current.result_ids:
                raise ValidationError(
                    "Result identifier already exists in this investigation.",
                    context={"result_id": result_id},
                )
            updated = current.model_copy(
                update={"result_ids": current.result_ids + (result_id,)}
            )
            self.repository.update(updated)
            return updated

    def complete(self, investigation_id: str, report: str) -> Investigation:
        with self._lock:
            current = self._running(investigation_id)
            if not report.strip():
                raise ValidationError("A completed investigation requires a report.")
            updated = current.model_copy(
                update={
                    "status": InvestigationStatus.COMPLETED,
                    "report": report,
                    "finished_at": datetime.now(timezone.utc),
                }
            )
            self.repository.update(updated)
            return updated

    def complete_partial(self, investigation_id: str, report: str) -> Investigation:
        """Close an investigation whose workflow produced usable partial artifacts."""
        with self._lock:
            current = self._running(investigation_id)
            if not report.strip():
                raise ValidationError("A partially completed investigation requires a report.")
            updated = current.model_copy(
                update={
                    "status": InvestigationStatus.PARTIAL,
                    "report": report,
                    "finished_at": datetime.now(timezone.utc),
                }
            )
            self.repository.update(updated)
            return updated

    def fail(self, investigation_id: str, reason: str) -> Investigation:
        with self._lock:
            current = self._running(investigation_id)
            if not reason.strip():
                raise ValidationError("A failed investigation requires a failure reason.")
            updated = current.model_copy(
                update={
                    "status": InvestigationStatus.FAILED,
                    "report": reason,
                    "finished_at": datetime.now(timezone.utc),
                }
            )
            self.repository.update(updated)
            return updated

    def cancel(self, investigation_id: str) -> Investigation:
        with self._lock:
            current = self.repository.get(investigation_id)
            if current.status not in {
                InvestigationStatus.PENDING,
                InvestigationStatus.RUNNING,
            }:
                raise ValidationError(
                    "Only pending or running investigations can be cancelled.",
                    context={
                        "investigation_id": investigation_id,
                        "status": current.status.value,
                    },
                )
            updated = current.model_copy(
                update={
                    "status": InvestigationStatus.CANCELLED,
                    "finished_at": datetime.now(timezone.utc),
                }
            )
            self.repository.update(updated)
            return updated

    def _running(self, investigation_id: str) -> Investigation:
        current = self.repository.get(investigation_id)
        self._require_status(current, InvestigationStatus.RUNNING)
        return current

    @staticmethod
    def _require_status(
        investigation: Investigation,
        expected: InvestigationStatus,
    ) -> None:
        if investigation.status != expected:
            raise ValidationError(
                f"Investigation must be {expected.value}, not {investigation.status.value}.",
                context={
                    "investigation_id": investigation.investigation_id,
                    "expected": expected.value,
                    "actual": investigation.status.value,
                },
            )


class MissionService:
    """Manage mission identity and create investigations against stored missions."""

    def __init__(
        self,
        repository: MissionRepository,
        investigations: InvestigationService,
    ) -> None:
        self.repository = repository
        self.investigations = investigations
        self._lock = threading.RLock()

    def create(self, mission: Mission) -> Mission:
        if mission.status != MissionStatus.ACTIVE:
            raise ValidationError("A new mission must be active.")
        self.repository.create(mission)
        return mission

    def get(self, mission_id: str) -> Mission:
        return self.repository.get(mission_id)

    def list(self) -> Tuple[Mission, ...]:
        return self.repository.list()

    def create_investigation(
        self,
        mission_id: str,
        tasks: Tuple[Task, ...] = (),
        *,
        investigation_plan_id: Optional[str] = None,
        investigation_design_id: Optional[str] = None,
        investigation_id: Optional[str] = None,
    ) -> Investigation:
        mission = self.repository.get(mission_id)
        return self.investigations.create(
            mission,
            tasks,
            investigation_plan_id=investigation_plan_id,
            investigation_design_id=investigation_design_id,
            investigation_id=investigation_id,
        )

    def complete(self, mission_id: str) -> Mission:
        with self._lock:
            current = self.repository.get(mission_id)
            if current.status != MissionStatus.ACTIVE:
                raise ValidationError(
                    "Only active missions can be completed.",
                    context={"mission_id": mission_id, "status": current.status.value},
                )
            updated = current.model_copy(
                update={
                    "status": MissionStatus.COMPLETED,
                    "finished_at": utc_now(),
                }
            )
            self.repository.update(updated)
            return updated

    def cancel(self, mission_id: str) -> Mission:
        with self._lock:
            current = self.repository.get(mission_id)
            if current.status != MissionStatus.ACTIVE:
                raise ValidationError(
                    "Only active missions can be cancelled.",
                    context={"mission_id": mission_id, "status": current.status.value},
                )
            updated = current.model_copy(
                update={
                    "status": MissionStatus.CANCELLED,
                    "finished_at": utc_now(),
                }
            )
            self.repository.update(updated)
            return updated
