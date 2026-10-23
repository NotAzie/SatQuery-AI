import pytest
from pydantic import ValidationError as PydanticValidationError
from satquery.errors import ValidationError as SatQueryValidationError
from satquery.platform.contracts import (
    EarthQuery,
    Evidence,
    ExecutionPlan,
    InvestigationStatus,
    Mission,
    Observation,
    Task,
)
from satquery.platform.investigations import (
    InMemoryInvestigationRepository,
    InvestigationService,
)


def test_execution_plan_rejects_cycles_and_unknown_dependencies():
    with pytest.raises(PydanticValidationError, match="dependency cycle"):
        ExecutionPlan(
            tasks=(
                Task(task_id="first", handler="work", depends_on=("second",)),
                Task(task_id="second", handler="work", depends_on=("first",)),
            )
        )

    with pytest.raises(PydanticValidationError, match="unknown tasks"):
        ExecutionPlan(
            tasks=(Task(task_id="first", handler="work", depends_on=("missing",)),)
        )


def test_retry_requires_explicit_idempotency_declaration():
    with pytest.raises(PydanticValidationError, match="retry_safe"):
        Task(task_id="unsafe", handler="work", max_attempts=2)


def test_contract_nested_metadata_is_immutable_and_remains_json_serializable():
    observation = Observation(
        provenance={"source": {"values": [1, {"name": "original"}]}},
    )

    with pytest.raises(TypeError, match="immutable"):
        observation.provenance["new"] = "value"
    with pytest.raises(TypeError, match="immutable"):
        observation.provenance["source"]["values"].append(2)
    with pytest.raises(TypeError, match="immutable"):
        observation.provenance["source"]["values"][1]["name"] = "changed"

    assert observation.model_dump(mode="json")["provenance"] == {
        "source": {"values": [1, {"name": "original"}]}
    }
    copied = observation.model_copy(update={"provenance": {"copy": [3]}})
    with pytest.raises(TypeError, match="immutable"):
        copied.provenance["copy"].append(4)


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Point", "coordinates": [float("nan"), 1]},
        {"type": "LineString", "coordinates": [[0, 0]]},
        {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [2, 2]]],
        },
        {"type": "Unknown", "coordinates": []},
    ],
)
def test_earth_query_rejects_malformed_geojson_geometry(geometry):
    with pytest.raises(PydanticValidationError, match="structurally valid GeoJSON"):
        EarthQuery(geometry=geometry)


def test_earth_query_applies_geographic_bounds_only_for_declared_geographic_crs():
    EarthQuery(
        geometry={"type": "Point", "coordinates": [500_000, 4_500_000]},
        crs="EPSG:32631",
    )

    with pytest.raises(PydanticValidationError, match="structurally valid GeoJSON"):
        EarthQuery(
            geometry={"type": "Point", "coordinates": [500_000, 4_500_000]},
            crs="OGC:CRS84",
        )


def test_investigation_lifecycle_tracks_evidence_results_and_report():
    mission = Mission(name="Test mission", objective="Verify lifecycle")
    service = InvestigationService(InMemoryInvestigationRepository())
    investigation = service.create(mission)
    assert investigation.status == InvestigationStatus.PENDING

    investigation = service.start(investigation.investigation_id)
    evidence = Evidence(
        investigation_id=investigation.investigation_id,
        claim="A reproducible test observation",
    )
    investigation = service.add_evidence(investigation.investigation_id, evidence)
    investigation = service.add_result(investigation.investigation_id, "result-1")
    investigation = service.complete(investigation.investigation_id, "Report contents")

    assert investigation.status == InvestigationStatus.COMPLETED
    assert investigation.evidence_ids == (evidence.evidence_id,)
    assert investigation.result_ids == ("result-1",)
    assert investigation.report == "Report contents"
    assert investigation.started_at is not None
    assert investigation.finished_at is not None


def test_investigation_rejects_evidence_from_another_investigation():
    service = InvestigationService(InMemoryInvestigationRepository())
    first = service.start(service.create(Mission(name="one", objective="one")).investigation_id)
    other = service.start(service.create(Mission(name="two", objective="two")).investigation_id)
    evidence = Evidence(investigation_id=other.investigation_id, claim="Other evidence")

    with pytest.raises(SatQueryValidationError, match="different investigation"):
        service.add_evidence(first.investigation_id, evidence)
