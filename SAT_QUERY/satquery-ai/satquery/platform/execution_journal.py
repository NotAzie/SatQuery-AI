"""Versioned execution checkpoint and event-journal adapters.

The journal stores execution mechanics, not scientific truth. Outputs are only
recoverable through an explicitly registered codec so an extension cannot be
silently reconstructed with a different contract after an upgrade.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from ..errors import ValidationError
from .contracts import ExecutionPlan, TaskExecution
from .observability import redact_sensitive

T = TypeVar("T")


class TaskOutputEncodingError(TypeError):
    """A successful task output has no stable registered wire representation."""


def _json_value(value: Any) -> Any:
    """Validate a JSON value without coercing scientific or binary objects."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {key: _json_value(item) for key, item in value.items()}
    raise TypeError(f"No execution output codec is registered for {type(value).__name__}.")


class TaskOutputCodec(Protocol[T]):
    codec_id: str
    version: str
    python_type: type[T]

    def encode(self, value: T) -> Any: ...
    def decode(self, payload: Any) -> T: ...


class PydanticTaskOutputCodec:
    """Codec for a named, versioned Pydantic task-output contract."""

    def __init__(self, codec_id: str, version: str, model: type[T]) -> None:
        if not codec_id.strip() or not version.strip() or not issubclass(model, BaseModel):
            raise ValueError("A task output codec requires an id, version, and Pydantic model.")
        self.codec_id = codec_id
        self.version = version
        self.python_type = model
        self._model = model

    def encode(self, value: T) -> Any:
        if not isinstance(value, self._model):
            raise TypeError(f"Codec {self.codec_id!r} cannot encode {type(value).__name__}.")
        try:
            return value.model_dump(mode="json")
        except Exception as exc:
            raise TaskOutputEncodingError(
                f"Output for codec {self.codec_id!r} is not JSON serializable."
            ) from exc

    def decode(self, payload: Any) -> T:
        return self._model.model_validate(payload)


class JsonTaskOutputCodec:
    codec_id = "satquery.json-value"
    version = "1.0.0"
    python_type = object

    def encode(self, value: Any) -> Any:
        return _json_value(value)

    def decode(self, payload: Any) -> Any:
        return _json_value(payload)


class TaskOutputCodecRegistry:
    """Explicit codec registry; typed outputs are never guessed during replay."""

    def __init__(self, *, include_json: bool = True) -> None:
        self._by_id: dict[tuple[str, str], TaskOutputCodec[Any]] = {}
        self._by_type: dict[type[Any], TaskOutputCodec[Any]] = {}
        self._lock = threading.RLock()
        if include_json:
            self.register(JsonTaskOutputCodec())

    def register(
        self, codec: TaskOutputCodec[Any], *, for_encoding: bool = True
    ) -> None:
        key = (codec.codec_id.strip(), codec.version.strip())
        if not all(key):
            raise ValueError("Task output codecs require an id and version.")
        with self._lock:
            if key in self._by_id or (
                for_encoding and codec.python_type in self._by_type
            ):
                raise ValueError(f"Task output codec {key[0]}@{key[1]} is already registered.")
            self._by_id[key] = codec
            if for_encoding:
                self._by_type[codec.python_type] = codec

    def encode(self, value: Any) -> tuple[str, str, Any]:
        with self._lock:
            codec = self._by_type.get(type(value))
            if codec is None and isinstance(value, (dict, list, str, bool, int, float, type(None))):
                codec = self._by_id[("satquery.json-value", "1.0.0")]
        if codec is None:
            raise TypeError(f"No execution output codec is registered for {type(value).__name__}.")
        try:
            return codec.codec_id, codec.version, codec.encode(value)
        except TaskOutputEncodingError:
            raise
        except (TypeError, ValueError) as exc:
            raise TaskOutputEncodingError(str(exc)) from exc

    def decode(self, codec_id: str, version: str, payload: Any) -> Any:
        with self._lock:
            codec = self._by_id.get((codec_id, version))
        if codec is None:
            raise ValidationError(
                f"Execution output codec {codec_id}@{version} is unavailable.",
                context={"codec_id": codec_id, "version": version},
            )
        return codec.decode(payload)

    @classmethod
    def platform_defaults(cls) -> "TaskOutputCodecRegistry":
        from ..schemas import QueryResponse
        from .contracts import ObservationSearchResult, PerceptionResult
        from .intelligence import EvidenceAssessment
        from .reasoning import ScientificReasoningReport

        registry = cls()
        for codec_id, version, model in (
            ("satquery.observation-search-result", "1.0.0", ObservationSearchResult),
            ("satquery.perception-result", "2.0.0", PerceptionResult),
            ("satquery.evidence-assessment", "1.0.0", EvidenceAssessment),
            ("satquery.scientific-reasoning-report", "1.0.0", ScientificReasoningReport),
            ("satquery.query-response", "1.0.0", QueryResponse),
        ):
            registry.register(PydanticTaskOutputCodec(codec_id, version, model))
        return registry


class ExecutionJournal(Protocol):
    def has_execution(self, plan_id: str) -> bool: ...
    def begin(self, plan: ExecutionPlan, *, resume: bool) -> dict[str, TaskExecution]: ...
    def checkpoints(self, plan_id: str) -> dict[str, TaskExecution]: ...
    def record_event(self, plan_id: str, event_type: str, payload: Mapping[str, Any]) -> None: ...
    def checkpoint(self, plan: ExecutionPlan, task: TaskExecution) -> None: ...
    def events(self, plan_id: str, *, after_sequence: int = 0) -> tuple[dict[str, Any], ...]: ...


class InMemoryExecutionJournal:
    """Process-local journal with the same checks as the durable adapter."""

    def __init__(self, codecs: TaskOutputCodecRegistry | None = None) -> None:
        self.codecs = codecs or TaskOutputCodecRegistry.platform_defaults()
        self._plans: dict[str, tuple[str, dict[str, Any]]] = {}
        self._checkpoints: dict[str, dict[str, tuple[str, str, Any, dict[str, Any]]]] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def has_execution(self, plan_id: str) -> bool:
        with self._lock:
            return plan_id in self._plans

    def checkpoints(self, plan_id: str) -> dict[str, TaskExecution]:
        with self._lock:
            stored = dict(self._checkpoints.get(plan_id, {}))
        return {
            task_id: _restore_checkpoint(value, self.codecs)
            for task_id, value in stored.items()
        }

    def begin(self, plan: ExecutionPlan, *, resume: bool) -> dict[str, TaskExecution]:
        plan_json = plan.model_dump(mode="json")
        fingerprint = _plan_fingerprint(plan_json)
        with self._lock:
            existing = self._plans.get(plan.plan_id)
            if resume and existing is None:
                raise ValidationError("No prior execution exists to resume.")
            if existing is not None and existing[0] != fingerprint:
                raise ValidationError("Execution plan identity was reused for different content.")
            if existing is not None and not resume:
                raise ValidationError("This execution already exists; resume it explicitly.")
            self._plans.setdefault(plan.plan_id, (fingerprint, plan_json))
            checkpoints = dict(self._checkpoints.get(plan.plan_id, {})) if resume else {}
            if resume:
                self.record_event(plan.plan_id, "execution.resumed", {"plan_fingerprint": fingerprint})
        if not resume:
            self.record_event(plan.plan_id, "execution.started", {"plan_fingerprint": fingerprint})
        return {task_id: _restore_checkpoint(value, self.codecs) for task_id, value in checkpoints.items()}

    def record_event(self, plan_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            previous = next((item["event_sha256"] for item in reversed(self._events) if item["plan_id"] == plan_id), "0" * 64)
            event = {
                "sequence": len(self._events) + 1, "plan_id": plan_id,
                "event_type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": _json_value(payload), "previous_event_sha256": previous,
            }
            event["event_sha256"] = _event_digest(event)
            self._events.append(event)

    def checkpoint(self, plan: ExecutionPlan, task: TaskExecution) -> None:
        if task.status.value != "succeeded":
            return
        codec_id, version, payload = self.codecs.encode(task.output)
        stored = (codec_id, version, payload, task.model_dump(mode="json", exclude={"output"}))
        with self._lock:
            existing = self._checkpoints.setdefault(plan.plan_id, {}).get(task.task_id)
            if existing is not None and existing != stored:
                raise ValidationError("A successful execution checkpoint is immutable.")
            self._checkpoints[plan.plan_id][task.task_id] = stored
        self.record_event(plan.plan_id, "task.checkpointed", {"task_id": task.task_id, "codec_id": codec_id, "codec_version": version})

    def events(self, plan_id: str, *, after_sequence: int = 0) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(_json_value(item) for item in self._events if item["plan_id"] == plan_id and item["sequence"] > after_sequence)


class SQLiteExecutionJournal:
    """Transactional, single-host execution journal suitable for local recovery."""

    SCHEMA_VERSION = 2

    def __init__(self, path: str | Path, *, codecs: TaskOutputCodecRegistry | None = None, busy_timeout_seconds: float = 5.0) -> None:
        if busy_timeout_seconds <= 0 or not math.isfinite(busy_timeout_seconds):
            raise ValueError("Execution journal busy timeout must be finite and positive.")
        if str(path) == ":memory:":
            raise ValueError("SQLiteExecutionJournal requires a durable file path.")
        self.path = Path(path).expanduser().resolve()
        self.busy_timeout_seconds = busy_timeout_seconds
        self.codecs = codecs or TaskOutputCodecRegistry.platform_defaults()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=self.busy_timeout_seconds, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_execution_schema (singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL)")
            row = connection.execute("SELECT version FROM satquery_execution_schema WHERE singleton=1").fetchone()
            if row is not None and row["version"] != self.SCHEMA_VERSION:
                raise ValueError(f"Unsupported execution journal schema version {row['version']}.")
            connection.execute("INSERT OR IGNORE INTO satquery_execution_schema(singleton, version) VALUES (1, ?)", (self.SCHEMA_VERSION,))
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_execution_runs (plan_id TEXT PRIMARY KEY, plan_fingerprint TEXT NOT NULL, plan_json TEXT NOT NULL, created_at TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_execution_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT NOT NULL, event_type TEXT NOT NULL, timestamp TEXT NOT NULL, payload_json TEXT NOT NULL, previous_event_sha256 TEXT NOT NULL, event_sha256 TEXT NOT NULL, FOREIGN KEY(plan_id) REFERENCES satquery_execution_runs(plan_id))")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_satquery_execution_events_plan ON satquery_execution_events(plan_id, sequence)")
            connection.execute("CREATE TABLE IF NOT EXISTS satquery_execution_checkpoints (plan_id TEXT NOT NULL, task_id TEXT NOT NULL, plan_fingerprint TEXT NOT NULL, codec_id TEXT NOT NULL, codec_version TEXT NOT NULL, output_json TEXT NOT NULL, output_sha256 TEXT NOT NULL, task_json TEXT NOT NULL, task_sha256 TEXT NOT NULL, PRIMARY KEY(plan_id, task_id), FOREIGN KEY(plan_id) REFERENCES satquery_execution_runs(plan_id))")
            for table in (
                "satquery_execution_runs",
                "satquery_execution_events",
                "satquery_execution_checkpoints",
            ):
                connection.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_update "
                    f"BEFORE UPDATE ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'execution journal records are immutable'); END"
                )
                connection.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete "
                    f"BEFORE DELETE ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'execution journal records are immutable'); END"
                )

    def begin(self, plan: ExecutionPlan, *, resume: bool) -> dict[str, TaskExecution]:
        plan_json = plan.model_dump(mode="json")
        encoded_plan = _canonical_json(redact_sensitive(plan_json))
        fingerprint = _plan_fingerprint(plan_json)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT plan_fingerprint FROM satquery_execution_runs WHERE plan_id=?", (plan.plan_id,)).fetchone()
                if row is not None and row["plan_fingerprint"] != fingerprint:
                    raise ValidationError("Execution plan identity was reused for different content.")
                if resume and row is None:
                    raise ValidationError("No prior execution exists to resume.")
                if row is not None and not resume:
                    raise ValidationError("This execution already exists; resume it explicitly.")
                if row is None:
                    connection.execute("INSERT INTO satquery_execution_runs(plan_id, plan_fingerprint, plan_json, created_at) VALUES (?, ?, ?, ?)", (plan.plan_id, fingerprint, encoded_plan, datetime.now(timezone.utc).isoformat()))
                checkpoints: dict[str, TaskExecution] = {}
                if resume:
                    for checkpoint in connection.execute("SELECT * FROM satquery_execution_checkpoints WHERE plan_id=? ORDER BY task_id", (plan.plan_id,)):
                        if checkpoint["plan_fingerprint"] != fingerprint:
                            raise ValidationError("Checkpoint does not match the current execution plan.")
                        if (
                            _sha256(checkpoint["output_json"]) != checkpoint["output_sha256"]
                            or _sha256(checkpoint["task_json"]) != checkpoint["task_sha256"]
                        ):
                            raise ValidationError(
                                "Execution checkpoint integrity verification failed.",
                                context={"task_id": checkpoint["task_id"]},
                            )
                        payload = json.loads(checkpoint["output_json"])
                        task_payload = json.loads(checkpoint["task_json"])
                        task_payload["output"] = self.codecs.decode(checkpoint["codec_id"], checkpoint["codec_version"], payload)
                        checkpoints[checkpoint["task_id"]] = TaskExecution.model_validate(task_payload)
                event_type = "execution.resumed" if resume else "execution.started"
                self._insert_event(connection, plan.plan_id, event_type, {"plan_fingerprint": fingerprint})
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return checkpoints

    def has_execution(self, plan_id: str) -> bool:
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM satquery_execution_runs WHERE plan_id=?", (plan_id,)
            ).fetchone() is not None

    def checkpoints(self, plan_id: str) -> dict[str, TaskExecution]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM satquery_execution_checkpoints WHERE plan_id=? ORDER BY task_id",
                (plan_id,),
            ).fetchall()
        restored: dict[str, TaskExecution] = {}
        for row in rows:
            if (
                _sha256(row["output_json"]) != row["output_sha256"]
                or _sha256(row["task_json"]) != row["task_sha256"]
            ):
                raise ValidationError(
                    "Execution checkpoint integrity verification failed.",
                    context={"task_id": row["task_id"]},
                )
            task_payload = json.loads(row["task_json"])
            task_payload["output"] = self.codecs.decode(
                row["codec_id"], row["codec_version"], json.loads(row["output_json"])
            )
            restored[row["task_id"]] = TaskExecution.model_validate(task_payload)
        return restored

    def _insert_event(self, connection: sqlite3.Connection, plan_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM satquery_execution_events"
        ).fetchone()[0]
        previous = connection.execute(
            "SELECT event_sha256 FROM satquery_execution_events WHERE plan_id=? ORDER BY sequence DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        event = {
            "sequence": sequence,
            "plan_id": plan_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": _json_value(payload),
            "previous_event_sha256": previous["event_sha256"] if previous else "0" * 64,
        }
        event["event_sha256"] = _event_digest(event)
        connection.execute(
            "INSERT INTO satquery_execution_events(sequence, plan_id, event_type, timestamp, payload_json, previous_event_sha256, event_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event["sequence"], plan_id, event_type, event["timestamp"],
                _canonical_json(event["payload"]), event["previous_event_sha256"],
                event["event_sha256"],
            ),
        )

    def record_event(self, plan_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if connection.execute("SELECT 1 FROM satquery_execution_runs WHERE plan_id=?", (plan_id,)).fetchone() is None:
                    raise ValidationError("Execution journal does not contain this plan.")
                self._insert_event(connection, plan_id, event_type, payload)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def checkpoint(self, plan: ExecutionPlan, task: TaskExecution) -> None:
        if task.status.value != "succeeded":
            return
        codec_id, version, payload = self.codecs.encode(task.output)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT plan_fingerprint, codec_id, codec_version, output_json, task_json FROM satquery_execution_checkpoints WHERE plan_id=? AND task_id=?", (plan.plan_id, task.task_id)).fetchone()
                fingerprint = _plan_fingerprint(plan.model_dump(mode="json"))
                output_json = _canonical_json(payload)
                task_metadata = task.model_dump(mode="json", exclude={"output"})
                task_json = _canonical_json(redact_sensitive(task_metadata))
                output_sha256, task_sha256 = _sha256(output_json), _sha256(task_json)
                if row is not None:
                    expected = (
                        fingerprint, codec_id, version, output_json, output_sha256,
                        task_json, task_sha256,
                    )
                    actual = tuple(row[key] for key in (
                        "plan_fingerprint", "codec_id", "codec_version", "output_json",
                        "output_sha256", "task_json", "task_sha256",
                    ))
                    if actual != expected:
                        raise ValidationError("A successful execution checkpoint is immutable.")
                else:
                    connection.execute("INSERT INTO satquery_execution_checkpoints(plan_id, task_id, plan_fingerprint, codec_id, codec_version, output_json, output_sha256, task_json, task_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (plan.plan_id, task.task_id, fingerprint, codec_id, version, output_json, output_sha256, task_json, task_sha256))
                self._insert_event(connection, plan.plan_id, "task.checkpointed", {"task_id": task.task_id, "codec_id": codec_id, "codec_version": version})
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def events(self, plan_id: str, *, after_sequence: int = 0) -> tuple[dict[str, Any], ...]:
        with self._connection() as connection:
            rows = connection.execute("SELECT sequence, plan_id, event_type, timestamp, payload_json, previous_event_sha256, event_sha256 FROM satquery_execution_events WHERE plan_id=? ORDER BY sequence", (plan_id,)).fetchall()
        events = tuple({
            "sequence": row["sequence"], "plan_id": row["plan_id"],
            "event_type": row["event_type"], "timestamp": row["timestamp"],
            "payload": json.loads(row["payload_json"]),
            "previous_event_sha256": row["previous_event_sha256"],
            "event_sha256": row["event_sha256"],
        } for row in rows)
        _verify_event_chain(events)
        return tuple(event for event in events if event["sequence"] > after_sequence)


def _restore_checkpoint(value: tuple[str, str, Any, dict[str, Any]], codecs: TaskOutputCodecRegistry) -> TaskExecution:
    codec_id, version, payload, task = value
    restored = dict(task)
    restored["output"] = codecs.decode(codec_id, version, payload)
    return TaskExecution.model_validate(restored)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event_digest(event: Mapping[str, Any]) -> str:
    return _sha256(_canonical_json({
        key: value for key, value in event.items() if key != "event_sha256"
    }))


def _verify_event_chain(events: tuple[dict[str, Any], ...]) -> None:
    previous_by_plan: dict[str, str] = {}
    for event in events:
        expected_previous = previous_by_plan.get(event["plan_id"], "0" * 64)
        if event["previous_event_sha256"] != expected_previous:
            raise ValidationError(
                "Execution event chain is discontinuous.",
                context={"sequence": event["sequence"]},
            )
        if _event_digest(event) != event["event_sha256"]:
            raise ValidationError(
                "Execution event integrity verification failed.",
                context={"sequence": event["sequence"]},
            )
        previous_by_plan[event["plan_id"]] = event["event_sha256"]


def _plan_fingerprint(plan_payload: Mapping[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(_canonical_json(plan_payload).encode("utf-8")).hexdigest()
