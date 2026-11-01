from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from satquery.platform.contracts import (
    CanonicalMeasurement,
    DatasetReference,
    EarthObjectCandidate,
    EarthObjectRelationship,
    Observation,
    TemporalExtent,
)
from satquery.platform.earth_object_benchmarks import (
    EarthObjectExtractionBenchmarkRunner,
)
from satquery.platform.earth_objects import (
    EarthObjectCatalog,
    EarthObjectDeclaration,
    EarthObjectExtractionPipeline,
    EarthObjectMaterializer,
    EarthObjectRevisionTransition,
)
from satquery.platform.scientific_governance import BenchmarkCase, canonical_digest


def _observation(
    observation_id: str,
    *,
    identity_value: str = "feature-7",
    object_type: str = "earth:WaterBody",
    declared_by: str = "source-a",
    mapping_id: str = "source-mapping@1.0.0",
    geometry: dict | None = None,
    time: datetime | None = None,
    attributes: dict | None = None,
) -> Observation:
    time = time or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return Observation(
        observation_id=observation_id,
        source_id=f"source-record:{observation_id}",
        dataset=DatasetReference(
            connector_id=declared_by,
            dataset_id="features",
            version="v1",
        ),
        observed_at=time,
        temporal_extent=TemporalExtent(start=time, end=time),
        geometry=geometry or {"type": "Point", "coordinates": [2.0, 1.0]},
        crs="OGC:CRS84",
        observation_type="vector_feature",
        earth_object_candidate=EarthObjectCandidate(
            identity_namespace="example.org/features",
            identity_value=identity_value,
            object_type=object_type,
            declared_by=declared_by,
            mapping_id=mapping_id,
            provenance={"source_attributes": attributes or {"name": "sample"}},
        ),
        canonical_measurements=(
            CanonicalMeasurement(
                canonical_variable="surface_water_level",
                value=1.25,
                unit="m",
                source_variable="level",
                source_unit="m",
                semantic_status="resolved",
            ),
        ),
        modalities=("hydrological",),
        provenance={"provider_record": observation_id},
        source_document={"record": observation_id},
    )


def test_extraction_is_order_independent_and_combines_shared_declared_identity():
    first = _observation("obs-a")
    second = _observation(
        "obs-b",
        declared_by="source-b",
        mapping_id="independent-mapping@2.0.0",
        time=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )
    pipeline = EarthObjectExtractionPipeline()

    forward = pipeline.extract((first, second), investigation_id="investigation-1")
    reverse = pipeline.extract((second, first), investigation_id="investigation-1")

    assert forward.model_dump(mode="json") == reverse.model_dump(mode="json")
    assert len(forward.declarations) == 1
    declaration = forward.declarations[0]
    metadata = declaration.declared_provenance["extraction_pipeline"]
    assert metadata["method_identities"] == (
        "independent-mapping@2.0.0",
        "source-mapping@1.0.0",
    )
    assert metadata["source_declarers"] == ("source-a", "source-b")
    assert set(declaration.observation_ids) == {"obs-a", "obs-b"}
    assert declaration.investigation_id == "investigation-1"


def test_extraction_rejects_duplicate_observation_identity():
    observation = _observation("obs-a")
    with pytest.raises(ValueError, match="duplicate observation IDs"):
        EarthObjectExtractionPipeline().extract((observation, observation))


def test_conflicting_source_types_are_reported_without_emitting_an_object():
    batch = EarthObjectExtractionPipeline().extract(
        (
            _observation("obs-a", object_type="earth:WaterBody"),
            _observation("obs-b", object_type="earth:River"),
        )
    )

    assert batch.declarations == ()
    assert len(batch.issues) == 1
    assert batch.issues[0].code == "conflicting_declaration"
    assert batch.issues[0].observation_ids == ("obs-a", "obs-b")


def test_materialization_preserves_source_data_without_inventing_semantics():
    observation = _observation(
        "obs-a", attributes={"name": "Lake A", "water": "reservoir"}
    )
    declaration = EarthObjectExtractionPipeline().extract((observation,)).declarations[0]

    item = EarthObjectMaterializer().materialize(declaration, (observation,))
    replay = EarthObjectMaterializer().materialize(declaration, (observation,))

    assert item == replay
    assert item.content_sha256 == replay.content_sha256
    assert item.object_type == "earth:WaterBody"
    assert item.lifecycle == "unknown"
    assert item.properties == {}
    assert item.measurements[0].observation_id == observation.observation_id
    assert item.property_assertions[0].observation_ids == (observation.observation_id,)
    assert {record.source_key: record.value for record in item.source_attributes} == {
        "name": "Lake A",
        "water": "reservoir",
    }
    assert all(record.uncertainty == {} for record in item.source_attributes)
    assert all(
        record.provenance["semantic_status"] == "unmapped_source_attribute"
        for record in item.source_attributes
    )
    assert item.provenance["source_records"] == (observation.model_dump(mode="json"),)


def test_geometry_and_temporal_validity_remain_unknown_when_sources_disagree():
    first = _observation("obs-a")
    second = _observation(
        "obs-b",
        geometry={"type": "Point", "coordinates": [3.0, 1.0]},
        time=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )
    declaration = EarthObjectExtractionPipeline().extract((first, second)).declarations[0]

    item = EarthObjectMaterializer().materialize(declaration, (first, second))

    assert item.geometry is None
    assert item.crs == "OGC:CRS84"
    assert item.temporal_validity is None
    assert len(item.provenance["source_records"]) == 2


def test_revision_extends_prior_source_lineage_and_catalog_rejects_branching():
    first = _observation("obs-a")
    first_declaration = EarthObjectExtractionPipeline().extract((first,)).declarations[0]
    materializer = EarthObjectMaterializer()
    revision_one = materializer.materialize(first_declaration, (first,))
    catalog = EarthObjectCatalog()
    catalog.put(revision_one)

    second = _observation(
        "obs-b", time=datetime(2025, 1, 2, tzinfo=timezone.utc)
    )
    second_declaration = EarthObjectExtractionPipeline().extract((second,)).declarations[0]
    revision_two = materializer.materialize(
        second_declaration, (second,), previous=revision_one
    )
    catalog.put(revision_two)
    assert revision_two.revision == 2
    assert revision_two.supersedes_object_id == revision_one.object_id
    assert set(revision_two.source_observation_ids) == {"obs-a", "obs-b"}

    third = _observation(
        "obs-c", time=datetime(2025, 1, 3, tzinfo=timezone.utc)
    )
    third_declaration = EarthObjectExtractionPipeline().extract((third,)).declarations[0]
    branch = materializer.materialize(
        third_declaration, (third,), previous=revision_one
    )
    assert branch.revision == 2
    assert branch.object_id != revision_two.object_id
    with pytest.raises(ValueError, match="does not extend the latest catalog revision"):
        catalog.put(branch)


def test_lifecycle_and_reclassification_revisions_require_explicit_supported_transitions():
    observation = _observation("obs-a")
    declaration = EarthObjectExtractionPipeline().extract((observation,)).declarations[0]
    materializer = EarthObjectMaterializer()
    initial = materializer.materialize(declaration, (observation,))
    with pytest.raises(ValueError, match="requires a matching explicit reclassification"):
        materializer.materialize(
            declaration.model_copy(update={"object_type": "earth:River"}),
            (observation,),
            previous=initial,
        )

    transition = EarthObjectRevisionTransition(
        prior_object_id=initial.object_id,
        transition_type="reclassification",
        actor="reviewer-1",
        rationale="The source record is explicitly typed as a river feature.",
        observation_ids=(observation.observation_id,),
        prior_object_type=initial.object_type,
        new_object_type="earth:River",
    )
    revised_declaration = EarthObjectDeclaration.model_validate(
        {
            **declaration.model_dump(mode="json"),
            "object_type": "earth:River",
            "declared_by": transition.actor,
            "revision_transition": transition.model_dump(mode="json"),
        }
    )
    revised = materializer.materialize(
        revised_declaration, (observation,), previous=initial
    )
    assert revised.revision == 2
    assert revised.supersedes_object_id == initial.object_id
    assert revised.object_type == "earth:River"
    assert revised.provenance["declaration"]["revision_transition"]["actor"] == "reviewer-1"

    lifecycle_transition = EarthObjectRevisionTransition(
        prior_object_id=revised.object_id,
        transition_type="lifecycle",
        actor="reviewer-2",
        rationale="The source owner reported this feature is inactive.",
        observation_ids=(observation.observation_id,),
        prior_lifecycle="unknown",
        new_lifecycle="inactive",
    )
    lifecycle_declaration = EarthObjectDeclaration.model_validate(
        {
            **revised_declaration.model_dump(mode="json"),
            "lifecycle": "inactive",
            "revision_transition": lifecycle_transition.model_dump(mode="json"),
        }
    )
    inactive = materializer.materialize(
        lifecycle_declaration, (observation,), previous=revised
    )
    assert inactive.revision == 3
    assert inactive.lifecycle == "inactive"
    catalog = EarthObjectCatalog()
    catalog.put(initial)
    catalog.put(revised)
    catalog.put(inactive)
    assert catalog.all() == (initial, revised, inactive)
    assert catalog.current() == (inactive,)


def test_relationship_requires_existing_object_evidence_or_observation_links():
    observations = (
        _observation("obs-a", identity_value="feature-a"),
        _observation("obs-b", identity_value="feature-b"),
    )
    declarations = EarthObjectExtractionPipeline().extract(observations).declarations
    materializer = EarthObjectMaterializer()
    objects = tuple(
        materializer.materialize(
            declaration,
            (observation,),
        )
        for declaration, observation in zip(declarations, observations, strict=True)
    )
    catalog = EarthObjectCatalog()
    for item in objects:
        catalog.put(item)

    relation = EarthObjectRelationship(
        relationship_id="relationship-1",
        source_object_id=objects[0].object_id,
        target_object_id=objects[1].object_id,
        relation="near",
        observation_ids=("obs-a", "obs-b"),
        asserted_by="reviewer",
    )
    catalog.put_relationship(relation)
    assert catalog.graph().relationships == (relation,)

    invalid = relation.model_copy(
        update={"relationship_id": "relationship-2", "observation_ids": ("unknown",)}
    )
    with pytest.raises(ValueError, match="absent from its endpoint objects"):
        catalog.put_relationship(invalid)


def test_reference_bundle_runner_is_reproducible_and_not_a_scientific_certification():
    observation = _observation("obs-a")
    dataset_bytes = json.dumps(
        {
            "schema_version": "satquery.earth-object-observations.v1",
            "observations": [observation.model_dump(mode="json")],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    input_manifest = {
        "investigation_id": "reference-investigation-1",
        "validation_dataset_ids": ["reference-observations"],
    }
    case = BenchmarkCase(
        case_id="case-1",
        reference_investigation_id="reference-investigation-1",
        input_manifest=input_manifest,
        input_sha256=canonical_digest(input_manifest),
        expected_output={},
        expected_output_sha256=canonical_digest({}),
        validation_dataset_ids=("reference-observations",),
    )
    runner = EarthObjectExtractionBenchmarkRunner(
        implementation_sha256="a" * 64
    )

    first = runner.execute(case, {"reference-observations": dataset_bytes})
    second = runner.execute(case, {"reference-observations": dataset_bytes})

    assert first == second
    assert len(first["earth_objects"]) == 1
    assert first["earth_objects"][0]["object_type"] == "earth:WaterBody"
    assert len(first["output_sha256"]) == 64
    assert first["earth_objects"][0]["provenance"]["declared_provenance"][
        "extraction_pipeline"
    ]["validation_status"] == "not_independently_validated"
