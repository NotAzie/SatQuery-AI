from datetime import datetime, timezone

import pytest

from satquery.platform.capabilities import build_earth_capability_matrix
from satquery.platform.contracts import ConnectorMetadata, DatasetMetadata, EarthQuery, TemporalExtent
from satquery.platform.scientific_knowledge import (
    EvidenceAggregationMetadata,
    EvidenceDependencyEdge,
    EvidenceWeightAssessment,
    ScientificMethodCapabilityPlanner,
    ScientificMethodManifest,
    ScientificMethodRegistry,
    ScientificOperatorManifest,
    ScientificOperatorManifestRegistry,
    ScientificWorkflowInstance,
    earth_science_workflow_templates,
)
from satquery.platform.scientific_methods import ScientificReference, ScientificRuleManifest


def _method(status="validated"):
    references = (ScientificReference(
        reference_id="fixture-ref", title="Fixture validation reference",
        citation="Test fixture only", uri="https://example.test/fixture",
    ),) if status == "validated" else ()
    digest = "a" * 64
    return ScientificMethodManifest(
        method_id="test.method", version="1.0.0", domain="climatology",
        rule=ScientificRuleManifest(
            rule_id="test.method", version="1.0.0", name="Test method",
            domain="climatology", description="Fixture method",
            validation_status=status,
            scientific_references=references,
            implementation_sha256=digest if status == "validated" else None,
            validation_record=(
                {
                    "validation_id": "fixture-validation", "validation_status": "validated",
                    "validated_by": "test-suite", "validation_suite_id": "fixture-suite",
                    "validation_suite_sha256": "b" * 64,
                    "implementation_sha256": digest, "reference_ids": ("fixture-ref",),
                } if status == "validated" else None
            ),
            applicability={"required_variables": ("air_temperature",), "required_modalities": ("atmospheric",)},
            uncertainty_propagation={"status": "not_required" if status == "validated" else "unsupported"},
            output_semantics=("diagnostic",),
        ),
        expected_outputs=("diagnostic",),
    )


def test_method_registry_is_versioned_stable_and_rejects_duplicates():
    registry = ScientificMethodRegistry((_method("draft"),))
    revision = registry.revision
    assert registry.get("test.method", "1.0.0").rule.validation_status == "draft"
    assert revision == ScientificMethodRegistry((_method("draft"),)).revision
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_method("draft"))


def test_domain_and_workflow_catalogs_are_explicit_empty_scaffolds():
    domains = ScientificMethodRegistry().domain_catalog()
    assert len(domains) == 10
    assert all(item.status == "no_validated_methods_registered" for item in domains)
    templates = earth_science_workflow_templates()
    assert len(templates) == 10
    assert all(item.status == "requires_configuration" for item in templates)
    assert all(not item.methods and not item.conclusions for item in templates)
    assert len(ScientificOperatorManifestRegistry().catalog()) == 10
    drought = next(item for item in templates if item.template_id.endswith("drought"))
    with pytest.raises(ValueError, match="cannot declare methods or conclusions"):
        type(drought).model_validate({**drought.model_dump(), "conclusions": ("Drought occurred",)})


def test_diagnostic_operator_cannot_claim_method_semantics_without_backing():
    operator = ScientificOperatorManifest(
        operator_id="trend", version="1", operation="trend_detection"
    )
    assert operator.output_semantics == "diagnostic_only"
    with pytest.raises(ValueError, match="diagnostic-only"):
        ScientificOperatorManifest(
            operator_id="trend", version="1", operation="trend_detection",
            output_semantics="scientific_conclusion",
        )


def test_evidence_weight_and_aggregation_do_not_infer_numeric_confidence():
    assessment = EvidenceWeightAssessment(
        assessment_id="assessment", evidence_id="obs-1", basis="reviewed metadata",
        assessor="researcher", evidence_strength="moderate",
    )
    assert assessment.numeric_weight is None and assessment.probability is None
    assert EvidenceDependencyEdge(
        source_evidence_id="obs-1", target_evidence_id="obs-2",
        relation="unknown", basis="independence not assessed",
    ).relation == "unknown"
    with pytest.raises(ValueError, match="explicit versioned method"):
        EvidenceAggregationMetadata(
            aggregation_id="combined", evidence_ids=("obs-1",),
            status="aggregated_by_validated_method",
        )


def test_method_preflight_rejects_unvalidated_and_missing_capability():
    matrix = build_earth_capability_matrix((), ())
    query = EarthQuery(requested_variables=("air_temperature",), requested_modalities=("atmospheric",))
    result = ScientificMethodCapabilityPlanner().assess(_method("draft"), query, matrix)
    assert result.status == "rejected"
    assert "validation status is draft" in result.unmet_requirements[0]
    assert any("no declared dataset" in item for item in result.unmet_requirements)


def test_method_preflight_eligible_only_when_declared_dataset_covers_inputs():
    connector = ConnectorMetadata(connector_id="fixture", name="Fixture", version="1")
    dataset = DatasetMetadata(
        connector_id="fixture", dataset_id="weather", provider="Example",
        variables=("air_temperature",), modalities=("atmospheric",),
        temporal_coverage=TemporalExtent(
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
    )
    matrix = build_earth_capability_matrix((connector,), (dataset,))
    query = EarthQuery(
        requested_variables=("air_temperature",), requested_modalities=("atmospheric",),
        temporal_start=datetime(2021, 1, 1, tzinfo=timezone.utc),
        temporal_end=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    result = ScientificMethodCapabilityPlanner().assess(_method(), query, matrix)
    assert result.status == "eligible"
    assert result.compatible_dataset_ids == ("weather",)
    assert result.capability_matrix_revision == matrix.revision


def test_method_preflight_is_indeterminate_when_requested_area_is_unverifiable():
    connector = ConnectorMetadata(connector_id="fixture", name="Fixture", version="1")
    dataset = DatasetMetadata(
        connector_id="fixture", dataset_id="weather", provider="Example",
        variables=("air_temperature",), modalities=("atmospheric",),
    )
    matrix = build_earth_capability_matrix((connector,), (dataset,))
    query = EarthQuery(
        bbox=(10, 10, 11, 11), requested_variables=("air_temperature",),
        requested_modalities=("atmospheric",),
    )
    result = ScientificMethodCapabilityPlanner().assess(_method(), query, matrix)
    assert result.status == "indeterminate"
    assert "spatial coverage cannot be verified" in result.unmet_requirements[0]


def test_method_preflight_does_not_claim_readiness_without_required_observation_count():
    connector = ConnectorMetadata(connector_id="fixture", name="Fixture", version="1")
    dataset = DatasetMetadata(
        connector_id="fixture", dataset_id="weather", provider="Example",
        variables=("air_temperature",), modalities=("atmospheric",),
    )
    method = _method()
    method = method.model_copy(update={
        "rule": method.rule.model_copy(update={
            "applicability": method.rule.applicability.model_copy(update={"minimum_observations": 2})
        })
    })
    result = ScientificMethodCapabilityPlanner().assess(
        method,
        EarthQuery(requested_variables=("air_temperature",), requested_modalities=("atmospheric",)),
        build_earth_capability_matrix((connector,), (dataset,)),
    )
    assert result.status == "indeterminate"
    assert any("minimum observation count" in item for item in result.unmet_requirements)


def test_method_preflight_requires_explicit_dataset_trust_scope():
    connector = ConnectorMetadata(connector_id="fixture", name="Fixture", version="1")
    dataset = DatasetMetadata(
        connector_id="fixture", dataset_id="weather", provider="Example",
        variables=("air_temperature",), modalities=("atmospheric",),
    )
    method = _method()
    compatibility = method.rule.dataset_compatibility.model_copy(
        update={"required_trust_scope_ids": ("temperature-calibration",)}
    )
    method = method.model_copy(update={
        "rule": method.rule.model_copy(update={"dataset_compatibility": compatibility})
    })
    result = ScientificMethodCapabilityPlanner().assess(
        method,
        EarthQuery(requested_variables=("air_temperature",), requested_modalities=("atmospheric",)),
        build_earth_capability_matrix((connector,), (dataset,)),
    )
    assert result.status == "indeterminate"
    assert any("no trusted assessment" in item for item in result.unmet_requirements)


def test_workflow_instance_contract_cannot_contain_scientific_conclusion():
    instance = ScientificWorkflowInstance(
        instance_id="instance", template_id="earth-investigation.drought",
        template_version="1.0.0", unresolved_configuration=("area_of_interest",),
    )
    assert instance.conclusions == ()
