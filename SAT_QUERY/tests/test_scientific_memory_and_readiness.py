import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from satquery.platform.capabilities import build_earth_capability_matrix
from satquery.platform.config import PlatformConfig
from satquery.platform.contracts import (
    DatasetReference,
    EarthObject,
    EarthQuery,
    Observation,
    ObservationStack,
    ObservationStackMember,
)
from satquery.platform.earth_memory import (
    EarthMemoryQuery,
    InMemoryEarthMemory,
    SQLiteEarthMemory,
    artifact_from_payload,
)
from satquery.platform.method_readiness import (
    AdaptiveInvestigationRefiner,
    EvidenceSufficiencyEngine,
)
from satquery.platform.runtime import PlatformRuntime
from satquery.platform.scientific_library import documented_reference_methods
from satquery.platform.spatiotemporal import ConsecutiveTemporalDifferenceEngine


@pytest.fixture
def sqlite_database_path():
    path = Path(__file__).resolve().parent / f".earth-memory-{uuid4().hex}.sqlite"
    try:
        yield path
    finally:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{path}{suffix}")
            if candidate.exists():
                candidate.unlink()


def test_reference_library_is_cited_but_does_not_claim_local_executability():
    methods = documented_reference_methods()
    assert {item.domain for item in methods} == {
        "hydrology", "drought", "wildfire", "land_cover", "cryosphere",
        "vegetation", "urban_analysis",
    }
    for method in methods:
        assert method.publication.doi or method.publication.uri
        assert method.validation_evidence.evidence_references
        assert method.assumptions and method.applicability and method.limitations
        assert method.required_variables and method.required_datasets
        assert method.required_modalities and method.uncertainty_model
        assert method.benchmark_reference
        assert method.benchmark_status == "identified_not_materialized"
        assert method.benchmark_suite_id is None
        assert method.reproducibility_requirements
        assert method.implementation_status == "reference_catalog_only"
        assert method.executable_method_id is None


def test_sufficiency_keeps_unknown_benchmark_dataset_and_implementation_unknown():
    method = documented_reference_methods()[1]
    observation = Observation(
        observation_id="rain-1",
        dataset=DatasetReference(connector_id="fixture", dataset_id="rain", version="v1"),
        measured_variables={"precipitation": {"value": 10, "unit": "mm"}},
        modalities=("atmospheric",),
        provenance={"source_record": "record-1"},
        uncertainty={},
    )
    matrix = build_earth_capability_matrix((), ())
    result = EvidenceSufficiencyEngine().assess(
        method, (observation,), EarthQuery(), matrix,
    )
    assert result.status == "insufficient"
    assert result.checks[0].status == "satisfied"
    assert next(item for item in result.checks if item.criterion == "provenance").status == "satisfied"
    assert next(item for item in result.checks if item.criterion == "benchmark:not_registered").status == "unknown"
    assert next(item for item in result.checks if item.criterion == "required_datasets").status == "unknown"
    assert next(item for item in result.checks if item.criterion == "registered_certified_implementation").status == "unsatisfied"


def test_missing_observation_recommendation_is_deterministic_and_never_executes():
    method = documented_reference_methods()[1]
    result = EvidenceSufficiencyEngine().assess(
        method, (), EarthQuery(), build_earth_capability_matrix((), ()),
    )
    first = AdaptiveInvestigationRefiner().recommend((result,), (method,), build_earth_capability_matrix((), ()))
    second = AdaptiveInvestigationRefiner().recommend((result,), (method,), build_earth_capability_matrix((), ()))
    assert first == second
    assert first
    assert all(item.acquisition_status == "recommended_only_not_executed" for item in first)
    assert any(item.missing_observation == "measurement:precipitation" for item in first)


def test_earth_memory_search_is_deterministic_and_artifact_ids_are_immutable():
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    artifact = artifact_from_payload(
        artifact_id="investigation:i-1", artifact_type="investigation",
        payload={"question": "river flooding after rainfall"}, indexed_at=timestamp,
        investigation_id="i-1", mission_id="m-1",
    )
    memory = InMemoryEarthMemory((artifact,))
    query = EarthMemoryQuery(text="flooding rainfall", mission_id="m-1")
    assert memory.search(query) == memory.search(query)
    assert memory.search(query).total == 1
    changed = artifact_from_payload(
        artifact_id="investigation:i-1", artifact_type="investigation",
        payload={"question": "different payload"}, indexed_at=timestamp,
        investigation_id="i-1", mission_id="m-1",
    )
    with pytest.raises(ValueError, match="immutable"):
        memory.upsert(changed)

    same_payload_different_relationship = artifact.model_copy(
        update={"source_artifact_ids": ("plan:p-2",)}
    )
    with pytest.raises(ValueError, match="immutable"):
        memory.upsert(same_payload_different_relationship)


def test_earth_memory_filters_exact_canonical_variables_across_artifact_types(
    sqlite_database_path,
):
    indexed_at = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    artifacts = (
        artifact_from_payload(
            artifact_id="observation:ndvi",
            artifact_type="observation",
            payload={
                "canonical_measurements": [
                    {
                        "canonical_variable": "ndvi",
                        "semantic_status": "resolved",
                        "source_variable": "NDVI",
                    }
                ]
            },
            indexed_at=indexed_at,
        ),
        artifact_from_payload(
            artifact_id="stack:ndvi",
            artifact_type="observation_stack",
            payload={"variable_key": "canonical:ndvi", "canonical_variable": "ndvi"},
            indexed_at=indexed_at,
        ),
        artifact_from_payload(
            artifact_id="difference:ndvi",
            artifact_type="temporal_difference",
            payload={"canonical_variable": "ndvi"},
            indexed_at=indexed_at,
        ),
        artifact_from_payload(
            artifact_id="earth-object:ndvi-feature",
            artifact_type="earth_object",
            payload={
                "measurements": [
                    {
                        "canonical_variable": "ndvi",
                        "semantic_status": "resolved",
                        "source_variable": "NDVI",
                    }
                ]
            },
            indexed_at=indexed_at,
        ),
        artifact_from_payload(
            artifact_id="observation:unresolved-ndvi",
            artifact_type="observation",
            payload={
                "canonical_measurements": [
                    {
                        "canonical_variable": "ndvi",
                        "semantic_status": "unresolved",
                        "source_variable": "NDVI",
                    }
                ]
            },
            indexed_at=indexed_at,
        ),
    )
    memory = InMemoryEarthMemory(artifacts)
    persistent = SQLiteEarthMemory(sqlite_database_path)
    for artifact in artifacts:
        persistent.upsert(artifact)

    query = EarthMemoryQuery(canonical_variable="NDVI")
    memory_result = memory.search(query)
    assert memory_result == persistent.search(query)
    assert {item.artifact_id for item in memory_result.artifacts} == {
        "observation:ndvi",
        "stack:ndvi",
        "difference:ndvi",
        "earth-object:ndvi-feature",
    }
    assert memory.search(EarthMemoryQuery(canonical_variable="normalized_difference_vegetation_index")).total == 0
    assert persistent.verify_integrity().status == "healthy"

    first_query = EarthMemoryQuery(canonical_variable="ndvi", limit=2)
    first_memory_page = memory.search(first_query)
    first_sqlite_page = persistent.search(first_query)
    assert first_memory_page == first_sqlite_page
    assert first_memory_page.total == 4
    assert first_memory_page.next_cursor
    second_query = first_query.model_copy(update={"cursor": first_memory_page.next_cursor})
    second_memory_page = memory.search(second_query)
    second_sqlite_page = persistent.search(second_query)
    assert second_memory_page == second_sqlite_page
    assert second_memory_page.total == 2
    assert second_memory_page.next_cursor is None
    assert not (
        {item.artifact_id for item in first_memory_page.artifacts}
        & {item.artifact_id for item in second_memory_page.artifacts}
    )
    with pytest.raises(ValueError, match="does not match"):
        memory.search(second_query.model_copy(update={"text": "different filters"}))
    for store in (memory, persistent):
        store.upsert(artifact_from_payload(
            artifact_id="observation:ndvi-later",
            artifact_type="observation",
            payload={"canonical_variable": "ndvi"},
            indexed_at=indexed_at,
        ))
        with pytest.raises(ValueError, match="stale"):
            store.search(second_query)
    with pytest.raises(ValueError, match="malformed"):
        memory.search(first_query.model_copy(update={"cursor": "not-a-cursor"}))


def test_earth_memory_canonicalizes_unordered_values_and_rejects_nonfinite_numbers():
    indexed_at = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    first = artifact_from_payload(
        artifact_id="fixture:set", artifact_type="evidence",
        payload={"values": {"b", "a"}}, indexed_at=indexed_at,
    )
    second = artifact_from_payload(
        artifact_id="fixture:set", artifact_type="evidence",
        payload={"values": {"a", "b"}}, indexed_at=indexed_at,
    )
    assert first.payload_sha256 == second.payload_sha256
    with pytest.raises(ValueError, match="non-finite"):
        artifact_from_payload(
            artifact_id="fixture:nan", artifact_type="evidence",
            payload={"value": float("nan")}, indexed_at=indexed_at,
        )


def test_sqlite_literal_search_preserves_unicode_casefold_semantics(sqlite_database_path):
    indexed_at = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    artifact = artifact_from_payload(
        artifact_id="evidence:unicode", artifact_type="evidence",
        payload={"description": "Straße İZMİR"}, indexed_at=indexed_at,
    )
    memory = InMemoryEarthMemory((artifact,))
    persistent = SQLiteEarthMemory(sqlite_database_path)
    persistent.upsert(artifact)
    query = EarthMemoryQuery(text="STRASSE İZMİR")
    assert persistent.search(query) == memory.search(query)
    assert persistent.search(query).total == 1


def test_sqlite_earth_memory_migrates_v5_search_ngram_index(sqlite_database_path):
    artifact = artifact_from_payload(
        artifact_id="evidence:migrate-search",
        artifact_type="evidence",
        payload={"finding": "monsoon rainfall variability"},
        indexed_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    )
    store = SQLiteEarthMemory(sqlite_database_path)
    store.upsert(artifact)
    connection = sqlite3.connect(sqlite_database_path)
    try:
        connection.execute("DROP TABLE earth_memory_ngrams")
        connection.execute("UPDATE earth_memory_schema SET version = 5 WHERE singleton = 1")
        connection.commit()
    finally:
        connection.close()

    migrated = SQLiteEarthMemory(sqlite_database_path)
    result = migrated.search(EarthMemoryQuery(text="MONSOON rainfall"))
    assert tuple(item.artifact_id for item in result.artifacts) == (artifact.artifact_id,)
    assert migrated.verify_integrity().status == "healthy"

    connection = sqlite3.connect(sqlite_database_path)
    try:
        connection.execute(
            "DELETE FROM earth_memory_ngrams WHERE artifact_id = ? AND ngram = 'rai'",
            (artifact.artifact_id,),
        )
        connection.commit()
    finally:
        connection.close()
    assert migrated.verify_integrity().status == "corrupt"


def test_sqlite_earth_memory_persists_immutable_artifacts_and_matches_memory(sqlite_database_path):
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    artifacts = (
        artifact_from_payload(
            artifact_id="plan:p-1", artifact_type="plan",
            payload={"question": "river flood after rain"}, indexed_at=timestamp,
            investigation_id="i-1", source_artifact_ids=("investigation:i-1",),
        ),
        artifact_from_payload(
            artifact_id="observation:o-1", artifact_type="observation",
            payload={"water_level": 2.1}, indexed_at=timestamp,
            investigation_id="i-1", mission_id="m-1",
        ),
    )
    in_memory = InMemoryEarthMemory(artifacts)
    database_path = sqlite_database_path
    persistent = SQLiteEarthMemory(database_path)
    for artifact in reversed(artifacts):
        persistent.upsert(artifact)

    query = EarthMemoryQuery(text="river flood", investigation_id="i-1", limit=1)
    assert persistent.search(query) == in_memory.search(query)
    assert persistent.search(EarthMemoryQuery(source_artifact_id="investigation:i-1")).total == 1
    assert persistent.verify_integrity().status == "healthy"

    reopened = SQLiteEarthMemory(database_path)
    assert reopened.all() == tuple(sorted(artifacts, key=lambda item: item.artifact_id))
    assert reopened.search(query).index_revision == in_memory.search(query).index_revision
    changed = artifacts[0].model_copy(update={"metadata": {"changed": True}})
    with pytest.raises(ValueError, match="immutable"):
        reopened.upsert(changed)


def test_sqlite_earth_memory_detects_corrupt_search_index(sqlite_database_path):
    artifact = artifact_from_payload(
        artifact_id="evidence:e-1", artifact_type="evidence",
        payload={"finding": "coastal inundation"},
        indexed_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    )
    memory = SQLiteEarthMemory(sqlite_database_path)
    memory.upsert(artifact)
    connection = sqlite3.connect(memory.path)
    try:
        connection.execute(
            "UPDATE earth_memory_artifacts SET search_index = ? WHERE artifact_id = ?",
            ("wrong", artifact.artifact_id),
        )
        connection.commit()
    finally:
        connection.close()
    report = memory.verify_integrity()
    assert report.status == "corrupt"
    assert report.artifacts_checked == 1
    with pytest.raises(ValueError, match="search index"):
        memory.search(EarthMemoryQuery(text="coastal"))
    # Structured filters retrieve and verify only their candidate rows. The
    # repository-wide audit remains the explicit way to detect unrelated
    # corruption without forcing every filtered query to deserialize the corpus.
    assert memory.search(EarthMemoryQuery(investigation_id="unrelated")).total == 0
    assert memory.verify_integrity().status == "corrupt"


def test_earth_memory_filters_are_spatiotemporal_deterministic_and_crs_scoped(sqlite_database_path):
    start = datetime(2025, 3, 1, tzinfo=timezone.utc)
    end = datetime(2025, 3, 31, 23, 59, tzinfo=timezone.utc)
    artifacts = (
        artifact_from_payload(
            artifact_id="observation:inside", artifact_type="observation",
            payload=Observation(
                observation_id="inside", bbox=(-2, -2, 2, 2), crs="OGC:CRS84",
                temporal_extent={"start": start, "end": end},
            ), indexed_at=start.isoformat(),
        ),
        artifact_from_payload(
            artifact_id="observation:outside", artifact_type="observation",
            payload=Observation(
                observation_id="outside", bbox=(20, 20, 25, 25), crs="OGC:CRS84",
                observed_at=end,
            ), indexed_at=start.isoformat(),
        ),
        artifact_from_payload(
            artifact_id="observation:unknown", artifact_type="observation",
            payload=Observation(observation_id="unknown", bbox=(-1, -1, 1, 1)),
            indexed_at=start.isoformat(),
        ),
        artifact_from_payload(
            artifact_id="earth-object:basin", artifact_type="earth_object",
            payload=EarthObject(
                object_id="basin", object_type="earth:Watershed",
                geometry={"type": "Polygon", "coordinates": [[
                    [-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1],
                ]]},
                crs="OGC:CRS84", temporal_validity={"start": start, "end": end},
                source_observation_ids=("inside",),
            ), indexed_at=start.isoformat(),
        ),
    )
    memory = InMemoryEarthMemory(artifacts)
    persistent = SQLiteEarthMemory(sqlite_database_path)
    for artifact in artifacts:
        persistent.upsert(artifact)

    query = EarthMemoryQuery(
        spatial_bbox=(-1, -1, 1, 1), spatial_crs="OGC:CRS84",
        temporal_start=start, temporal_end=end,
    )
    in_memory_result = memory.search(query)
    assert tuple(item.artifact_id for item in in_memory_result.artifacts) == (
        "earth-object:basin", "observation:inside",
    )
    assert persistent.search(query) == in_memory_result
    assert memory.search(query.model_copy(update={"spatial_crs": "EPSG:3857"})).total == 0
    assert memory.search(query.model_copy(update={"temporal_start": end, "temporal_end": end})).total == 2
    assert persistent.verify_integrity().status == "healthy"


def test_earth_memory_spatiotemporal_query_requires_explicit_complete_bounds():
    with pytest.raises(ValueError, match="supplied together"):
        EarthMemoryQuery(spatial_bbox=(0, 0, 1, 1))
    with pytest.raises(ValueError, match="supplied together"):
        EarthMemoryQuery(temporal_start=datetime(2025, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="timezone-aware"):
        EarthMemoryQuery(
            temporal_start=datetime.fromisoformat("2025-01-01T00:00:00"),
            temporal_end=datetime.fromisoformat("2025-01-02T00:00:00"),
        )


def test_sqlite_earth_memory_migrates_v1_artifact_extent_index(sqlite_database_path):
    artifact = artifact_from_payload(
        artifact_id="observation:migrate", artifact_type="observation",
        payload=Observation(
            observation_id="migrate", bbox=(4, 5, 6, 7), crs="OGC:CRS84",
            observed_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        ), indexed_at="2025-06-01T00:00:00+00:00",
    )
    connection = sqlite3.connect(sqlite_database_path)
    try:
        connection.executescript(
            "CREATE TABLE earth_memory_schema (singleton INTEGER PRIMARY KEY, version INTEGER NOT NULL);"
            "INSERT INTO earth_memory_schema(singleton, version) VALUES (1, 1);"
            "CREATE TABLE earth_memory_artifacts (artifact_id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL, "
            "investigation_id TEXT, mission_id TEXT, method_id TEXT, method_version TEXT, indexed_at TEXT NOT NULL, "
            "payload_sha256 TEXT NOT NULL, record_sha256 TEXT NOT NULL, search_index TEXT NOT NULL, artifact_json TEXT NOT NULL);"
            "CREATE TABLE earth_memory_sources (artifact_id TEXT NOT NULL, source_artifact_id TEXT NOT NULL, "
            "PRIMARY KEY (artifact_id, source_artifact_id), FOREIGN KEY (artifact_id) REFERENCES earth_memory_artifacts(artifact_id) ON DELETE CASCADE);"
        )
        connection.execute(
            "INSERT INTO earth_memory_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact.artifact_id, artifact.artifact_type, artifact.investigation_id,
             artifact.mission_id, artifact.method_id, artifact.method_version, artifact.indexed_at,
             artifact.payload_sha256, hashlib.sha256(
                 json.dumps(artifact.model_dump(mode="json"), sort_keys=True,
                 separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
             ).hexdigest(),
             f"{artifact.search_text} {artifact.artifact_id} {artifact.payload_sha256}".casefold(),
             artifact.model_dump_json()),
        )
        connection.commit()
    finally:
        connection.close()

    migrated = SQLiteEarthMemory(sqlite_database_path)
    result = migrated.search(EarthMemoryQuery(
        spatial_bbox=(5, 6, 5, 6), spatial_crs="OGC:CRS84",
        temporal_start=datetime(2025, 6, 1, tzinfo=timezone.utc),
        temporal_end=datetime(2025, 6, 1, tzinfo=timezone.utc),
    ))
    assert tuple(item.artifact_id for item in result.artifacts) == (artifact.artifact_id,)
    assert migrated.verify_integrity().status == "healthy"


def test_sqlite_earth_memory_migrates_v3_canonical_variable_index_and_verifies_it(
    sqlite_database_path,
):
    indexed_at = datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat()
    artifact = artifact_from_payload(
        artifact_id="observation:canonical-water-level",
        artifact_type="observation",
        payload={
            "canonical_measurements": [
                {
                    "canonical_variable": "water_level",
                    "semantic_status": "resolved",
                }
            ]
        },
        indexed_at=indexed_at,
    )
    store = SQLiteEarthMemory(sqlite_database_path)
    store.upsert(artifact)
    connection = sqlite3.connect(sqlite_database_path)
    try:
        connection.execute("DELETE FROM earth_memory_variables")
        connection.execute("UPDATE earth_memory_schema SET version = 3 WHERE singleton = 1")
        connection.commit()
    finally:
        connection.close()

    migrated = SQLiteEarthMemory(sqlite_database_path)
    assert migrated.search(EarthMemoryQuery(canonical_variable="water_level")).total == 1
    assert migrated.verify_integrity().status == "healthy"
    connection = sqlite3.connect(sqlite_database_path)
    try:
        connection.execute(
            "DELETE FROM earth_memory_variables WHERE artifact_id = ?",
            (artifact.artifact_id,),
        )
        connection.commit()
    finally:
        connection.close()
    report = migrated.verify_integrity()
    assert report.status == "corrupt"
    assert any("canonical variable index" in error for error in report.errors)


def test_sqlite_earth_memory_detects_corrupt_spatiotemporal_index(sqlite_database_path):
    observed_at = datetime(2025, 7, 1, tzinfo=timezone.utc)
    artifact = artifact_from_payload(
        artifact_id="observation:extent-integrity", artifact_type="observation",
        payload=Observation(
            observation_id="extent-integrity", bbox=(1, 2, 3, 4),
            crs="OGC:CRS84", observed_at=observed_at,
        ), indexed_at=observed_at.isoformat(),
    )
    memory = SQLiteEarthMemory(sqlite_database_path)
    memory.upsert(artifact)
    connection = sqlite3.connect(memory.path)
    try:
        connection.execute(
            "UPDATE earth_memory_spatiotemporal SET max_x = 99 WHERE artifact_id = ?",
            (artifact.artifact_id,),
        )
        connection.commit()
    finally:
        connection.close()
    report = memory.verify_integrity()
    assert report.status == "corrupt"
    assert any("spatiotemporal index" in error for error in report.errors)


def test_temporal_stack_and_difference_are_searchable_by_declared_space_and_time(sqlite_database_path):
    support = {
        "type": "Polygon",
        "coordinates": [[[1, 2], [3, 2], [3, 4], [1, 4], [1, 2]]],
    }
    members = tuple(
        ObservationStackMember(
            observation_id=f"scene-{day}",
            measurement_observation_id=f"measurement-{day}",
            source_id=f"source-{day}",
            dataset=DatasetReference(connector_id="stac", dataset_id="thermal"),
            observed_at=datetime(2025, 1, day, tzinfo=timezone.utc),
            value=value,
            unit="K",
            source_variable="surface_temperature",
            uncertainty={"source": "not-provided"},
            source_measurement_metadata={
                "pixel_support_geometry": support,
                "pixel_support_crs": "OGC:CRS84",
            },
            provenance={"source_item": f"item-{day}"},
        )
        for day, value in ((1, 290.0), (2, 292.0))
    )
    stack = ObservationStack(
        stack_id="stack-thermal-1-2",
        variable_key="canonical:surface_temperature",
        canonical_variable="surface_temperature",
        unit="K",
        spatial_support_geometry=support,
        spatial_support_crs="OGC:CRS84",
        spatial_alignment="exact_pixel_support",
        temporal_alignment="source_acquisition_time",
        members=members,
    )
    diagnostic = ConsecutiveTemporalDifferenceEngine().build((stack,))[0][0]
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat()
    artifacts = (
        artifact_from_payload(
            artifact_id=f"observation-stack:{stack.stack_id}",
            artifact_type="observation_stack", payload=stack, indexed_at=timestamp,
            investigation_id="i-temporal",
        ),
        artifact_from_payload(
            artifact_id=f"temporal-difference:{diagnostic.diagnostic_id}",
            artifact_type="temporal_difference", payload=diagnostic,
            indexed_at=timestamp, investigation_id="i-temporal",
            source_artifact_ids=(f"observation-stack:{stack.stack_id}",),
        ),
    )
    memory = InMemoryEarthMemory(artifacts)
    persistent = SQLiteEarthMemory(sqlite_database_path)
    for artifact in artifacts:
        persistent.upsert(artifact)
    query = EarthMemoryQuery(
        investigation_id="i-temporal",
        spatial_bbox=(2, 3, 2, 3),
        spatial_crs="OGC:CRS84",
        temporal_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        temporal_end=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )

    expected = memory.search(query)
    assert tuple(item.artifact_type for item in expected.artifacts) == (
        "observation_stack", "temporal_difference",
    )
    assert persistent.search(query) == expected
    assert persistent.verify_integrity().status == "healthy"


def test_sqlite_v2_migration_rebuilds_temporal_stack_extents(sqlite_database_path):
    support = {
        "type": "Polygon",
        "coordinates": [[[4, 5], [6, 5], [6, 7], [4, 7], [4, 5]]],
    }
    members = tuple(
        ObservationStackMember(
            observation_id=f"old-scene-{day}",
            observed_at=datetime(2025, 2, day, tzinfo=timezone.utc),
            value=float(day), unit="m", source_variable="elevation",
            source_measurement_metadata={
                "pixel_support_geometry": support,
                "pixel_support_crs": "OGC:CRS84",
            },
        )
        for day in (1, 2)
    )
    stack = ObservationStack(
        stack_id="v2-stack", variable_key="canonical:elevation",
        canonical_variable="elevation", unit="m",
        spatial_support_geometry=support, spatial_support_crs="OGC:CRS84",
        spatial_alignment="exact_pixel_support",
        temporal_alignment="source_acquisition_time", members=members,
    )
    artifact = artifact_from_payload(
        artifact_id="observation-stack:v2-stack", artifact_type="observation_stack",
        payload=stack, indexed_at="2025-02-01T00:00:00+00:00",
    )
    memory = SQLiteEarthMemory(sqlite_database_path)
    memory.upsert(artifact)
    connection = sqlite3.connect(memory.path)
    try:
        connection.execute("UPDATE earth_memory_schema SET version = 2 WHERE singleton = 1")
        connection.execute(
            "UPDATE earth_memory_spatiotemporal SET spatial_crs = NULL, min_x = NULL, "
            "min_y = NULL, max_x = NULL, max_y = NULL, temporal_start = NULL, temporal_end = NULL "
            "WHERE artifact_id = ?",
            (artifact.artifact_id,),
        )
        connection.commit()
    finally:
        connection.close()

    migrated = SQLiteEarthMemory(sqlite_database_path)
    result = migrated.search(EarthMemoryQuery(
        spatial_bbox=(5, 6, 5, 6), spatial_crs="OGC:CRS84",
        temporal_start=datetime(2025, 2, 1, tzinfo=timezone.utc),
        temporal_end=datetime(2025, 2, 2, tzinfo=timezone.utc),
    ))
    assert tuple(item.artifact_id for item in result.artifacts) == (artifact.artifact_id,)
    assert migrated.verify_integrity().status == "healthy"


def test_runtime_reopens_persistent_memory_and_seeds_catalog_idempotently(sqlite_database_path):
    config = PlatformConfig.load(environ={
        "SATQUERY_PLATFORM__STORAGE__EARTH_MEMORY_PATH": str(sqlite_database_path),
    })
    first_runtime = PlatformRuntime(config=config)
    first_records = first_runtime.earth_memory.all()
    assert first_records

    second_runtime = PlatformRuntime(config=config)
    assert second_runtime.earth_memory.all() == first_records
    assert second_runtime.earth_memory.verify_integrity().status == "healthy"
