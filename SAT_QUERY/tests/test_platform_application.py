from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import satquery.__main__ as cli
from fastapi.testclient import TestClient
from satquery.api import create_app, set_engine
from satquery.config import get_settings
from satquery.connector_bootstrap import load_configured_connectors
from satquery.orchestrator import SatQueryEngine
from satquery.platform.config import PlatformConfig
from satquery.platform.connectors import PerceptionConnector
from satquery.platform.contracts import (
    ConnectorMetadata,
    DatasetMetadata,
    DatasetReference,
    EarthObjectCandidate,
    EarthQuery,
    ExecutionResult,
    ExecutionStatus,
    Mission,
    Observation,
    ObservationAsset,
    ObservationSearchResult,
    ObservationStack,
    ObservationStackMember,
    PerceptionResult,
    Task,
    TaskExecution,
    TaskStatus,
    utc_now,
)
from satquery.platform.earth_memory import artifact_from_payload
from satquery.platform.earth_objects import (
    EarthObjectExtractionBatch,
    EarthObjectExtractionPipeline,
)
from satquery.platform.intelligence import EvidenceAssessment
from satquery.platform.normalization import SemanticNormalizer
from satquery.platform.raster_objects import RasterCategoricalComponentExtractor
from satquery.platform.reasoning import ScientificReasoningReport
from satquery.platform.runtime import PlatformRuntime
from satquery.platform.scientific_governance import SQLiteAuditTrail
from satquery.schemas import BackendKind, Intent, QueryPlan, QueryResponse


def test_platform_runtime_audit_history_survives_reconstruction(tmp_path):
    audit_path = tmp_path / "audit.sqlite"
    config = PlatformConfig.load(
        environ={}, overrides={"storage": {"audit_path": str(audit_path)}}
    )
    first_runtime = PlatformRuntime(config=config)
    first_runtime.audit_trail.append(
        aggregate_id="investigation-1", event_type="planning", actor="planner",
        payload={"plan_id": "plan-1"},
    )

    restarted_runtime = PlatformRuntime(config=config)
    assert isinstance(restarted_runtime.audit_trail, SQLiteAuditTrail)
    assert restarted_runtime.audit_trail.verify("investigation-1")
    assert len(restarted_runtime.audit_trail.events("investigation-1")) == 1


def test_platform_runtime_restores_method_certification_from_complete_audit(tmp_path):
    from test_scientific_governance import _DatasetLoader, _Runner, _suite

    audit_path = tmp_path / "governance.sqlite"
    config = PlatformConfig.load(
        environ={}, overrides={"storage": {"audit_path": str(audit_path)}}
    )
    first_runtime = PlatformRuntime(config=config)
    suite = _suite()
    registration = first_runtime.method_certifications.register(
        suite.method_id, suite.method_version, implementation_sha256="b" * 64
    )
    aggregate_id = f"method:{suite.method_id}@{suite.method_version}"
    first_runtime.audit_trail.append(
        aggregate_id=aggregate_id, event_type="method_certification",
        actor=registration.actor, payload=registration.model_dump(mode="json"),
    )
    report = first_runtime.method_certifications.execute_benchmark(
        suite, implementation_sha256="b" * 64, runner=_Runner(),
        dataset_loader=_DatasetLoader(), execution_environment={"python": "3.12"},
    )
    first_runtime.audit_trail.append(
        aggregate_id=aggregate_id, event_type="method_certification",
        actor=report.runner_id,
        payload={
            "report_id": report.report_id, "report_sha256": report.report_sha256,
            "status": report.status, "suite_id": report.suite_id,
            "suite_version": report.suite_version,
            "report": report.model_dump(mode="json"),
        },
    )
    promoted = first_runtime.method_certifications.transition(
        suite.method_id, suite.method_version, expected_version=1, state="internal",
        actor="reviewer", rationale="Fixture benchmark passed.",
        benchmark_report_ids=(report.report_id,),
    )
    first_runtime.audit_trail.append(
        aggregate_id=aggregate_id, event_type="method_certification",
        actor=promoted.actor, payload=promoted.model_dump(mode="json"),
    )

    restarted_runtime = PlatformRuntime(config=config)
    assert restarted_runtime.method_certifications.state(
        suite.method_id, suite.method_version
    ) == "internal"
    assert restarted_runtime.method_certifications.reports(
        suite.method_id, suite.method_version
    ) == (report,)
    with pytest.raises(ValueError, match="differs from its certification history"):
        restarted_runtime.method_certifications.bind_implementation(
            suite.method_id, suite.method_version, "c" * 64
        )


def test_platform_runtime_restores_hypothesis_lifecycle_from_audit(tmp_path):
    from satquery.platform.planning import CandidateHypothesis
    from satquery.platform.scientific_inference import (
        HypothesisLifecycleLedger,
        hypothesis_graph_from_candidates,
    )

    audit_path = tmp_path / "hypotheses.sqlite"
    config = PlatformConfig.load(
        environ={}, overrides={"storage": {"audit_path": str(audit_path)}}
    )
    runtime = PlatformRuntime(config=config)
    ledger = HypothesisLifecycleLedger()
    candidate = CandidateHypothesis(
        statement="Surface water expanded.",
        source_text="An explicit investigation proposition.",
        origin="explicit",
    )
    record = hypothesis_graph_from_candidates((candidate,)).hypotheses[0].model_copy(
        update={"lifecycle": "proposed"}
    )
    ledger.add(record, actor="researcher", rationale="Preregistered.")
    active = ledger.transition(
        record.hypothesis_id,
        expected_version=1,
        status="active",
        actor="researcher",
        rationale="Approved for evaluation.",
    )
    for event in ledger.events():
        event_record = ledger.get(event.hypothesis_id)
        if event.version == 1:
            event_record = record
        else:
            event_record = active
        runtime.audit_trail.append(
            aggregate_id="investigation-persistent",
            event_type="hypothesis_transition",
            actor=event.actor,
            payload={
                "hypothesis_id": event.hypothesis_id,
                "version": event.version,
                "state": event.to_status,
                "rationale": event.rationale,
                "record": event_record.model_dump(mode="json"),
                "event": event.model_dump(mode="json"),
            },
        )

    restarted = PlatformRuntime(config=config)
    restored = restarted.get_hypothesis_ledger("investigation-persistent")
    assert restored is not None
    assert restored.get(record.hypothesis_id) == active
    assert tuple(event.version for event in restored.events()) == (1, 2)
    ensured = restarted.ensure_hypothesis_ledger(
        "investigation-persistent", (candidate,)
    )
    assert ensured.events() == restored.events()


def test_platform_runtime_rejects_partial_replayed_design_hypotheses(tmp_path):
    from satquery.platform.planning import CandidateHypothesis
    from satquery.platform.scientific_inference import (
        HypothesisLifecycleLedger,
        hypothesis_graph_from_candidates,
    )

    audit_path = tmp_path / "partial-hypotheses.sqlite"
    config = PlatformConfig.load(
        environ={}, overrides={"storage": {"audit_path": str(audit_path)}}
    )
    runtime = PlatformRuntime(config=config)
    candidates = (
        CandidateHypothesis(
            statement="Surface water expanded.",
            source_text="The first explicit proposition.",
            origin="explicit",
        ),
        CandidateHypothesis(
            statement="Surface water contracted.",
            source_text="The competing explicit proposition.",
            origin="explicit",
        ),
    )
    partial_record = hypothesis_graph_from_candidates(candidates[:1]).hypotheses[0].model_copy(
        update={"lifecycle": "proposed"}
    )
    ledger = HypothesisLifecycleLedger()
    ledger.add(partial_record, actor="researcher", rationale="Partial history fixture.")
    event = ledger.events()[0]
    runtime.audit_trail.append(
        aggregate_id="investigation-partial",
        event_type="hypothesis_transition",
        actor=event.actor,
        payload={
            "hypothesis_id": event.hypothesis_id,
            "version": event.version,
            "state": event.to_status,
            "rationale": event.rationale,
            "record": partial_record.model_dump(mode="json"),
            "event": event.model_dump(mode="json"),
        },
    )

    restarted = PlatformRuntime(config=config)
    with pytest.raises(ValueError, match="exact hypotheses declared"):
        restarted.ensure_hypothesis_ledger("investigation-partial", candidates)
    assert restarted.get_hypothesis_ledger("investigation-partial") is None


def test_platform_runtime_fails_closed_for_summary_only_hypothesis_history(tmp_path):
    audit_path = tmp_path / "hypotheses-legacy.sqlite"
    config = PlatformConfig.load(
        environ={}, overrides={"storage": {"audit_path": str(audit_path)}}
    )
    runtime = PlatformRuntime(config=config)
    runtime.audit_trail.append(
        aggregate_id="investigation-legacy",
        event_type="hypothesis_transition",
        actor="researcher",
        payload={"hypothesis_id": "legacy", "version": 1, "state": "proposed"},
    )

    restarted = PlatformRuntime(config=config)
    assert restarted.get_hypothesis_ledger("investigation-legacy") is None
    assert "lacks a replayable record" in restarted.hypothesis_restore_error(
        "investigation-legacy"
    )


def test_platform_runtime_fails_closed_when_hypothesis_audit_commit_fails():
    from satquery.platform.scientific_inference import (
        HypothesisLifecycleLedger,
        HypothesisRecord,
    )

    runtime = PlatformRuntime()
    ledger = HypothesisLifecycleLedger()
    ledger.add(
        HypothesisRecord(
            hypothesis_id="not-committed",
            proposition="A declared proposition.",
            source_text="Explicitly supplied.",
            origin="explicit",
        ),
        actor="researcher",
        rationale="Registration attempt.",
    )

    def reject_append(**_kwargs):
        raise OSError("audit storage unavailable")

    runtime.audit_trail.append = reject_append
    with pytest.raises(OSError, match="audit storage unavailable"):
        runtime.record_hypothesis_lifecycle_event(
            "investigation-unavailable", ledger, ledger.events()[0]
        )

    assert runtime.get_hypothesis_ledger("investigation-unavailable") is None
    assert "could not be committed" in runtime.hypothesis_restore_error(
        "investigation-unavailable"
    )


class _AtmosphericFixture(PerceptionConnector):
    @property
    def metadata(self):
        return ConnectorMetadata(
            connector_id="fixture-atmosphere",
            name="Atmospheric fixture",
            version="1",
            capabilities=("observation",),
            modalities=("atmospheric",),
            supported_variables=("air_temperature",),
            supported_spatial_types=("point",),
            supports_temporal_query=True,
            supported_query_fields=("requested_dataset_ids",),
        )

    async def discover(self):
        return self.metadata.datasets

    async def acquire(self, request):
        return request

    async def observe(self, query):
        return ObservationSearchResult(
            observations=(
                Observation(
                    source_id="fixture-record-1",
                    measured_variables={
                        "air_temperature": {"value": 292.1, "unit": "K"}
                    },
                ),
            ),
            matched=1,
        )


class _EarthObjectFixture(_AtmosphericFixture):
    async def observe(self, query):
        return ObservationSearchResult(
            observations=(
                Observation(
                    observation_id="fixture-object-observation-v1",
                    source_id="fixture-object-source-1",
                    dataset=DatasetReference(
                        connector_id="fixture-atmosphere",
                        dataset_id="fixture-earth-feature",
                        version="1",
                    ),
                    geometry={"type": "Point", "coordinates": [12.0, 45.0]},
                    crs="OGC:CRS84",
                    observation_type="vector_feature",
                    earth_object_candidate=EarthObjectCandidate(
                        identity_namespace="fixture.example/features",
                        identity_value="feature-1",
                        object_type="earth:TestFeature",
                        declared_by=self.metadata.connector_id,
                        mapping_id="fixture-explicit-object-candidate@1.0.0",
                        provenance={
                            "source_attributes": {
                                "source_label": "Feature One",
                                "unmapped_code": "A7",
                            }
                        },
                    ),
                    modalities=("atmospheric",),
                    source_document={"source_record": "feature-1"},
                ),
            ),
            matched=1,
        )


def test_object_candidates_flow_through_investigation_memory_and_report():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_EarthObjectFixture())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            client.post(
                "/api/v1/platform/missions",
                json={
                    "mission_id": "earth-object-mission",
                    "name": "Feature inventory",
                    "objective": "Record an explicitly declared feature",
                },
            )
            investigation = client.post(
                "/api/v1/platform/missions/earth-object-mission/investigations",
                json={"requested_variables": ["air_temperature"]},
            ).json()
            investigation_id = investigation["investigation_id"]
            executed = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/execute"
            )
            assert executed.status_code == 200
            assert executed.json()["status"] == "succeeded"
            extraction_task = next(
                item for item in executed.json()["tasks"]
                if item["handler"] == "earth.objects.extract"
            )
            assert len(extraction_task["output"]["materialized_object_ids"]) == 1

            extraction = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["earth_object_extraction"],
                    "investigation_id": investigation_id,
                },
            )
            assert extraction.status_code == 200
            assert extraction.json()["total"] == 1
            assert len(
                extraction.json()["artifacts"][0]["payload"]["declarations"]
            ) == 1

            objects = client.get(
                "/api/v1/platform/earth-objects",
                params={"investigation_id": investigation_id},
            )
            assert objects.status_code == 200
            object_record = objects.json()[0]
            assert object_record["object_type"] == "earth:TestFeature"
            assert {item["source_key"] for item in object_record["source_attributes"]} == {
                "source_label",
                "unmapped_code",
            }
            assert object_record["lifecycle"] == "unknown"

            memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["earth_object", "earth_object_extraction"],
                    "investigation_id": investigation_id,
                    "text": "unmapped_code",
                },
            )
            assert memory.status_code == 200
            assert memory.json()["total"] >= 1
            assert any(
                artifact["artifact_type"] == "earth_object"
                for artifact in memory.json()["artifacts"]
            )
            object_artifact = next(
                item for item in memory.json()["artifacts"]
                if item["artifact_type"] == "earth_object"
            )
            source_observation = object_record["source_observation_ids"][0]
            assert any(
                item.startswith(f"observation:{source_observation}:")
                for item in object_artifact["source_artifact_ids"]
            )
            method_search = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["earth_object"],
                    "investigation_id": investigation_id,
                    "method_id": "fixture-explicit-object-candidate",
                },
            )
            assert method_search.status_code == 200
            assert method_search.json()["total"] == 1

            report = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/report"
            )
            assert report.status_code == 200
            assert len(report.json()["earth_objects"]) == 1
            assert "Unmapped source attribute" in report.json()["markdown"]
            assert "no canonical semantic mapping asserted" in report.json()["markdown"]
            assert 'id="earthObjects"' in client.get("/").text

            transition = client.post(
                f"/api/v1/platform/earth-objects/id/{object_record['object_id']}/transitions",
                json={
                    "prior_object_id": object_record["object_id"],
                    "transition_type": "reclassification",
                    "actor": "reviewer-1",
                    "rationale": "The source feature record was reviewed and explicitly reclassified.",
                    "observation_ids": object_record["source_observation_ids"],
                    "evidence_ids": [],
                    "prior_object_type": "earth:TestFeature",
                    "new_object_type": "earth:ReviewedFeature",
                },
            )
            assert transition.status_code == 200
            assert transition.json()["revision"] == 2
            assert transition.json()["object_type"] == "earth:ReviewedFeature"
            assert transition.json()["supersedes_object_id"] == object_record["object_id"]
            revised_report = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/report"
            )
            assert revised_report.status_code == 200
            assert len(revised_report.json()["earth_objects"]) == 1
            assert (
                revised_report.json()["earth_objects"][0]["object_type"]
                == "earth:ReviewedFeature"
            )
            transition_memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["earth_object_transition"],
                    "investigation_id": investigation_id,
                },
            )
            assert transition_memory.status_code == 200
            assert transition_memory.json()["total"] == 1
            assert transition_memory.json()["artifacts"][0]["payload"][
                "transition_type"
            ] == "reclassification"
            audit = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/audit"
            )
            assert audit.status_code == 200
            assert any(
                event["event_type"] == "earth_object_transition"
                for chain in audit.json()["chains"].values()
                for event in chain["events"]
            )
            reproducibility = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reproducibility"
            )
            assert reproducibility.status_code == 200
            bundle = reproducibility.json()
            assert bundle["schema_version"] == "1.3.0"
            assert [item["revision"] for item in bundle["earth_objects"]] == [1, 2]
            assert bundle["earth_object_graph"]["objects"]
            assert len(bundle["earth_object_extractions"]) == 1
            assert len(bundle["earth_object_transitions"]) == 1
            assert "earth_objects" in bundle["artifact_hashes"]
            assert "earth_object_graph" in bundle["artifact_hashes"]
            repeated = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reproducibility"
            )
            assert repeated.status_code == 200
            assert repeated.json()["bundle_sha256"] == bundle["bundle_sha256"]
    finally:
        set_engine(None)


class _CategoricalRasterFixture(_AtmosphericFixture):
    def __init__(self, asset_uri: str) -> None:
        super().__init__()
        self.asset_uri = asset_uri

    @property
    def metadata(self):
        return ConnectorMetadata(
            connector_id="fixture-categorical-raster",
            name="Categorical raster fixture",
            version="1",
            capabilities=("observation", "raster_asset"),
            modalities=("visual", "ecological"),
            supported_variables=("land_cover_class",),
            supported_spatial_types=("bbox",),
            supported_query_fields=("requested_dataset_ids", "requested_variables"),
        )

    async def observe(self, query):
        return ObservationSearchResult(
            observations=(Observation(
                observation_id="fixture-categorical-raster-observation",
                source_id="fixture-categorical-raster-source",
                dataset=DatasetReference(
                    connector_id=self.metadata.connector_id,
                    dataset_id="fixture-land-cover-raster",
                    version="1",
                ),
                observed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                modalities=("visual",),
                assets={"classification": ObservationAsset(
                    uri=self.asset_uri,
                    media_type="image/tiff; application=geotiff",
                    roles=("data",),
                    metadata={"raster:bands": [{
                        "name": "land_cover_class",
                        "data_type": "uint8",
                        "measurement_kind": "categorical",
                    }]},
                )},
            ),),
            matched=1,
        )


def test_categorical_raster_components_materialize_through_investigation_api():
    import tempfile

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    with tempfile.NamedTemporaryFile(
        suffix=".tif", dir=Path.cwd(), delete=False
    ) as temp_raster:
        raster_path = Path(temp_raster.name)
    raster_values = np.array(
        [
            [7, 7, 0, 0, 0],
            [7, 7, 0, 0, 0],
            [0, 0, 7, 0, 0],
            [0, 0, 0, 0, 0],
            [0, 0, 0, 0, 7],
        ],
        dtype=np.uint8,
    )
    try:
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=5,
            height=5,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(0, 5, 1, 1),
            nodata=0,
        ) as dataset:
            dataset.write(raster_values, 1)

        engine = SatQueryEngine(get_settings())
        engine.platform_runtime.register_connector(
            _CategoricalRasterFixture(str(raster_path))
        )
        engine.platform_runtime.registries.datasets.register(
            DatasetMetadata(
                connector_id="fixture-categorical-raster",
                dataset_id="fixture-land-cover-raster",
                provider="fixture source",
                version="1",
                variables=("land_cover_class",),
                modalities=("visual", "ecological"),
                capabilities=("raster_categorical_polygonization",),
            )
        )
        engine.platform_runtime.earth_object_extraction_pipeline = (
            EarthObjectExtractionPipeline(
                RasterCategoricalComponentExtractor(allow_local_files=True)
            )
        )
        set_engine(engine)
        query = EarthQuery(
            bbox=(0, 0, 5, 5),
            crs="EPSG:4326",
            requested_variables=("land_cover_class",),
            raster_component_extraction=({
                "asset_key": "classification",
                "band_index": 1,
                "source_variable": "land_cover_class",
                "class_mappings": [{
                    "class_value": 7,
                    "object_type": "earth:UserDeclaredClass7Region",
                }],
                "connectivity": 8,
                "pixel_selection": "pixel_center",
                "minimum_component_pixels": 2,
                "maximum_components": 10,
            },),
        )
        with TestClient(create_app(get_settings())) as client:
            mission = client.post(
                "/api/v1/platform/missions",
                json={
                    "mission_id": "categorical-raster-mission",
                    "name": "Categorical raster materialization",
                    "objective": "Polygonize a caller-declared raster class",
                },
            )
            assert mission.status_code == 201
            created = client.post(
                "/api/v1/platform/missions/categorical-raster-mission/investigations",
                json=query.model_dump(mode="json"),
            )
            assert created.status_code == 201
            investigation_id = created.json()["investigation_id"]
            executed = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/execute"
            )
            assert executed.status_code == 200
            extraction_task = next(
                item for item in executed.json()["tasks"]
                if item["handler"] == "earth.objects.extract"
            )
            assert extraction_task["status"] == "succeeded"
            assert len(
                extraction_task["output"]["materialized_object_ids"]
            ) == 1, extraction_task["output"]
            assert extraction_task["output"]["issues"] == []

            objects = client.get(
                "/api/v1/platform/earth-objects",
                params={"investigation_id": investigation_id},
            )
            assert objects.status_code == 200
            assert len(objects.json()) == 1
            earth_object = objects.json()[0]
            assert earth_object["object_type"] == "earth:UserDeclaredClass7Region"
            from shapely.geometry import shape

            assert earth_object["geometry"]["type"] == "MultiPolygon"
            assert shape(earth_object["geometry"]).is_valid
            assert earth_object["crs"] == "EPSG:4326"
            assert earth_object["property_assertions"][0]["value"] == 5
            assert earth_object["uncertainty"]["derived"][
                "classification_uncertainty"
            ] == "not_assessed"
            provenance = earth_object["provenance"]["declared_provenance"]
            assert provenance["extraction_pipeline"][
                "semantic_mapping_origin"
            ] == "explicit_query_configuration"
            assert provenance["raster_processing"]["source_window_sha256"]
            assert provenance["raster_processing"]["geometry_topology_repaired"]
            report = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/report"
            )
            assert report.status_code == 200
            assert len(report.json()["earth_objects"]) == 1
            assert 'id="earthObjects"' in client.get("/").text
            bundle = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reproducibility"
            )
            assert bundle.status_code == 200
            assert len(bundle.json()["earth_objects"]) == 1
            repeated_bundle = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reproducibility"
            )
            assert repeated_bundle.json()["bundle_sha256"] == bundle.json()[
                "bundle_sha256"
            ]
    finally:
        set_engine(None)
        raster_path.unlink(missing_ok=True)


class _FailingScientificOperator:
    operator_id = "fixture.failing-operator"
    version = "1"

    def evaluate(self, context):
        raise RuntimeError("extension failure must not escape reasoning")


def test_platform_api_exposes_modalities_and_perception_planning():
    engine = SatQueryEngine(get_settings())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            modalities = client.get("/api/v1/platform/modalities")
            assert modalities.status_code == 200
            assert "hydrological" in {item["modality_id"] for item in modalities.json()}

            capability_matrix = client.get("/api/v1/platform/earth/capabilities")
            assert capability_matrix.status_code == 200
            assert capability_matrix.json()["revision"]
            assert "ecological" in {
                item["modality_id"] for item in capability_matrix.json()["modalities"]
            }

            planned = client.post(
                "/api/v1/platform/earth/plan",
                json={"requested_variables": ["air_temperature"]},
            )
            assert planned.status_code == 200
            assert planned.json()["requested_modalities"] == ["atmospheric"]
            assert planned.json()["selected_modalities"] == []
            assert planned.json()["unavailable_modalities"] == ["atmospheric"]
            assert (
                planned.json()["capability_matrix_revision"]
                == capability_matrix.json()["revision"]
            )
            scientific_methods = client.get("/api/v1/platform/scientific-methods")
            assert scientific_methods.status_code == 200
            method_catalog = scientific_methods.json()
            assert method_catalog["rules"] == []
            assert "satquery.temporal-alignment" in {
                item["operator_id"] for item in method_catalog["operators"]
            }
            assert len(method_catalog["domains"]) == 10
            assert all(
                item["status"] == "no_validated_methods_registered"
                for item in method_catalog["domains"]
            )
            cited_library = client.get(
                "/api/v1/platform/scientific-knowledge/methods?domain=hydrology"
            )
            assert cited_library.status_code == 200
            assert cited_library.json()[0]["benchmark_status"] == "identified_not_materialized"
            assert cited_library.json()[0]["implementation_status"] == "reference_catalog_only"
            earth_memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"text": "Landsat", "artifact_types": ["scientific_method"]},
            )
            assert earth_memory.status_code == 200
            assert earth_memory.json()["total"] >= 1
            assert "search_text" not in earth_memory.json()["artifacts"][0]
            workflows = client.get("/api/v1/platform/scientific-workflows")
            assert workflows.status_code == 200
            assert len(workflows.json()) == 10
            assert all(not item["methods"] and not item["conclusions"] for item in workflows.json())
            instantiated = client.post(
                "/api/v1/platform/scientific-workflows/earth-investigation.drought/instantiate",
                json={"configuration": {"area_of_interest": "explicitly supplied"}},
            )
            assert instantiated.status_code == 200
            assert instantiated.json()["conclusions"] == []
            assert instantiated.json()["generated_method_ids"] == []
            assert "drought_definition" in instantiated.json()["unresolved_configuration"]
            missing_method = client.post(
                "/api/v1/platform/scientific-methods/assess",
                json={"method_id": "unknown", "version": "1", "earth_query": {}},
            )
            assert missing_method.status_code == 404
    finally:
        set_engine(None)


def test_platform_earth_memory_api_accepts_spatiotemporal_filters():
    engine = SatQueryEngine(get_settings())
    from datetime import datetime, timezone

    observed_at = datetime(2025, 4, 10, tzinfo=timezone.utc)
    observation = Observation(
        observation_id="memory-api-observation", bbox=(70, 10, 72, 12),
        crs="OGC:CRS84", observed_at=observed_at,
        measured_variables={"ndvi": {"value": 0.4, "unit": "1"}},
    )
    observation = SemanticNormalizer().harmonize_observation(observation)
    engine.platform_runtime.earth_memory.upsert(artifact_from_payload(
        artifact_id="observation:memory-api-observation", artifact_type="observation",
        payload=observation, indexed_at=observed_at.isoformat(),
    ))
    for artifact_id in ("evidence:memory-api-a", "evidence:memory-api-b"):
        engine.platform_runtime.earth_memory.upsert(artifact_from_payload(
            artifact_id=artifact_id, artifact_type="evidence",
            payload={"source": artifact_id}, indexed_at=observed_at.isoformat(),
        ))
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            workspace = client.get("/")
            assert workspace.status_code == 200
            assert 'id="modalityCatalog"' in workspace.text
            assert 'id="datasetSearch"' in workspace.text
            assert 'id="connectorExplorer"' in workspace.text
            assert "searchRegisteredDatasets" in workspace.text
            assert "/api/v1/platform/connectors/health" in workspace.text
            assert "/api/v1/platform/datasets/search" in workspace.text
            assert "health-check" in workspace.text
            assert "runConnectorOperation('discover')" in workspace.text
            assert 'id="searchEarthMemory"' in workspace.text
            assert 'id="nextEarthMemoryPage"' in workspace.text
            assert 'id="memoryVariable"' in workspace.text
            assert 'id="memoryArtifactType"' in workspace.text
            assert 'id="memoryMission"' in workspace.text
            assert 'id="memoryInvestigation"' in workspace.text
            assert 'id="memoryMethod"' in workspace.text
            assert 'id="memorySourceArtifact"' in workspace.text
            assert "canonical_variable: $('memoryVariable')" in workspace.text
            response = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "spatial_bbox": [71, 11, 71.5, 11.5],
                    "spatial_crs": "OGC:CRS84",
                    "temporal_start": "2025-04-10T00:00:00Z",
                    "temporal_end": "2025-04-10T00:00:00Z",
                    "artifact_types": ["observation"],
                },
            )
            assert response.status_code == 200
            assert response.json()["total"] == 1
            variable_response = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"canonical_variable": "ndvi"},
            )
            assert variable_response.status_code == 200
            assert variable_response.json()["total"] == 1
            assert (
                variable_response.json()["artifacts"][0]["artifact_id"]
                == "observation:memory-api-observation"
            )
            assert response.json()["spatial_semantics"] == "inclusive_same_crs_bbox_overlap"
            assert response.json()["temporal_semantics"] == "inclusive_interval_overlap"
            assert response.json()["artifacts"][0]["artifact_id"] == "observation:memory-api-observation"
            paged = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"artifact_types": ["evidence"], "limit": 1},
            )
            assert paged.status_code == 200
            assert paged.json()["total"] == 2
            assert paged.json()["next_cursor"]
            next_page = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["evidence"], "limit": 1,
                    "cursor": paged.json()["next_cursor"],
                },
            )
            assert next_page.status_code == 200
            assert next_page.json()["total"] == 1
            assert next_page.json()["next_cursor"] is None
            assert paged.json()["artifacts"][0]["artifact_id"] != next_page.json()["artifacts"][0]["artifact_id"]
            mismatched_cursor = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["observation"],
                    "cursor": paged.json()["next_cursor"],
                },
            )
            assert mismatched_cursor.status_code == 422
            engine.platform_runtime.earth_memory.upsert(artifact_from_payload(
                artifact_id="evidence:memory-api-c",
                artifact_type="evidence",
                payload={"source": "evidence:memory-api-c"},
                indexed_at=observed_at.isoformat(),
            ))
            stale_cursor = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["evidence"],
                    "cursor": paged.json()["next_cursor"],
                },
            )
            assert stale_cursor.status_code == 409
            rejected = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"spatial_bbox": [0, 0, 1, 1]},
            )
            assert rejected.status_code == 422
    finally:
        set_engine(None)


def test_temporal_differences_are_exposed_and_indexed_for_an_investigation():
    engine = SatQueryEngine(get_settings())
    runtime = engine.platform_runtime
    mission = runtime.mission_service.create(Mission(
        mission_id="mission-temporal-difference",
        name="Temporal raster inspection",
        objective="Compare exact-support samples",
    ))
    investigation = runtime.mission_service.create_investigation(mission.mission_id)
    runtime.investigation_service.start(investigation.investigation_id)
    support = {
        "type": "Polygon",
        "coordinates": [[[10, 20], [11, 20], [11, 21], [10, 21], [10, 20]]],
    }
    members = tuple(
        ObservationStackMember(
            observation_id=f"temporal-scene-{day}",
            measurement_observation_id=f"temporal-measurement-{day}",
            dataset=DatasetReference(connector_id="fixture-stac", dataset_id="thermal-collection"),
            observed_at=datetime(2025, 3, day, tzinfo=timezone.utc),
            value=value,
            unit="K",
            source_variable="surface_temperature",
            source_measurement_metadata={
                "pixel_support_geometry": support,
                "pixel_support_crs": "OGC:CRS84",
            },
            provenance={"source_item_id": f"item-{day}"},
        )
        for day, value in ((1, 290.0), (2, 291.5))
    )
    stack = ObservationStack(
        stack_id="api-test-stack",
        variable_key="canonical:surface_temperature",
        canonical_variable="surface_temperature",
        unit="K",
        spatial_support_geometry=support,
        spatial_support_crs="OGC:CRS84",
        spatial_alignment="exact_pixel_support",
        temporal_alignment="source_acquisition_time",
        members=members,
    )
    from satquery.platform.spatiotemporal import ConsecutiveTemporalDifferenceEngine

    diagnostic = ConsecutiveTemporalDifferenceEngine().build((stack,))[0][0]
    perception_result = PerceptionResult(
        query_fingerprint="api-test-query",
        observation_stacks=(stack,),
        temporal_differences=(diagnostic,),
    )
    now = utc_now()
    execution = ExecutionResult(
        plan_id="execution-temporal-test",
        status=ExecutionStatus.SUCCEEDED,
        started_at=now,
        tasks=(TaskExecution(
            task_id="observe",
            handler="earth.observe",
            status=TaskStatus.SUCCEEDED,
            attempts=1,
            output=perception_result,
            duration_seconds=0,
            finished_at=now,
        ),),
    )
    runtime.record_execution_result(execution, investigation_id=investigation.investigation_id)
    runtime.investigation_service.add_result(
        investigation.investigation_id, execution.plan_id
    )
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            stacks_response = client.get(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/observation-stacks"
            )
            assert stacks_response.status_code == 200
            assert stacks_response.json()[0]["stack_id"] == stack.stack_id
            assert len(stacks_response.json()[0]["members"]) == 2
            response = client.get(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/temporal-differences"
            )
            assert response.status_code == 200
            assert response.json()[0]["difference_value"] == 1.5
            assert response.json()[0]["interpretation_status"] == "descriptive_only"
            assert response.json()[0]["uncertainty_status"] == "not_propagated"
            report = client.get(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/report"
            )
            assert report.status_code == 200
            assert len(report.json()["temporal_differences"]) == 1
            assert "Descriptive only" in report.json()["markdown"]
            memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "investigation_id": investigation.investigation_id,
                    "artifact_types": ["temporal_difference"],
                    "spatial_bbox": [10.2, 20.2, 10.8, 20.8],
                    "spatial_crs": "OGC:CRS84",
                    "temporal_start": "2025-03-01T00:00:00Z",
                    "temporal_end": "2025-03-02T00:00:00Z",
                },
            )
            assert memory.status_code == 200
            assert memory.json()["total"] == 1
            assert memory.json()["artifacts"][0]["payload"]["stack_id"] == stack.stack_id
            workspace = client.get("/")
            assert "Temporal sample differences" in workspace.text
    finally:
        set_engine(None)


def test_platform_mission_investigation_executes_registered_tasks(monkeypatch):
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            def api_request(method, path, *, payload=None, params=None):
                response = client.request(method, path, json=payload, params=params)
                response.raise_for_status()
                return response.json()

            monkeypatch.setattr(cli, "_platform_api_request", api_request)
            created = client.post(
                "/api/v1/platform/missions",
                json={
                    "mission_id": "mission-1",
                    "name": "Flood watch",
                    "objective": "Observe river levels",
                },
            )
            assert created.status_code == 201

            investigation_response = client.post(
                "/api/v1/platform/missions/mission-1/investigations",
                json={"requested_variables": ["air_temperature"]},
            )
            assert investigation_response.status_code == 201
            investigation_id = investigation_response.json()["investigation_id"]

            artifacts = cli._execute_investigation_and_collect_artifacts(
                investigation_id
            )
            assert artifacts["execution"]["status"] == "succeeded"
            assert (
                artifacts["observations"][0]["source_id"]
                == "fixture-record-1"
            )
            assert artifacts["earth_objects"] == []
            assert (
                artifacts["report"]["investigation"]["investigation_id"]
                == investigation_id
            )
            assert artifacts["audit"]["chains"][investigation_id]["valid"] is True
            assert artifacts["reproducibility"]["observations"]
            assert artifacts["events"]["events"]

            extraction = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["earth_object_extraction"],
                    "investigation_id": investigation_id,
                },
            )
            assert extraction.status_code == 200
            assert extraction.json()["total"] == 1
            assert extraction.json()["artifacts"][0]["payload"]["declarations"] == []

            inspected = client.get(
                f"/api/v1/platform/investigations/{investigation_id}"
            )
            assert inspected.status_code == 200
            assert inspected.json()["status"] == "completed"
            assert "not a scientific conclusion" in inspected.json()["report"]
            audit = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/audit"
            )
            assert audit.status_code == 200
            assert audit.json()["chains"][investigation_id]["valid"] is True
            assert audit.json()["chains"][investigation_id]["events"]
            reproducibility = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reproducibility"
            )
            assert reproducibility.status_code == 200
            bundle = reproducibility.json()
            assert bundle["capability_matrix_revision"]
            assert bundle["bundle_sha256"]
            assert bundle["observations"]
            assert bundle["earth_objects"] == []
            assert bundle["earth_object_graph"]["objects"] == []
            assert len(bundle["earth_object_extractions"]) == 1
            assert "earth_objects" not in bundle["missing_artifacts"]
            assert "earth_object_graph" not in bundle["missing_artifacts"]
            assert "earth_object_transitions" not in bundle["missing_artifacts"]
            assert bundle["provenance"]
    finally:
        set_engine(None)


def test_monitoring_schedule_runs_and_records_a_linked_investigation():
    from datetime import timedelta

    from satquery.platform.contracts import utc_now

    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            mission = client.post(
                "/api/v1/platform/missions",
                json={"mission_id": "monitor-mission", "name": "Air watch", "objective": "Track air temperature observations"},
            )
            assert mission.status_code == 201
            now = utc_now()
            schedule = client.post(
                "/api/v1/platform/monitoring/schedules",
                json={
                    "schedule_id": "temperature-watch",
                    "mission_id": "monitor-mission",
                    "name": "Hourly temperature observation",
                    "interval_seconds": 1,
                    "next_run_at": (now - timedelta(seconds=10)).isoformat(),
                    "earth_query": {"requested_variables": ["air_temperature"]},
                    "trigger_policies": [{
                        "policy_id": "temperature-review",
                        "name": "Review any descriptive temperature difference",
                        "canonical_variable": "air_temperature",
                        "unit": "K",
                        "operator": "gte",
                        "threshold": 0,
                        "follow_up_query": {
                            "requested_variables": ["air_temperature"],
                        },
                    }],
                },
            )
            assert schedule.status_code == 201, schedule.text
            assert 'id="createMonitor"' in client.get("/").text
            assert 'id="monitoringHealth"' in client.get("/").text
            assert 'id="monitorTriggerPolicies"' in client.get("/").text

            dispatched = client.post("/api/v1/platform/monitoring/run-due")
            assert dispatched.status_code == 200, dispatched.text
            runs = dispatched.json()
            assert len(runs) == 1
            assert runs[0]["status"] == "completed"
            assert runs[0]["execution_id"]
            investigation_id = runs[0]["investigation_id"]

            investigation = client.get(
                f"/api/v1/platform/investigations/{investigation_id}"
            )
            assert investigation.status_code == 200
            assert investigation.json()["status"] == "completed"
            report = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/report"
            )
            assert report.status_code == 200
            report_data = report.json()
            assert report_data["schema_version"] == "1.4"
            assert report_data["monitoring_context"]["runs"][0]["run_id"] == runs[0]["run_id"]
            assert report_data["monitoring_context"]["schedule_definitions"][0]["revision"] == 1
            assert "Continuous observation context" in report_data["markdown"]
            run_history = client.get(
                "/api/v1/platform/monitoring/schedules/temperature-watch/runs"
            )
            assert run_history.status_code == 200
            assert run_history.json() == runs
            memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"artifact_types": ["monitoring_run"], "mission_id": "monitor-mission"},
            )
            assert memory.status_code == 200
            assert memory.json()["total"] == 1
            assert f"investigation:{investigation_id}" in memory.json()["artifacts"][0]["source_artifact_ids"]
            assert any(
                item.startswith(f"investigation-snapshot:{investigation_id}:")
                for item in memory.json()["artifacts"][0]["source_artifact_ids"]
            )
            assert "monitoring-schedule:temperature-watch:revision:1" in memory.json()["artifacts"][0]["source_artifact_ids"]
            reproducibility = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reproducibility"
            )
            assert reproducibility.status_code == 200
            reproducibility_bundle = reproducibility.json()
            assert reproducibility_bundle["schema_version"] == "1.3.0"
            assert reproducibility_bundle["monitoring_runs"][0]["run_id"] == runs[0]["run_id"]
            assert reproducibility_bundle["monitoring_schedules"][0]["revision"] == 1
            assert {event["event_type"] for event in reproducibility_bundle["monitoring_events"]} >= {
                "schedule_created", "run_claimed", "run_completed"
            }
            event_history = client.get(
                "/api/v1/platform/monitoring/events",
                params={"run_id": runs[0]["run_id"]},
            )
            assert event_history.status_code == 200
            assert [event["event_type"] for event in event_history.json()] == [
                "run_claimed", "run_completed"
            ]
            first_event_page = client.get(
                "/api/v1/platform/monitoring/events/page",
                params={"schedule_id": "temperature-watch", "limit": 1},
            )
            assert first_event_page.status_code == 200
            assert len(first_event_page.json()["events"]) == 1
            if first_event_page.json()["has_more"]:
                next_event_page = client.get(
                    "/api/v1/platform/monitoring/events/page",
                    params={
                        "schedule_id": "temperature-watch",
                        "limit": 1,
                        "cursor": first_event_page.json()["next_cursor"],
                    },
                )
                assert next_event_page.status_code == 200
                assert next_event_page.json()["events"][0]["event_id"] != (
                    first_event_page.json()["events"][0]["event_id"]
                )
            invalid_event_cursor = client.get(
                "/api/v1/platform/monitoring/events/page",
                params={"cursor": "not-a-cursor"},
            )
            assert invalid_event_cursor.status_code == 422
            health = client.get("/api/v1/platform/monitoring/health")
            assert health.status_code == 200
            assert health.json()["completed_run_count"] == 1
            assert health.json()["trigger_evaluation_count"] == 0
            workspace = client.get("/")
            assert workspace.status_code == 200
            assert "loadOlderMonitoringEvents" in workspace.text
            assert "loadOlderMonitoringTriggers" in workspace.text
            assert "/api/v1/platform/monitoring/events/page" in workspace.text
            trigger_history = client.get(
                "/api/v1/platform/monitoring/schedules/temperature-watch/triggers"
            )
            assert trigger_history.status_code == 200
            assert trigger_history.json()["policies"][0]["policy_id"] == "temperature-review"
            assert trigger_history.json()["events"] == []
            assert "next_cursor" in trigger_history.json()
            assert "history_truncated" not in trigger_history.json()
            too_few_runs = client.get(
                "/api/v1/platform/monitoring/schedules/temperature-watch/comparison"
            )
            assert too_few_runs.status_code == 409

            time.sleep(1.05)
            second_dispatch = client.post("/api/v1/platform/monitoring/run-due")
            assert second_dispatch.status_code == 200
            second_runs = second_dispatch.json()
            assert len(second_runs) == 1
            assert second_runs[0]["status"] == "completed", second_runs[0]
            repeated_observations = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["observation"],
                    "mission_id": "monitor-mission",
                },
            )
            assert repeated_observations.status_code == 200
            observation_artifacts = repeated_observations.json()["artifacts"]
            assert len(observation_artifacts) == 2
            assert len({item["artifact_id"] for item in observation_artifacts}) == 2
            assert len({item["investigation_id"] for item in observation_artifacts}) == 2
            comparison = client.get(
                "/api/v1/platform/monitoring/schedules/temperature-watch/comparison"
            )
            assert comparison.status_code == 200, comparison.text
            comparison_data = comparison.json()
            assert comparison_data["comparison_sha256"]
            assert comparison_data["schema_version"] == "1.2"
            assert "No trends, statistical tests, or scientific conclusions were generated." in comparison_data["markdown"]
            assert len(comparison_data["investigation_reports"]) == 2
            assert all(
                item["snapshot_sha256"]
                and "monitoring_context" not in item
                for item in comparison_data["investigation_reports"]
            )
            comparison_memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={
                    "artifact_types": ["monitoring_comparison"],
                    "mission_id": "monitor-mission",
                },
            )
            assert comparison_memory.status_code == 200
            assert comparison_memory.json()["total"] == 1
            assert comparison_memory.json()["artifacts"][0]["payload"]["comparison_sha256"] == comparison_data["comparison_sha256"]
            repeated_comparison = client.get(
                "/api/v1/platform/monitoring/schedules/temperature-watch/comparison"
            )
            assert repeated_comparison.status_code == 200
            assert repeated_comparison.json()["comparison_sha256"] == comparison_data["comparison_sha256"]
            assert second_runs[0]["run_id"] in comparison_memory.json()["artifacts"][0]["source_artifact_ids"]
            reproducibility_after_comparison = client.get(
                f"/api/v1/platform/investigations/{second_runs[0]['investigation_id']}/reproducibility"
            )
            assert reproducibility_after_comparison.status_code == 200
            comparison_bundle = reproducibility_after_comparison.json()
            assert comparison_bundle["schema_version"] == "1.3.0"
            assert len(comparison_bundle["monitoring_comparisons"]) == 1
            assert comparison_bundle["monitoring_comparisons"][0]["artifact_type"] == "monitoring_comparison"
            assert len(comparison_bundle["investigation_comparisons"]) == 1

            revised = client.patch(
                "/api/v1/platform/monitoring/schedules/temperature-watch",
                json={
                    "expected_revision": 1,
                    "name": "Every half hour",
                    "interval_seconds": 1800,
                    "overlap_policy": "allow",
                },
            )
            assert revised.status_code == 200, revised.text
            assert revised.json()["revision"] == 2
            assert revised.json()["overlap_policy"] == "allow"
            stale = client.patch(
                "/api/v1/platform/monitoring/schedules/temperature-watch",
                json={"expected_revision": 1, "name": "Stale update"},
            )
            assert stale.status_code == 409

            not_due = client.post("/api/v1/platform/monitoring/run-due")
            assert not_due.status_code == 200
            assert not_due.json() == []
            disabled = client.post(
                "/api/v1/platform/monitoring/schedules/temperature-watch/disable"
            )
            assert disabled.status_code == 200
            assert disabled.json()["enabled"] is False
            schedule_memory = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"artifact_types": ["monitoring_schedule"], "mission_id": "monitor-mission"},
            )
            assert schedule_memory.status_code == 200
            revisions = {
                item["artifact_id"] for item in schedule_memory.json()["artifacts"]
            }
            assert revisions == {
                "monitoring-schedule:temperature-watch:revision:1",
                "monitoring-schedule:temperature-watch:revision:2",
                "monitoring-schedule:temperature-watch:revision:3",
            }
            memory_events = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"artifact_types": ["monitoring_event"], "mission_id": "monitor-mission"},
            )
            assert memory_events.status_code == 200
            assert memory_events.json()["total"] == 7

            failing_schedule = client.post(
                "/api/v1/platform/monitoring/schedules",
                json={
                    "schedule_id": "failure-watch",
                    "mission_id": "monitor-mission",
                    "name": "Failure path verification",
                    "interval_seconds": 3600,
                    "next_run_at": (utc_now() - timedelta(seconds=1)).isoformat(),
                    "earth_query": {"requested_variables": ["air_temperature"]},
                },
            )
            assert failing_schedule.status_code == 201
            runtime = engine.platform_runtime
            execute_investigation = runtime.execute_investigation

            async def fail_execution(_investigation_id):
                raise RuntimeError("controlled failure for notification integration")

            runtime.execute_investigation = fail_execution
            try:
                failed_runs = client.post("/api/v1/platform/monitoring/run-due")
            finally:
                runtime.execute_investigation = execute_investigation
            assert failed_runs.status_code == 200
            assert failed_runs.json()[0]["status"] == "failed"
            notifications = client.get(
                "/api/v1/platform/monitoring/notifications",
                params={"schedule_id": "failure-watch", "unread_only": "true"},
            )
            assert notifications.status_code == 200
            assert len(notifications.json()) == 1
            notification_id = notifications.json()[0]["notification_id"]
            acknowledged = client.post(
                f"/api/v1/platform/monitoring/notifications/{notification_id}/acknowledge"
            )
            assert acknowledged.status_code == 200
            assert acknowledged.json()["status"] == "acknowledged"
            memory_notifications = client.post(
                "/api/v1/platform/earth-memory/search",
                json={"artifact_types": ["monitoring_notification"], "mission_id": "monitor-mission"},
            )
            assert memory_notifications.status_code == 200
            assert memory_notifications.json()["total"] == 2
    finally:
        set_engine(None)


def test_pending_investigation_can_be_cancelled_through_platform_api():
    engine = SatQueryEngine(get_settings())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            assert 'id="cancelInvestigation"' in client.get("/").text
            mission = client.post(
                "/api/v1/platform/missions",
                json={"name": "Cancel test", "objective": "Exercise lifecycle cancellation"},
            ).json()
            investigation = client.post(
                f"/api/v1/platform/missions/{mission['mission_id']}/investigations",
                json={"requested_variables": ["air_temperature"]},
            ).json()
            response = client.post(
                f"/api/v1/platform/investigations/{investigation['investigation_id']}/cancel"
            )

            assert response.status_code == 200
            assert response.json()["status"] == "cancelled"
            assert client.get(
                f"/api/v1/platform/investigations/{investigation['investigation_id']}"
            ).json()["status"] == "cancelled"
    finally:
        set_engine(None)


def test_failed_investigation_resumes_through_api_and_exposes_persisted_events():
    engine = SatQueryEngine(get_settings())
    attempts = 0

    def retryable_handler(_context):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("recoverable fixture failure")
        return {"result": "completed"}

    runtime = engine.platform_runtime
    runtime.register_task_handler("fixture.retryable", retryable_handler)
    mission = Mission(name="Resume test", objective="Validate restart-safe execution")
    runtime.mission_service.create(mission)
    investigation = runtime.mission_service.create_investigation(
        mission.mission_id,
        (Task(task_id="retry", handler="fixture.retryable", retry_safe=True),),
    )
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            first = client.post(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/execute"
            )
            assert first.status_code == 200
            assert first.json()["status"] == "failed"
            execution_id = first.json()["plan_id"]

            resumed = client.post(
                f"/api/v1/platform/investigations/{investigation.investigation_id}/resume"
            )
            assert resumed.status_code == 200
            assert resumed.json()["status"] == "succeeded"
            assert resumed.json()["plan_id"] == execution_id
            assert attempts == 2

            journal = client.get(
                f"/api/v1/platform/executions/{execution_id}/events"
            ).json()
            assert any(
                event["event_type"] == "execution.resumed"
                for event in journal["events"]
            )
            assert journal["next_sequence"] == journal["events"][-1]["sequence"]
    finally:
        set_engine(None)


def test_reasoning_extension_failure_does_not_fail_observation_execution():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    engine.platform_runtime.scientific_reasoning.operators.register(
        _FailingScientificOperator()
    )
    set_engine(engine)
    query = {
        "point": [80.15, 12.84],
        "temporal_start": "2024-01-01T00:00:00Z",
        "temporal_end": "2024-01-31T23:59:59Z",
        "requested_variables": ["air_temperature"],
    }
    try:
        with TestClient(create_app(get_settings())) as client:
            created = client.post(
                "/api/v1/platform/investigate",
                json={"question": "Measure air temperature", "earth_query": query},
            )
            investigation_id = created.json()["investigation"]["investigation_id"]

            executed = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/execute"
            )
            assert executed.status_code == 200
            inspected = client.get(
                f"/api/v1/platform/investigations/{investigation_id}"
            )
            assert inspected.json()["status"] == "completed"

            reasoning = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reasoning"
            ).json()
            failure = next(
                item
                for item in reasoning["operator_results"]
                if item["operator_id"] == "fixture.failing-operator"
            )
            assert failure["status"] == "error"
            assert failure["statement"].startswith("Operator failed with RuntimeError")
    finally:
        set_engine(None)


def test_scientific_planner_creates_reviewable_plan_then_executable_investigation():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    query = {
        "point": [80.15, 12.84],
        "temporal_start": "2024-01-01T00:00:00Z",
        "temporal_end": "2024-01-31T23:59:59Z",
        "requested_variables": ["air_temperature"],
    }
    try:
        with TestClient(create_app(get_settings())) as client:
            assert 'id="executionGraph"' in client.get("/").text
            registered_workflows = client.get(
                "/api/v1/platform/execution/workflows"
            ).json()
            assert registered_workflows["workflow_compilers"] == [{
                "workflow_id": "satquery.scientific-investigation",
                "version": "1.2.0",
            }]
            planned = client.post(
                "/api/v1/platform/planning/investigations",
                json={
                    "question": "Measure air temperature near the study site",
                    "earth_query": query,
                },
            )
            assert planned.status_code == 200
            plan = planned.json()
            assert plan["status"] == "ready"
            assert plan["candidate_plans"][0]["selected_implementations"] == [
                "fixture-atmosphere"
            ]
            assert (
                plan["candidate_plans"][0]["provider_assessments"][0]["confidence"]
                is None
            )
            assert plan["candidate_plans"][0]["cost_estimate"]["status"] == "unknown"
            assert plan["reproducibility"]["capability_matrix_revision"]

            created = client.post(
                "/api/v1/platform/investigate",
                json={
                    "question": "Test whether air temperature increased near the study site",
                    "earth_query": query,
                },
            )
            assert created.status_code == 201
            body = created.json()
            assert body["state"] == "ready"
            assert (
                body["investigation"]["investigation_plan_id"]
                == body["plan"]["plan_id"]
            )
            assert (
                body["investigation"]["investigation_design_id"]
                == body["design"]["design_id"]
            )
            assert body["design"]["status"] == "ready_for_acquisition"
            assert len(body["investigation"]["tasks"]) == 1

            investigation_id = body["investigation"]["investigation_id"]
            executed = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/execute"
            )
            assert executed.status_code == 200
            assert executed.json()["metadata"]["workflow_id"] == (
                "satquery.scientific-investigation"
            )
            workflow_tasks = {
                item["handler"]: item
                for item in executed.json()["tasks"]
            }
            assert set(workflow_tasks) == {
                "earth.observe", "earth.objects.extract", "earth.assess", "earth.reason"
            }
            assert workflow_tasks["earth.objects.extract"]["depends_on"] == [
                body["investigation"]["tasks"][0]["task_id"]
            ]
            assert workflow_tasks["earth.objects.extract"]["status"] == "succeeded"
            assert workflow_tasks["earth.objects.extract"]["output"][
                "materialized_object_ids"
            ] == []
            assert workflow_tasks["earth.assess"]["depends_on"] == [
                body["investigation"]["tasks"][0]["task_id"]
            ]
            assert workflow_tasks["earth.reason"]["depends_on"][-1] == (
                workflow_tasks["earth.assess"]["task_id"]
            )
            assert workflow_tasks["earth.objects.extract"]["task_id"] in (
                workflow_tasks["earth.reason"]["depends_on"]
            )
            assert workflow_tasks["earth.assess"]["status"] == "succeeded"
            assert workflow_tasks["earth.reason"]["status"] == "succeeded"
            execution_id = executed.json()["plan_id"]
            journal = client.get(
                f"/api/v1/platform/executions/{execution_id}/events"
            )
            assert journal.status_code == 200
            assert any(
                item["event_type"] == "task.checkpointed"
                for item in journal.json()["events"]
            )
            runtime = engine.platform_runtime
            runtime._execution_results.clear()
            replayed = runtime.get_execution_result(execution_id)
            replayed_outputs = {item.handler: item.output for item in replayed.tasks}
            assert isinstance(replayed_outputs["earth.objects.extract"], EarthObjectExtractionBatch)
            assert isinstance(replayed_outputs["earth.assess"], EvidenceAssessment)
            assert isinstance(replayed_outputs["earth.reason"], ScientificReasoningReport)
            assert (
                client.get(f"/api/v1/platform/executions/{execution_id}").status_code
                == 200
            )
            observations = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/observations"
            )
            assert observations.status_code == 200
            assert observations.json()[0]["source_id"] == "fixture-record-1"
            provenance = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/provenance"
            )
            assert provenance.status_code == 200
            intelligence = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/intelligence"
            )
            assert intelligence.status_code == 200
            assert len(intelligence.json()["assessment"]["hypotheses"]) == 1
            assert (
                intelligence.json()["assessment"]["hypotheses"][0]["status"]
                == "not_evaluated"
            )
            assert intelligence.json()["assessment"]["status"] == "coverage_partial"
            reasoning = intelligence.json()["reasoning"]
            assert reasoning["conclusion"]["status"] == "unresolved"
            assert reasoning["conclusion"]["confidence"] is None
            hypothesis_lifecycle = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses"
            )
            assert hypothesis_lifecycle.status_code == 200
            lifecycle_body = hypothesis_lifecycle.json()
            assert len(lifecycle_body["graph"]["hypotheses"]) == 1
            hypothesis = lifecycle_body["graph"]["hypotheses"][0]
            assert hypothesis["lifecycle"] == "active"
            assert len(lifecycle_body["events"]) == 2
            transitioned = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses/{hypothesis['hypothesis_id']}/transitions",
                json={
                    "expected_version": hypothesis["version"],
                    "status": "under_review",
                    "actor": "test-reviewer",
                    "rationale": "Reviewing evidence sufficiency.",
                },
            )
            assert transitioned.status_code == 200
            assert transitioned.json()["hypothesis"]["version"] == hypothesis["version"] + 1
            assert transitioned.json()["hypothesis"]["lifecycle"] == "under_review"
            added_hypothesis = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses",
                json={
                    "hypothesis_id": "review-alternative",
                    "proposition": "The observed change reflects sampling variability.",
                    "source_text": "Explicit reviewer hypothesis",
                    "origin": "explicit",
                    "competing_group_id": "temperature-change-alternatives",
                    "actor": "test-reviewer",
                    "rationale": "Record an explicit alternative for review.",
                },
            )
            assert added_hypothesis.status_code == 201
            assert added_hypothesis.json()["hypothesis"]["lifecycle"] == "proposed"
            current_hypotheses = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses"
            ).json()["graph"]["hypotheses"]
            assert {item["hypothesis_id"] for item in current_hypotheses} == {
                hypothesis["hypothesis_id"],
                "review-alternative",
            }
            composite = client.post(
                f"/api/v1/platform/investigations/{investigation_id}/hypotheses",
                json={
                    "hypothesis_id": "composite-review",
                    "proposition": "The temperature change and sampling explanation jointly apply.",
                    "source_text": "Explicit composite hypothesis",
                    "origin": "composite",
                    "parent_hypothesis_ids": [
                        hypothesis["hypothesis_id"],
                        "review-alternative",
                    ],
                    "composition": "all",
                    "actor": "test-reviewer",
                    "rationale": "Preserve a declared composite without evaluating its truth.",
                },
            )
            assert composite.status_code == 201
            assert composite.json()["hypothesis"]["origin"] == "composite"
            standalone = client.get(
                f"/api/v1/platform/investigations/{investigation_id}/reasoning"
            )
            assert standalone.status_code == 200
            assert standalone.json()["reasoning_id"] == reasoning["reasoning_id"]
    finally:
        set_engine(None)


def test_investigation_with_partial_observation_coverage_is_not_executable():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    query = {
        "point": [80.15, 12.84],
        "temporal_start": "2024-01-01T00:00:00Z",
        "temporal_end": "2024-01-31T23:59:59Z",
        "requested_variables": ["air_temperature", "precipitation"],
    }
    try:
        with TestClient(create_app(get_settings())) as client:
            created = client.post(
                "/api/v1/platform/investigate",
                json={
                    "question": "Measure air temperature and precipitation",
                    "earth_query": query,
                },
            )

            assert created.status_code == 201
            body = created.json()
            assert body["state"] == "no_capability"
            assert body["plan"]["candidate_plans"][0]["perception_plan"][
                "unavailable_variables"
            ] == ["precipitation_amount"]
            assert body["investigation"]["tasks"] == []
    finally:
        set_engine(None)


def test_intelligence_design_api_returns_graph_without_acquiring_observations():
    engine = SatQueryEngine(get_settings())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            designed = client.post(
                "/api/v1/platform/intelligence/design",
                json={
                    "question": "Measure air temperature globally during 2024",
                    "earth_query": {
                        "region": "*",
                        "temporal_start": "2024-01-01T00:00:00Z",
                        "temporal_end": "2024-12-31T23:59:59Z",
                        "requested_variables": ["air_temperature"],
                    },
                },
            )

            assert designed.status_code == 200
            body = designed.json()
            assert body["design"]["plan_id"] == body["plan"]["plan_id"]
            assert body["design"]["evidence_graph"]["nodes"]
            assert all(
                edge["source_node_id"]
                in {
                    node["node_id"]
                    for node in body["design"]["evidence_graph"]["nodes"]
                }
                for edge in body["design"]["evidence_graph"]["edges"]
            )
            assert engine.platform_runtime.execution_results() == ()
    finally:
        set_engine(None)


def test_connector_health_api_separates_local_status_from_explicit_probes():
    engine = SatQueryEngine(get_settings())
    engine.platform_runtime.register_connector(_AtmosphericFixture())
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            local = client.get("/api/v1/platform/connectors/health")
            assert local.status_code == 200
            assert local.json()[0]["connector_id"] == "fixture-atmosphere"
            assert "last_error" not in local.json()[0]

            probed = client.post(
                "/api/v1/platform/connectors/fixture-atmosphere/health-check"
            )
            assert probed.status_code == 200
            assert probed.json()["connector_id"] == "fixture-atmosphere"
    finally:
        set_engine(None)


def test_legacy_image_analysis_runs_as_a_platform_investigation():
    engine = SatQueryEngine(get_settings())
    response = QueryResponse.model_construct(
        request_id="sq-test",
        query="describe this image",
        answer="A fixture response.",
        intent=Intent.CAPTION,
        tools_used=[],
        backend=BackendKind.PRACTICAL,
        images=[],
        results=[],
        plan=object(),
        latency_ms=0,
    )
    engine.answer = lambda **_kwargs: response

    result = asyncio.run(
        engine.answer_on_platform("describe this image", image_paths=("image.png",))
    )

    assert result.answer == response.answer
    assert result.platform_mission_id
    assert result.platform_investigation_id
    assert result.platform_execution_id
    mission = engine.platform_runtime.mission_service.list()[0]
    investigations = engine.platform_runtime.investigation_service.list_for_mission(
        mission.mission_id
    )
    assert mission.status.value == "completed"
    assert mission.finished_at is not None
    assert len(investigations) == 1
    assert investigations[0].status.value == "completed"
    assert investigations[0].result_ids
    asyncio.run(engine.close())


def test_image_api_executes_through_platform_and_returns_lifecycle_ids():
    engine = SatQueryEngine(get_settings())
    response = QueryResponse(
        request_id="sq-api-test",
        query="describe this image",
        answer="A fixture response.",
        intent=Intent.CAPTION,
        tools_used=[],
        backend=BackendKind.PRACTICAL,
        images=[],
        results=[],
        plan=QueryPlan(
            intent=Intent.CAPTION,
            steps=[],
            router="fixture",
            rationale="deterministic API integration fixture",
        ),
        latency_ms=0,
    )
    engine.answer = lambda **_kwargs: response
    set_engine(engine)
    try:
        with TestClient(create_app(get_settings())) as client:
            result = client.post(
                "/api/v1/query",
                data={"query": "describe this image"},
                files={"files": ("scene.png", b"fixture image bytes", "image/png")},
            )
            assert result.status_code == 200
            body = result.json()
            assert body["platform_mission_id"]
            assert body["platform_investigation_id"]
            assert body["platform_execution_id"]
            inspection = client.get(
                f"/api/v1/platform/investigations/{body['platform_investigation_id']}"
            )
            assert inspection.status_code == 200
            assert inspection.json()["status"] == "completed"
    finally:
        set_engine(None)


def test_connector_manifest_registers_adapters_without_opening_network_clients():
    runtime = PlatformRuntime()
    manifest = Path(__file__).parents[1] / "configs" / "connectors.example.json"

    registered = load_configured_connectors(runtime, config_path=manifest)

    assert registered == (
        "earth-search",
        "nasa-earthdata",
        "nasa-power-daily",
        "noaa-coops-water-level",
        "open-meteo.climate",
        "open-meteo.historical_weather",
        "open-meteo.hydrology",
        "open-meteo.weather",
        "openstreetmap-overpass",
        "usgs-3dep-epqs",
        "usgs-water-daily",
    )
    declared_weather = runtime.registries.datasets.get(
        "open-meteo.weather", "weather-forecast"
    )
    assert declared_weather.variables
    assert declared_weather.modalities == ("atmospheric",)
    assert declared_weather.units["air_temperature_2m"] == "°C"
    assert declared_weather.supports_forecast is True
    assert declared_weather.supports_historical is False
    noaa_dataset = runtime.registries.datasets.get(
        "noaa-coops-water-level", "noaa-coops-water-level"
    )
    assert noaa_dataset.modalities == ("oceanic",)
    assert noaa_dataset.variables == ("coastal_water_level",)
    assert noaa_dataset.units["coastal_water_level"] == "m"
    assert noaa_dataset.access_policy["station_id_required"] is True
    assert runtime.perception_engine.plan(
        EarthQuery(point=(80.15, 12.84), requested_variables=("air_temperature_2m",))
    ).selected_modalities == ("atmospheric",)
    asyncio.run(runtime.close())
