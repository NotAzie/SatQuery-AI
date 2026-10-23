"""Searchable, storage-neutral index for cross-investigation Earth knowledge.

Earth Memory is an index over recorded artifacts, not a learning system. It
stores immutable artifact payloads and explicit relationships so another
repository/index adapter can implement the same contract later.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sqlite3
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from .contracts import Contract

_REVISION_MODULUS = (1 << 521) - 1
_REVISION_ACCUMULATOR_WIDTH = 132
_MAX_INDEXED_SEARCH_NGRAMS = 400

MemoryArtifactType = Literal[
    "mission", "investigation", "plan", "observation", "evidence", "hypothesis",
    "capability_snapshot",
    "scientific_method", "reproducibility_artifact", "provenance_node",
    "earth_object", "earth_object_extraction", "object_relationship",
    "earth_object_transition",
    "observation_stack", "temporal_difference",
    "monitoring_schedule", "monitoring_run", "monitoring_event",
    "monitoring_notification",
    "monitoring_comparison",
    "investigation_comparison",
]


class EarthMemoryArtifact(Contract):
    artifact_id: str = Field(min_length=1)
    artifact_type: MemoryArtifactType
    investigation_id: str | None = None
    mission_id: str | None = None
    method_id: str | None = None
    method_version: str | None = None
    source_artifact_ids: tuple[str, ...] = ()
    observed_at: str | None = None
    indexed_at: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    search_text: str
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_artifact_ids")
    @classmethod
    def canonicalize_source_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def payload_digest_matches_content(self) -> EarthMemoryArtifact:
        encoded = json.dumps(
            self.payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if digest != self.payload_sha256:
            raise ValueError("Earth Memory payload digest does not match its content")
        if self.search_text != encoded:
            raise ValueError("Earth Memory search text must be the canonical payload")
        return self


class EarthMemoryQuery(Contract):
    text: str | None = None
    artifact_types: tuple[MemoryArtifactType, ...] = ()
    canonical_variable: str | None = Field(default=None, min_length=1)
    investigation_id: str | None = None
    mission_id: str | None = None
    method_id: str | None = None
    source_artifact_id: str | None = None
    spatial_bbox: tuple[float, float, float, float] | None = None
    spatial_crs: str | None = None
    temporal_start: datetime | None = None
    temporal_end: datetime | None = None
    cursor: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_spatiotemporal_query(self) -> EarthMemoryQuery:
        if (self.spatial_bbox is None) != (self.spatial_crs is None):
            raise ValueError("spatial_bbox and spatial_crs must be supplied together")
        if self.spatial_bbox is not None:
            min_x, min_y, max_x, max_y = self.spatial_bbox
            if not all(math.isfinite(value) for value in self.spatial_bbox):
                raise ValueError("spatial_bbox coordinates must be finite")
            if min_x > max_x or min_y > max_y:
                raise ValueError("spatial_bbox bounds must be ordered")
            if not self.spatial_crs or not self.spatial_crs.strip():
                raise ValueError("spatial_crs must be non-empty")
        if (self.temporal_start is None) != (self.temporal_end is None):
            raise ValueError("temporal_start and temporal_end must be supplied together")
        if self.temporal_start is not None:
            if self.temporal_start.tzinfo is None or self.temporal_end.tzinfo is None:
                raise ValueError("Earth Memory temporal filters must be timezone-aware")
            if self.temporal_start > self.temporal_end:
                raise ValueError("temporal_start must not be after temporal_end")
        return self


class EarthMemorySearchResult(Contract):
    artifacts: tuple[EarthMemoryArtifact, ...] = ()
    total: int = Field(ge=0)
    index_revision: str
    index_revision_algorithm: Literal["sha256_counted_sha512_sum_v1"] = (
        "sha256_counted_sha512_sum_v1"
    )
    semantics: Literal["deterministic_literal_search"] = "deterministic_literal_search"
    spatial_semantics: Literal["inclusive_same_crs_bbox_overlap"] | None = None
    temporal_semantics: Literal["inclusive_interval_overlap"] | None = None
    next_cursor: str | None = None


class EarthMemoryIntegrityReport(Contract):
    repository: str
    status: Literal["healthy", "corrupt"]
    artifacts_checked: int
    index_revision: str
    errors: tuple[str, ...] = ()


class EarthMemoryCursorError(ValueError):
    """A continuation cursor is malformed or incompatible with its query."""


class StaleEarthMemoryCursorError(EarthMemoryCursorError):
    """The indexed snapshot changed after the cursor was issued."""


class EarthMemoryRepository(Protocol):
    def upsert(self, artifact: EarthMemoryArtifact) -> None: ...
    def search(self, query: EarthMemoryQuery) -> EarthMemorySearchResult: ...
    def get(self, artifact_id: str) -> EarthMemoryArtifact | None: ...
    def all(self) -> tuple[EarthMemoryArtifact, ...]: ...


class InMemoryEarthMemory:
    """Thread-safe deterministic exact-token index; no semantic ranking implied."""

    def __init__(self, artifacts: Iterable[EarthMemoryArtifact] = ()) -> None:
        self._artifacts: dict[str, EarthMemoryArtifact] = {}
        self._lock = threading.RLock()
        self._revision_count = 0
        self._revision_accumulator = 0
        for artifact in artifacts:
            self.upsert(artifact)

    def upsert(self, artifact: EarthMemoryArtifact) -> None:
        with self._lock:
            current = self._artifacts.get(artifact.artifact_id)
            if current is not None and current != artifact:
                raise ValueError(
                    "Earth Memory artifact IDs are immutable; changed records require a new artifact ID"
                )
            if current is None:
                self._revision_count += 1
                self._revision_accumulator = (
                    self._revision_accumulator
                    + _revision_entry_value(
                        artifact.artifact_id, _artifact_record_digest(artifact)
                    )
                ) % _REVISION_MODULUS
            self._artifacts[artifact.artifact_id] = artifact

    def get(self, artifact_id: str) -> EarthMemoryArtifact | None:
        with self._lock:
            return self._artifacts.get(artifact_id)

    def all(self) -> tuple[EarthMemoryArtifact, ...]:
        with self._lock:
            return tuple(self._artifacts[key] for key in sorted(self._artifacts))

    def search(self, query: EarthMemoryQuery) -> EarthMemorySearchResult:
        terms = tuple(
            token.casefold() for token in (query.text or "").split() if token
        )
        with self._lock:
            values = tuple(self._artifacts[key] for key in sorted(self._artifacts))
            revision = _revision_from_state(
                self._revision_count, self._revision_accumulator
            )
        after_artifact_id = _decode_memory_cursor(query.cursor, revision, query)
        matched = []
        for item in values:
            if after_artifact_id is not None and item.artifact_id <= after_artifact_id:
                continue
            if query.artifact_types and item.artifact_type not in query.artifact_types:
                continue
            if query.investigation_id and item.investigation_id != query.investigation_id:
                continue
            if query.mission_id and item.mission_id != query.mission_id:
                continue
            if query.method_id and item.method_id != query.method_id:
                continue
            if query.canonical_variable and not _matches_canonical_variable(
                item, query.canonical_variable
            ):
                continue
            if query.source_artifact_id and query.source_artifact_id not in item.source_artifact_ids:
                continue
            if not _matches_spatiotemporal_query(item, query):
                continue
            haystack = _search_haystack(item)
            if terms and not all(term in haystack for term in terms):
                continue
            matched.append(item)
        page = matched[:query.limit]
        next_cursor = (
            _encode_memory_cursor(revision, page[-1].artifact_id, query)
            if len(matched) > query.limit else None
        )
        return EarthMemorySearchResult(
            artifacts=tuple(page), total=len(matched),
            index_revision=revision,
            spatial_semantics=(
                "inclusive_same_crs_bbox_overlap" if query.spatial_bbox is not None else None
            ),
            temporal_semantics=(
                "inclusive_interval_overlap" if query.temporal_start is not None else None
            ),
            next_cursor=next_cursor,
        )


class SQLiteEarthMemory:
    """Durable local Earth Memory repository with immutable records.

    Each operation owns a short-lived SQLite connection. WAL and bounded busy
    waits support concurrent API workers on one local database file. Exact
    substring terms use the same Unicode ``casefold`` semantics as the memory
    adapter; no SQLite tokenizer or relevance ranking changes search meaning.
    """

    SCHEMA_VERSION = 6

    def __init__(self, path: str | Path, *, busy_timeout_seconds: float = 5.0) -> None:
        if busy_timeout_seconds <= 0 or not math.isfinite(busy_timeout_seconds):
            raise ValueError("Earth Memory SQLite busy timeout must be finite and positive")
        database_path = Path(path).expanduser()
        if str(database_path) == ":memory:":
            raise ValueError("SQLiteEarthMemory requires a durable file path")
        self.path = database_path.resolve()
        self.busy_timeout_seconds = busy_timeout_seconds
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path), timeout=self.busy_timeout_seconds, isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}"
        )
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
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS earth_memory_schema "
                    "(singleton INTEGER PRIMARY KEY CHECK (singleton = 1), version INTEGER NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS earth_memory_artifacts ("
                    "artifact_id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL, "
                    "investigation_id TEXT, mission_id TEXT, method_id TEXT, "
                    "method_version TEXT, indexed_at TEXT NOT NULL, "
                    "payload_sha256 TEXT NOT NULL, record_sha256 TEXT NOT NULL, "
                    "search_index TEXT NOT NULL, artifact_json TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS earth_memory_sources ("
                    "artifact_id TEXT NOT NULL, source_artifact_id TEXT NOT NULL, "
                    "PRIMARY KEY (artifact_id, source_artifact_id), "
                    "FOREIGN KEY (artifact_id) REFERENCES earth_memory_artifacts(artifact_id) ON DELETE CASCADE)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_type_id "
                    "ON earth_memory_artifacts(artifact_type, artifact_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_investigation "
                    "ON earth_memory_artifacts(investigation_id, artifact_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_mission "
                    "ON earth_memory_artifacts(mission_id, artifact_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_method "
                    "ON earth_memory_artifacts(method_id, artifact_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_source "
                    "ON earth_memory_sources(source_artifact_id, artifact_id)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS earth_memory_spatiotemporal ("
                    "artifact_id TEXT PRIMARY KEY, spatial_crs TEXT, min_x REAL, min_y REAL, "
                    "max_x REAL, max_y REAL, temporal_start TEXT, temporal_end TEXT, "
                    "FOREIGN KEY (artifact_id) REFERENCES earth_memory_artifacts(artifact_id) ON DELETE CASCADE)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_spatial "
                    "ON earth_memory_spatiotemporal(spatial_crs, min_x, max_x, min_y, max_y)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_temporal "
                    "ON earth_memory_spatiotemporal(temporal_start, temporal_end)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS earth_memory_variables ("
                    "artifact_id TEXT NOT NULL, canonical_variable TEXT NOT NULL, "
                    "PRIMARY KEY (artifact_id, canonical_variable), "
                    "FOREIGN KEY (artifact_id) REFERENCES earth_memory_artifacts(artifact_id) ON DELETE CASCADE)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_variable "
                    "ON earth_memory_variables(canonical_variable, artifact_id)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS earth_memory_ngrams ("
                    "artifact_id TEXT NOT NULL, ngram TEXT NOT NULL, "
                    "PRIMARY KEY (artifact_id, ngram), "
                    "FOREIGN KEY (artifact_id) REFERENCES earth_memory_artifacts(artifact_id) ON DELETE CASCADE)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_earth_memory_ngram "
                    "ON earth_memory_ngrams(ngram, artifact_id)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS earth_memory_revision_state ("
                    "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                    "artifact_count INTEGER NOT NULL, accumulator TEXT NOT NULL)"
                )
                row = connection.execute(
                    "SELECT version FROM earth_memory_schema WHERE singleton = 1"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO earth_memory_schema(singleton, version) VALUES (1, ?)",
                        (self.SCHEMA_VERSION,),
                    )
                    self._rebuild_spatiotemporal_index(connection)
                    self._rebuild_canonical_variable_index(connection)
                    self._rebuild_search_ngram_index(connection)
                    self._rebuild_revision_state(connection)
                elif row["version"] in {1, 2, 3, 4, 5}:
                    self._rebuild_spatiotemporal_index(connection)
                    self._rebuild_canonical_variable_index(connection)
                    self._rebuild_search_ngram_index(connection)
                    self._rebuild_revision_state(connection)
                    connection.execute(
                        "UPDATE earth_memory_schema SET version = ? WHERE singleton = 1",
                        (self.SCHEMA_VERSION,),
                    )
                elif row["version"] != self.SCHEMA_VERSION:
                    raise ValueError(
                        f"Unsupported Earth Memory schema version {row['version']}; "
                        f"this runtime supports {self.SCHEMA_VERSION}"
                    )
                revision_state = connection.execute(
                    "SELECT 1 FROM earth_memory_revision_state WHERE singleton = 1"
                ).fetchone()
                if revision_state is None:
                    raise ValueError("Earth Memory revision state is missing")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _rebuild_spatiotemporal_index(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM earth_memory_spatiotemporal")
        rows = connection.execute(
            "SELECT artifact_id, artifact_json FROM earth_memory_artifacts ORDER BY artifact_id"
        ).fetchall()
        for row in rows:
            _write_spatiotemporal_index(connection, _decode_artifact(row["artifact_json"]))

    @staticmethod
    def _rebuild_canonical_variable_index(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM earth_memory_variables")
        rows = connection.execute(
            "SELECT artifact_id, artifact_json FROM earth_memory_artifacts ORDER BY artifact_id"
        ).fetchall()
        for row in rows:
            _write_canonical_variable_index(
                connection, _decode_artifact(row["artifact_json"])
            )

    @staticmethod
    def _rebuild_search_ngram_index(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM earth_memory_ngrams")
        rows = connection.execute(
            "SELECT artifact_json FROM earth_memory_artifacts ORDER BY artifact_id"
        ).fetchall()
        for row in rows:
            artifact = _decode_artifact(row["artifact_json"])
            _write_search_ngram_index(connection, artifact)

    @staticmethod
    def _rebuild_revision_state(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT artifact_id, artifact_json, record_sha256, search_index "
            "FROM earth_memory_artifacts ORDER BY artifact_id"
        ).fetchall()
        count = 0
        accumulator = 0
        for row in rows:
            artifact = _verified_row_artifact(row)
            count += 1
            accumulator = (
                accumulator
                + _revision_entry_value(artifact.artifact_id, row["record_sha256"])
            ) % _REVISION_MODULUS
        connection.execute(
            "INSERT INTO earth_memory_revision_state(singleton, artifact_count, accumulator) "
            "VALUES (1, ?, ?) ON CONFLICT(singleton) DO UPDATE SET "
            "artifact_count = excluded.artifact_count, accumulator = excluded.accumulator",
            (count, f"{accumulator:0132x}"),
        )

    def upsert(self, artifact: EarthMemoryArtifact) -> None:
        encoded = _canonical_json(artifact.model_dump(mode="json"))
        record_sha256 = _artifact_record_digest(artifact)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = connection.execute(
                    "SELECT artifact_json FROM earth_memory_artifacts WHERE artifact_id = ?",
                    (artifact.artifact_id,),
                ).fetchone()
                if current is not None:
                    existing = _decode_artifact(current["artifact_json"])
                    if existing != artifact:
                        raise ValueError(
                            "Earth Memory artifact IDs are immutable; changed records require a new artifact ID"
                        )
                else:
                    connection.execute(
                        "INSERT INTO earth_memory_artifacts ("
                        "artifact_id, artifact_type, investigation_id, mission_id, method_id, "
                        "method_version, indexed_at, payload_sha256, record_sha256, search_index, artifact_json"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            artifact.artifact_id, artifact.artifact_type,
                            artifact.investigation_id, artifact.mission_id,
                            artifact.method_id, artifact.method_version,
                            artifact.indexed_at, artifact.payload_sha256, record_sha256,
                            _search_haystack(artifact), encoded,
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO earth_memory_sources(artifact_id, source_artifact_id) VALUES (?, ?)",
                        ((artifact.artifact_id, item) for item in artifact.source_artifact_ids),
                    )
                    _write_spatiotemporal_index(connection, artifact)
                    _write_canonical_variable_index(connection, artifact)
                    _write_search_ngram_index(connection, artifact)
                    state = connection.execute(
                        "SELECT artifact_count, accumulator FROM earth_memory_revision_state "
                        "WHERE singleton = 1"
                    ).fetchone()
                    if state is None:
                        raise ValueError("Earth Memory revision state is missing")
                    accumulator = int(state["accumulator"], 16)
                    accumulator = (
                        accumulator
                        + _revision_entry_value(artifact.artifact_id, record_sha256)
                    ) % _REVISION_MODULUS
                    connection.execute(
                        "UPDATE earth_memory_revision_state SET artifact_count = ?, accumulator = ? "
                        "WHERE singleton = 1",
                        (state["artifact_count"] + 1, f"{accumulator:0132x}"),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def get(self, artifact_id: str) -> EarthMemoryArtifact | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT artifact_json, record_sha256, search_index FROM earth_memory_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return None if row is None else _verified_row_artifact(row)

    def all(self) -> tuple[EarthMemoryArtifact, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT artifact_json, record_sha256, search_index FROM earth_memory_artifacts ORDER BY artifact_id"
            ).fetchall()
        return tuple(_verified_row_artifact(row) for row in rows)

    def search(self, query: EarthMemoryQuery) -> EarthMemorySearchResult:
        terms = tuple(token.casefold() for token in (query.text or "").split() if token)
        with self._connection() as connection:
            connection.execute("BEGIN")
            revision_state = connection.execute(
                "SELECT artifact_count, accumulator FROM earth_memory_revision_state "
                "WHERE singleton = 1"
            ).fetchone()
            if revision_state is None:
                raise ValueError("Earth Memory revision state is missing")
            revision = _revision_from_state(
                revision_state["artifact_count"], int(revision_state["accumulator"], 16)
            )
            after_artifact_id = _decode_memory_cursor(query.cursor, revision, query)
            conditions = []
            parameters: list[Any] = []
            joins = []
            if after_artifact_id is not None:
                conditions.append("a.artifact_id > ?")
                parameters.append(after_artifact_id)
            if query.artifact_types:
                placeholders = ", ".join("?" for _ in query.artifact_types)
                conditions.append(f"a.artifact_type IN ({placeholders})")
                parameters.extend(query.artifact_types)
            if query.investigation_id:
                conditions.append("a.investigation_id = ?")
                parameters.append(query.investigation_id)
            if query.mission_id:
                conditions.append("a.mission_id = ?")
                parameters.append(query.mission_id)
            if query.method_id:
                conditions.append("a.method_id = ?")
                parameters.append(query.method_id)
            if query.source_artifact_id:
                joins.append(
                    "JOIN earth_memory_sources source_filter "
                    "ON source_filter.artifact_id = a.artifact_id"
                )
                conditions.append("source_filter.source_artifact_id = ?")
                parameters.append(query.source_artifact_id)
            if query.spatial_bbox is not None:
                min_x, min_y, max_x, max_y = query.spatial_bbox
                conditions.extend((
                    "s.spatial_crs = ?", "s.min_x <= ?", "s.max_x >= ?",
                    "s.min_y <= ?", "s.max_y >= ?",
                ))
                parameters.extend((query.spatial_crs, max_x, min_x, max_y, min_y))
            if query.temporal_start is not None:
                conditions.extend((
                    "s.temporal_start IS NOT NULL", "s.temporal_end IS NOT NULL",
                    "s.temporal_start <= ?", "s.temporal_end >= ?",
                ))
                parameters.extend((
                    _canonical_timestamp(query.temporal_end),
                    _canonical_timestamp(query.temporal_start),
                ))
            if query.canonical_variable:
                joins.append(
                    "JOIN earth_memory_variables v ON v.artifact_id = a.artifact_id"
                )
                conditions.append("v.canonical_variable = ?")
                parameters.append(query.canonical_variable.strip().casefold())
            query_ngrams = _search_query_ngrams(terms)
            if query_ngrams:
                placeholders = ", ".join("?" for _ in query_ngrams)
                conditions.append(
                    "a.artifact_id IN (SELECT artifact_id FROM earth_memory_ngrams "
                    f"WHERE ngram IN ({placeholders}) GROUP BY artifact_id "
                    "HAVING COUNT(*) = ?)"
                )
                parameters.extend(query_ngrams)
                parameters.append(len(query_ngrams))
            if query.spatial_bbox is not None or query.temporal_start is not None:
                joins.append(
                    "JOIN earth_memory_spatiotemporal s ON s.artifact_id = a.artifact_id"
                )
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            row_cursor = connection.execute(
                "SELECT a.artifact_id, a.artifact_type, a.investigation_id, a.mission_id, a.method_id, "
                "a.artifact_json, a.record_sha256, a.search_index"
                " FROM earth_memory_artifacts a"
                + (" " + " ".join(joins) if joins else "")
                + where + " ORDER BY a.artifact_id",
                parameters,
            )
            page_candidates = []
            total = 0
            while rows := row_cursor.fetchmany(256):
                for row in rows:
                    artifact = _verified_row_artifact(row)
                    if query.artifact_types and artifact.artifact_type not in query.artifact_types:
                        continue
                    if query.investigation_id and artifact.investigation_id != query.investigation_id:
                        continue
                    if query.mission_id and artifact.mission_id != query.mission_id:
                        continue
                    if query.method_id and artifact.method_id != query.method_id:
                        continue
                    if query.canonical_variable and not _matches_canonical_variable(
                        artifact, query.canonical_variable
                    ):
                        continue
                    if (
                        query.source_artifact_id
                        and query.source_artifact_id not in artifact.source_artifact_ids
                    ):
                        continue
                    if not _matches_spatiotemporal_query(artifact, query):
                        continue
                    haystack = _search_haystack(artifact)
                    if terms and not all(term in haystack for term in terms):
                        continue
                    total += 1
                    if len(page_candidates) < query.limit + 1:
                        page_candidates.append(artifact)
            connection.execute("COMMIT")
        page = page_candidates[:query.limit]
        next_cursor = (
            _encode_memory_cursor(revision, page[-1].artifact_id, query)
            if total > query.limit else None
        )
        return EarthMemorySearchResult(
            artifacts=tuple(page), total=total,
            index_revision=revision,
            spatial_semantics=(
                "inclusive_same_crs_bbox_overlap" if query.spatial_bbox is not None else None
            ),
            temporal_semantics=(
                "inclusive_interval_overlap" if query.temporal_start is not None else None
            ),
            next_cursor=next_cursor,
        )

    def verify_integrity(self) -> EarthMemoryIntegrityReport:
        errors: list[str] = []
        sqlite_status = "unknown"
        with self._connection() as connection:
            connection.execute("BEGIN")
            sqlite_status = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if sqlite_status != "ok":
                errors.append(f"SQLite integrity_check: {sqlite_status}")
            rows = connection.execute(
                "SELECT artifact_id, artifact_json, record_sha256, search_index FROM earth_memory_artifacts ORDER BY artifact_id"
            ).fetchall()
            indexed_sources = connection.execute(
                "SELECT artifact_id, source_artifact_id FROM earth_memory_sources "
                "ORDER BY artifact_id, source_artifact_id"
            ).fetchall()
            revision_rows = connection.execute(
                "SELECT artifact_id, record_sha256 FROM earth_memory_artifacts ORDER BY artifact_id"
            ).fetchall()
            extent_rows = connection.execute(
                "SELECT artifact_id, spatial_crs, min_x, min_y, max_x, max_y, temporal_start, temporal_end "
                "FROM earth_memory_spatiotemporal ORDER BY artifact_id"
            ).fetchall()
            revision_state = connection.execute(
                "SELECT artifact_count, accumulator FROM earth_memory_revision_state "
                "WHERE singleton = 1"
            ).fetchone()
            variable_rows = connection.execute(
                "SELECT artifact_id, canonical_variable FROM earth_memory_variables "
                "ORDER BY artifact_id, canonical_variable"
            ).fetchall()
            ngram_rows = connection.execute(
                "SELECT artifact_id, ngram FROM earth_memory_ngrams "
                "ORDER BY artifact_id, ngram"
            ).fetchall()
            connection.execute("COMMIT")
        expected_sources: list[tuple[str, str]] = []
        checked = 0
        for row in rows:
            checked += 1
            try:
                artifact = _verified_row_artifact(row)
                expected_sources.extend(
                    (artifact.artifact_id, source) for source in artifact.source_artifact_ids
                )
            except (ValueError, TypeError) as exc:
                errors.append(f"artifact {row['artifact_id']}: {exc}")
        actual_sources = [(row["artifact_id"], row["source_artifact_id"]) for row in indexed_sources]
        if sorted(expected_sources) != actual_sources:
            errors.append("source relationship index does not match immutable artifact records")
        expected_extents = []
        for row in rows:
            try:
                artifact = _verified_row_artifact(row)
            except (ValueError, TypeError):
                continue
            expected_extents.append((artifact.artifact_id, *_spatiotemporal_values(artifact)))
        actual_extents = [
            (row["artifact_id"], row["spatial_crs"], row["min_x"], row["min_y"],
             row["max_x"], row["max_y"], row["temporal_start"], row["temporal_end"])
            for row in extent_rows
        ]
        if expected_extents != actual_extents:
            errors.append("spatiotemporal index does not match immutable artifact payloads")
        expected_variables = []
        for row in rows:
            try:
                artifact = _verified_row_artifact(row)
            except (ValueError, TypeError):
                continue
            expected_variables.extend(
                (artifact.artifact_id, variable)
                for variable in sorted(_canonical_variable_names(artifact))
            )
        actual_variables = [
            (row["artifact_id"], row["canonical_variable"])
            for row in variable_rows
        ]
        if expected_variables != actual_variables:
            errors.append("canonical variable index does not match immutable artifact payloads")
        expected_ngrams = []
        for row in rows:
            try:
                artifact = _verified_row_artifact(row)
            except (ValueError, TypeError):
                continue
            expected_ngrams.extend(
                (artifact.artifact_id, ngram)
                for ngram in _artifact_search_ngrams(artifact)
            )
        actual_ngrams = [(row["artifact_id"], row["ngram"]) for row in ngram_rows]
        if expected_ngrams != actual_ngrams:
            errors.append("search n-gram index does not match immutable artifact records")
        expected_revision = _index_revision(
            (row["artifact_id"], row["record_sha256"]) for row in revision_rows
        )
        if revision_state is None or expected_revision != _revision_from_state(
            revision_state["artifact_count"], int(revision_state["accumulator"], 16)
        ):
            errors.append("revision state does not match immutable artifact records")
        return EarthMemoryIntegrityReport(
            repository=str(self.path), status="healthy" if not errors else "corrupt",
            artifacts_checked=checked,
            index_revision=expected_revision,
            errors=tuple(errors),
        )


def artifact_from_payload(
    *, artifact_id: str, artifact_type: MemoryArtifactType,
    payload: Any, indexed_at: str, investigation_id: str | None = None,
    mission_id: str | None = None, method_id: str | None = None,
    method_version: str | None = None, source_artifact_ids: Iterable[str] = (),
    observed_at: str | None = None, metadata: dict[str, Any] | None = None,
) -> EarthMemoryArtifact:
    """Build a stable searchable artifact preserving the full JSON payload."""
    serialized = payload.model_dump(mode="python") if hasattr(payload, "model_dump") else payload
    serialized = _json_safe(serialized)
    payload_document = serialized if isinstance(serialized, dict) else {"value": serialized}
    encoded = _canonical_json(payload_document)
    return EarthMemoryArtifact(
        artifact_id=artifact_id, artifact_type=artifact_type,
        investigation_id=investigation_id, mission_id=mission_id,
        method_id=method_id, method_version=method_version,
        source_artifact_ids=tuple(sorted(set(source_artifact_ids))),
        observed_at=observed_at, indexed_at=indexed_at,
        payload_sha256=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        search_text=encoded, payload=payload_document,
        metadata=metadata or {},
    )


def _json_safe(value: Any) -> Any:
    """Canonicalize supported values without memory-address repr fallbacks."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Earth Memory cannot index non-finite numeric values")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [_json_safe(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(
            item, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ))
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    # Preserve the fact that a runtime-only object existed; do not pretend its
    # content has been archived in a reproducible form.
    return {"$unserialized_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def _artifact_record_digest(artifact: EarthMemoryArtifact) -> str:
    encoded = _canonical_json(artifact.model_dump(mode="json"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _spatiotemporal_values(artifact: EarthMemoryArtifact) -> tuple[Any, ...]:
    """Return explicitly declared source extents; never reproject or infer them."""
    payload = artifact.payload
    spatial_crs = None
    bounds = None
    if artifact.artifact_type == "observation":
        spatial_crs = payload.get("crs")
        bounds = _valid_bbox(payload.get("bbox"))
        if bounds is None and spatial_crs:
            bounds = _geometry_bounds(payload.get("geometry"))
    elif artifact.artifact_type == "earth_object":
        spatial_crs = payload.get("crs")
        bounds = _geometry_bounds(payload.get("geometry")) if spatial_crs else None
    elif artifact.artifact_type in {"observation_stack", "temporal_difference"}:
        spatial_crs = payload.get("spatial_support_crs")
        bounds = (
            _geometry_bounds(payload.get("spatial_support_geometry"))
            if spatial_crs else None
        )
    if not spatial_crs or bounds is None:
        spatial_crs = None
        bounds = (None, None, None, None)

    start = end = None
    if artifact.artifact_type == "observation":
        extent = payload.get("temporal_extent")
        if isinstance(extent, dict) and extent.get("start") and extent.get("end"):
            start, end = extent["start"], extent["end"]
        elif payload.get("observed_at"):
            start = end = payload["observed_at"]
    elif artifact.artifact_type == "earth_object":
        extent = payload.get("temporal_validity")
        if isinstance(extent, dict) and extent.get("start") and extent.get("end"):
            start, end = extent["start"], extent["end"]
    elif artifact.artifact_type == "observation_stack":
        members = payload.get("members", ())
        times = [
            _canonical_timestamp(item.get("observed_at"))
            for item in members if isinstance(item, dict)
        ]
        if len(times) == len(members) and len(times) >= 2 and all(times):
            start, end = min(times), max(times)
    elif artifact.artifact_type == "temporal_difference":
        earlier = payload.get("earlier")
        later = payload.get("later")
        if isinstance(earlier, dict) and isinstance(later, dict):
            start, end = earlier.get("observed_at"), later.get("observed_at")
    if start is not None and end is not None:
        start, end = _canonical_timestamp(start), _canonical_timestamp(end)
    else:
        start = end = None
    return (spatial_crs, *bounds, start, end)


def _valid_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) not in {4, 6}:
        return None
    positions = (0, 1, 3, 4) if len(value) == 6 else (0, 1, 2, 3)
    try:
        coordinates = tuple(float(value[index]) for index in positions)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in coordinates):
        return None
    min_x, min_y, max_x, max_y = coordinates
    return coordinates if min_x <= max_x and min_y <= max_y else None


def _geometry_bounds(geometry: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(geometry, dict):
        return None
    points: list[tuple[float, float]] = []

    def visit(value: Any) -> None:
        if not isinstance(value, (tuple, list)):
            return
        if len(value) >= 2 and all(
            isinstance(item, (int, float)) and math.isfinite(item) for item in value[:2]
        ):
            points.append((float(value[0]), float(value[1])))
            return
        for child in value:
            visit(child)

    visit(geometry.get("coordinates"))
    if not points:
        return None
    xs, ys = zip(*points)
    return (min(xs), min(ys), max(xs), max(ys))


def _canonical_timestamp(value: Any) -> str | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _matches_spatiotemporal_query(
    artifact: EarthMemoryArtifact, query: EarthMemoryQuery
) -> bool:
    spatial_crs, min_x, min_y, max_x, max_y, start, end = _spatiotemporal_values(artifact)
    if query.spatial_bbox is not None:
        if spatial_crs != query.spatial_crs or min_x is None:
            return False
        query_min_x, query_min_y, query_max_x, query_max_y = query.spatial_bbox
        if min_x > query_max_x or max_x < query_min_x or min_y > query_max_y or max_y < query_min_y:
            return False
    if query.temporal_start is not None:
        if start is None or end is None:
            return False
        if start > _canonical_timestamp(query.temporal_end) or end < _canonical_timestamp(query.temporal_start):
            return False
    return True


def _write_spatiotemporal_index(
    connection: sqlite3.Connection, artifact: EarthMemoryArtifact
) -> None:
    connection.execute(
        "INSERT INTO earth_memory_spatiotemporal(artifact_id, spatial_crs, min_x, min_y, max_x, max_y, temporal_start, temporal_end) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact.artifact_id, *_spatiotemporal_values(artifact)),
    )


def _canonical_variable_names(artifact: EarthMemoryArtifact) -> set[str]:
    names: set[str] = set()
    declared = artifact.metadata.get("canonical_variables", ())
    if isinstance(declared, (list, tuple, set, frozenset)):
        names.update(
            value.strip().casefold()
            for value in declared
            if isinstance(value, str) and value.strip()
        )
    for container in (artifact.metadata, artifact.payload):
        single = container.get("canonical_variable")
        if isinstance(single, str) and single.strip():
            names.add(single.strip().casefold())
    variable_key = artifact.payload.get("variable_key")
    if isinstance(variable_key, str) and variable_key.startswith("canonical:"):
        canonical = variable_key.removeprefix("canonical:").strip()
        if canonical:
            names.add(canonical.casefold())
    for field in ("canonical_measurements", "measurements"):
        measurements = artifact.payload.get(field, ())
        if isinstance(measurements, list):
            names.update(
                value["canonical_variable"].strip().casefold()
                for value in measurements
                if isinstance(value, dict)
                and value.get("semantic_status") == "resolved"
                and isinstance(value.get("canonical_variable"), str)
                and value["canonical_variable"].strip()
            )
    return names


def _write_canonical_variable_index(
    connection: sqlite3.Connection, artifact: EarthMemoryArtifact
) -> None:
    connection.executemany(
        "INSERT INTO earth_memory_variables(artifact_id, canonical_variable) VALUES (?, ?)",
        (
            (artifact.artifact_id, variable)
            for variable in sorted(_canonical_variable_names(artifact))
        ),
    )


def _artifact_search_ngrams(artifact: EarthMemoryArtifact) -> tuple[str, ...]:
    text = _search_haystack(artifact)
    return tuple(sorted({text[index : index + 3] for index in range(len(text) - 2)}))


def _search_query_ngrams(terms: tuple[str, ...]) -> tuple[str, ...]:
    grams = {
        term[index : index + 3]
        for term in terms
        if len(term) >= 3
        for index in range(len(term) - 2)
    }
    if not grams or len(grams) > _MAX_INDEXED_SEARCH_NGRAMS:
        return ()
    return tuple(sorted(grams))


def _write_search_ngram_index(
    connection: sqlite3.Connection, artifact: EarthMemoryArtifact
) -> None:
    connection.executemany(
        "INSERT INTO earth_memory_ngrams(artifact_id, ngram) VALUES (?, ?)",
        ((artifact.artifact_id, ngram) for ngram in _artifact_search_ngrams(artifact)),
    )


def _index_revision(records: Iterable[tuple[str, str]]) -> str:
    count = 0
    accumulator = 0
    for artifact_id, record_sha256 in records:
        count += 1
        accumulator = (
            accumulator + _revision_entry_value(artifact_id, record_sha256)
        ) % _REVISION_MODULUS
    return _revision_from_state(count, accumulator)


def _revision_entry_value(artifact_id: str, record_sha256: str) -> int:
    identity = f"{artifact_id}\0{record_sha256.lower()}".encode("utf-8")
    return int.from_bytes(hashlib.sha512(identity).digest(), "big") % _REVISION_MODULUS


def _revision_from_state(artifact_count: int, accumulator: int) -> str:
    revision_state = (
        f"satquery-earth-memory:{artifact_count}:"
        f"{accumulator % _REVISION_MODULUS:0{_REVISION_ACCUMULATOR_WIDTH}x}"
    )
    return hashlib.sha256(revision_state.encode("ascii")).hexdigest()


def _query_fingerprint(query: EarthMemoryQuery) -> str:
    query_payload = query.model_dump(mode="json", exclude={"cursor", "limit"})
    canonical_query = json.dumps(
        query_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical_query.encode("utf-8")).hexdigest()


def _encode_memory_cursor(
    revision: str, after_artifact_id: str, query: EarthMemoryQuery
) -> str:
    payload = json.dumps(
        {
            "version": 1,
            "revision": revision,
            "after_artifact_id": after_artifact_id,
            "query_sha256": _query_fingerprint(query),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_memory_cursor(
    cursor: str | None, revision: str, query: EarthMemoryQuery
) -> str | None:
    if cursor is None:
        return None
    try:
        encoded = cursor.encode("ascii")
        if not encoded or any(
            char not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for char in encoded
        ):
            raise ValueError
        payload = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        decoded = json.loads(payload)
        if (
            not isinstance(decoded, dict)
            or type(decoded.get("version")) is not int
            or decoded["version"] != 1
            or not isinstance(decoded.get("revision"), str)
            or not isinstance(decoded.get("after_artifact_id"), str)
            or not decoded["after_artifact_id"]
            or not isinstance(decoded.get("query_sha256"), str)
        ):
            raise ValueError
    except (UnicodeEncodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise EarthMemoryCursorError("Earth Memory cursor is malformed or unsupported") from exc
    if decoded["revision"] != revision:
        raise StaleEarthMemoryCursorError(
            "Earth Memory cursor is stale because the index revision changed"
        )
    if decoded["query_sha256"] != _query_fingerprint(query):
        raise EarthMemoryCursorError("Earth Memory cursor does not match this search query")
    return decoded["after_artifact_id"]


def _search_haystack(artifact: EarthMemoryArtifact) -> str:
    return f"{artifact.search_text} {artifact.artifact_id} {artifact.payload_sha256}".casefold()


def _matches_canonical_variable(
    artifact: EarthMemoryArtifact, canonical_variable: str
) -> bool:
    """Match only declared canonical variable identifiers, not fuzzy aliases."""
    wanted = canonical_variable.strip().casefold()
    return bool(wanted) and wanted in _canonical_variable_names(artifact)


def _decode_artifact(encoded: str) -> EarthMemoryArtifact:
    return EarthMemoryArtifact.model_validate_json(encoded)


def _verified_row_artifact(row: sqlite3.Row) -> EarthMemoryArtifact:
    artifact = _decode_artifact(row["artifact_json"])
    if _artifact_record_digest(artifact) != row["record_sha256"]:
        raise ValueError("stored Earth Memory record digest does not match its content")
    if row["search_index"] != _search_haystack(artifact):
        raise ValueError("stored Earth Memory search index does not match its artifact")
    return artifact
