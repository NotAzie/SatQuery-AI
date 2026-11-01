"""Scientific knowledge catalogs and configuration-only workflow scaffolds.

Registries describe executable scientific assets but do not certify them. Domain
namespaces and investigation templates are deliberately empty scaffolds until
independently validated methods and study-specific requirements are supplied.
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, Literal

from pydantic import Field, model_validator

from .capabilities import EarthCapabilityMatrix
from .contracts import Contract, EarthQuery
from .scientific_inference import DatasetTrustAssertion
from .scientific_methods import ScientificRuleManifest
from .spatial import query_intersects_coverage

EARTH_SCIENCE_DOMAINS = (
    "hydrology", "climatology", "ecology", "geology", "cryosphere",
    "oceanography", "disaster_science", "atmospheric_science",
    "urban_analysis", "agriculture",
)


class ScientificMethodManifest(Contract):
    """Stable knowledge catalog entry referencing an executable rule contract."""

    method_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    rule: ScientificRuleManifest
    expected_outputs: tuple[str, ...] = ()
    reproducibility_requirements: tuple[str, ...] = ()
    required_dataset_ids: tuple[str, ...] = ()
    required_uncertainty_categories: tuple[str, ...] = ()
    minimum_spatial_resolution: float | None = Field(default=None, gt=0)
    maximum_spatial_resolution: float | None = Field(default=None, gt=0)
    spatial_resolution_unit: str | None = None

    @model_validator(mode="after")
    def identity_and_constraints_match(self) -> "ScientificMethodManifest":
        if (self.method_id, self.version) != (self.rule.rule_id, self.rule.version):
            raise ValueError("method and executable rule IDs/versions must match")
        if self.domain != self.rule.domain:
            raise ValueError("method domain must match its scientific rule domain")
        if (
            self.minimum_spatial_resolution is not None
            and self.maximum_spatial_resolution is not None
            and self.minimum_spatial_resolution > self.maximum_spatial_resolution
        ):
            raise ValueError("minimum spatial resolution exceeds maximum")
        if (
            self.minimum_spatial_resolution is not None
            or self.maximum_spatial_resolution is not None
        ) and not self.spatial_resolution_unit:
            raise ValueError("spatial resolution constraints require an explicit unit")
        return self


class ScientificMethodRegistry:
    def __init__(self, methods: Iterable[ScientificMethodManifest] = ()) -> None:
        self._methods: dict[tuple[str, str], ScientificMethodManifest] = {}
        for method in methods:
            self.register(method)

    def register(self, method: ScientificMethodManifest) -> None:
        key = (method.method_id, method.version)
        if key in self._methods:
            raise ValueError(f"scientific method already registered: {key[0]}@{key[1]}")
        self._methods[key] = method

    def all(self) -> tuple[ScientificMethodManifest, ...]:
        return tuple(self._methods[key] for key in sorted(self._methods))

    def get(self, method_id: str, version: str) -> ScientificMethodManifest | None:
        return self._methods.get((method_id, version))

    def domain_catalog(self) -> tuple["ScientificDomainCatalogEntry", ...]:
        return tuple(
            ScientificDomainCatalogEntry(
                domain=domain,
                method_ids=tuple(item.method_id for item in self.all() if item.domain == domain),
                validated_method_ids=tuple(
                    item.method_id for item in self.all()
                    if item.domain == domain and item.rule.validation_status == "validated"
                ),
                status="validated_methods_registered"
                if any(item.domain == domain and item.rule.validation_status == "validated" for item in self.all())
                else "no_validated_methods_registered",
            )
            for domain in EARTH_SCIENCE_DOMAINS
        )

    @property
    def revision(self) -> str:
        payload = [item.model_dump(mode="json") for item in self.all()]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ScientificDomainCatalogEntry(Contract):
    domain: str
    method_ids: tuple[str, ...] = ()
    validated_method_ids: tuple[str, ...] = ()
    status: Literal["validated_methods_registered", "no_validated_methods_registered"]


class ScientificOperatorManifest(Contract):
    operator_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    operation: Literal[
        "anomaly_detection", "threshold_test", "trend_detection",
        "temporal_comparison", "spatial_comparison", "cross_dataset_validation",
        "change_significance", "evidence_sufficiency", "hypothesis_discrimination",
        "competing_hypothesis_comparison",
    ]
    validation_status: Literal["diagnostic", "validated_method"] = "diagnostic"
    required_variables: tuple[str, ...] = ()
    required_modalities: tuple[str, ...] = ()
    required_observation_count: int = Field(default=1, ge=1)
    reference_ids: tuple[str, ...] = ()
    method_id: str | None = None
    method_version: str | None = None
    output_semantics: str = "diagnostic_only"
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validated_operator_is_backed(self) -> "ScientificOperatorManifest":
        if self.validation_status == "validated_method":
            if not self.method_id or not self.method_version or not self.reference_ids:
                raise ValueError("validated operators require a versioned method and references")
        elif self.output_semantics != "diagnostic_only":
            raise ValueError("unvalidated operators must remain diagnostic-only")
        return self


class ScientificOperatorManifestRegistry:
    def __init__(self, manifests: Iterable[ScientificOperatorManifest] = ()) -> None:
        self._items: dict[tuple[str, str], ScientificOperatorManifest] = {}
        for item in manifests:
            self.register(item)

    def register(self, item: ScientificOperatorManifest) -> None:
        key = (item.operator_id, item.version)
        if key in self._items:
            raise ValueError(f"scientific operator manifest already registered: {key[0]}@{key[1]}")
        self._items[key] = item

    def all(self) -> tuple[ScientificOperatorManifest, ...]:
        return tuple(self._items[key] for key in sorted(self._items))

    def catalog(self) -> tuple[dict[str, object], ...]:
        operations = (
            "anomaly_detection", "threshold_test", "trend_detection",
            "temporal_comparison", "spatial_comparison",
            "cross_dataset_validation", "change_significance",
            "evidence_sufficiency", "hypothesis_discrimination",
            "competing_hypothesis_comparison",
        )
        return tuple(
            {
                "operation": operation,
                "manifest_ids": tuple(
                    f"{item.operator_id}@{item.version}"
                    for item in self.all() if item.operation == operation
                ),
                "status": "registered" if any(item.operation == operation for item in self.all()) else "no_operator_registered",
                "default_semantics": "diagnostic_only",
            }
            for operation in operations
        )


class EvidenceWeightAssessment(Contract):
    """Explicit categorical assessment; no numeric score or probability is inferred."""

    assessment_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    evidence_strength: Literal["unknown", "limited", "moderate", "strong"] = "unknown"
    reliability: Literal["unknown", "limited", "moderate", "strong"] = "unknown"
    dataset_suitability: Literal["unknown", "limited", "moderate", "strong"] = "unknown"
    observation_relevance: Literal["unknown", "limited", "moderate", "strong"] = "unknown"
    basis: str = Field(min_length=1)
    assessor: str = Field(min_length=1)
    reference_ids: tuple[str, ...] = ()
    provenance_ids: tuple[str, ...] = ()
    method_id: str | None = None
    method_version: str | None = None
    numeric_weight: None = None
    probability: None = None

    @model_validator(mode="after")
    def method_pair(self) -> "EvidenceWeightAssessment":
        if (self.method_id is None) != (self.method_version is None):
            raise ValueError("evidence assessment method ID and version must be supplied together")
        return self


class EvidenceDependencyEdge(Contract):
    source_evidence_id: str = Field(min_length=1)
    target_evidence_id: str = Field(min_length=1)
    relation: Literal["dependent", "independent", "unknown"]
    basis: str = Field(min_length=1)
    reference_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def distinct_evidence(self) -> "EvidenceDependencyEdge":
        if self.source_evidence_id == self.target_evidence_id:
            raise ValueError("evidence dependency edges require distinct evidence IDs")
        return self


class EvidenceAggregationMetadata(Contract):
    aggregation_id: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    status: Literal["not_aggregated", "aggregated_by_validated_method"] = "not_aggregated"
    method_id: str | None = None
    method_version: str | None = None
    assumptions: tuple[str, ...] = ()
    dependence_handling: str = "not_assessed"

    @model_validator(mode="after")
    def aggregation_requires_method(self) -> "EvidenceAggregationMetadata":
        if self.status == "aggregated_by_validated_method" and not (self.method_id and self.method_version):
            raise ValueError("evidence aggregation requires an explicit versioned method")
        return self


class WorkflowStage(Contract):
    stage_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    required_inputs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


class ScientificWorkflowTemplate(Contract):
    template_id: str = Field(min_length=1)
    version: str = "1.0.0"
    domain: str = Field(min_length=1)
    title: str = Field(min_length=1)
    required_configuration: tuple[str, ...]
    stages: tuple[WorkflowStage, ...]
    status: Literal["requires_configuration"] = "requires_configuration"
    methods: tuple[str, ...] = ()
    conclusions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def structural_only(self) -> "ScientificWorkflowTemplate":
        ids = {item.stage_id for item in self.stages}
        if len(ids) != len(self.stages):
            raise ValueError("workflow stage IDs must be unique")
        if any(dep not in ids for item in self.stages for dep in item.depends_on):
            raise ValueError("workflow stages may depend only on declared stages")
        if self.methods or self.conclusions:
            raise ValueError("unconfigured workflow templates cannot declare methods or conclusions")
        return self


class ScientificWorkflowInstance(Contract):
    instance_id: str = Field(min_length=1)
    template_id: str
    template_version: str
    supplied_configuration: dict[str, object] = Field(default_factory=dict)
    unresolved_configuration: tuple[str, ...]
    generated_method_ids: tuple[str, ...] = ()
    conclusions: tuple[str, ...] = ()
    status: Literal["requires_configuration"] = "requires_configuration"


def earth_science_workflow_templates() -> tuple[ScientificWorkflowTemplate, ...]:
    """Return generic structure only; no variables, thresholds, or conclusions."""
    specs = (
        ("drought", "Hydrology", ("drought_definition", "area_of_interest", "time_period", "evidence_requirements")),
        ("wildfire", "Disaster science", ("event_definition", "area_of_interest", "time_period", "evidence_requirements")),
        ("flood", "Hydrology", ("event_definition", "area_of_interest", "time_period", "evidence_requirements")),
        ("cyclone", "Atmospheric science", ("event_definition", "area_of_interest", "time_period", "evidence_requirements")),
        ("urban_expansion", "Urban analysis", ("change_definition", "area_of_interest", "baseline_period", "comparison_period", "evidence_requirements")),
        ("deforestation", "Ecology", ("change_definition", "area_of_interest", "baseline_period", "comparison_period", "evidence_requirements")),
        ("glacier_retreat", "Cryosphere", ("change_definition", "area_of_interest", "baseline_period", "comparison_period", "evidence_requirements")),
        ("crop_health", "Agriculture", ("health_definition", "area_of_interest", "time_period", "evidence_requirements")),
        ("water_quality", "Hydrology", ("quality_definition", "area_of_interest", "time_period", "evidence_requirements")),
        ("land_degradation", "Ecology", ("degradation_definition", "area_of_interest", "baseline_period", "comparison_period", "evidence_requirements")),
    )
    stages = (
        WorkflowStage(stage_id="scope", purpose="Record the investigation scope and definitions.", required_inputs=("area_of_interest", "time_period")),
        WorkflowStage(stage_id="evidence", purpose="Declare evidence requirements and candidate sources.", required_inputs=("evidence_requirements",), depends_on=("scope",)),
        WorkflowStage(stage_id="validation", purpose="Select only compatible, appropriately validated methods.", required_inputs=("method_selection",), depends_on=("evidence",)),
        WorkflowStage(stage_id="review", purpose="Record unresolved evidence gaps and reproducibility inputs.", required_inputs=("review_record",), depends_on=("validation",)),
    )
    return tuple(
        ScientificWorkflowTemplate(
            template_id=f"earth-investigation.{slug}", domain=domain,
            title=f"{slug.replace('_', ' ').title()} investigation structure",
            required_configuration=required, stages=stages,
        ) for slug, domain, required in specs
    )


class MethodEligibility(Contract):
    method_id: str
    version: str
    status: Literal["eligible", "rejected", "indeterminate"]
    capability_matrix_revision: str
    compatible_dataset_ids: tuple[str, ...] = ()
    satisfied_requirements: tuple[str, ...] = ()
    unmet_requirements: tuple[str, ...] = ()
    explanation: str


class ScientificMethodCapabilityPlanner:
    """Conservative preflight: missing matrix metadata is indeterminate/rejected."""

    def assess(
        self,
        method: ScientificMethodManifest,
        query: EarthQuery,
        matrix: EarthCapabilityMatrix,
        *,
        registered_uncertainty_methods: dict[str, str] | None = None,
        dataset_trust_assertions: Iterable[DatasetTrustAssertion] | None = None,
    ) -> MethodEligibility:
        failures: list[str] = []
        unknown: list[str] = []
        global_unknown: list[str] = []
        satisfied: list[str] = []
        if method.rule.validation_status != "validated":
            failures.append(f"method validation status is {method.rule.validation_status}")
        if method.rule.applicability.minimum_observations > 1:
            global_unknown.append(
                "minimum observation count cannot be established from a capability declaration before acquisition"
            )
        uncertainty = method.rule.uncertainty_propagation
        if uncertainty.status == "required":
            if registered_uncertainty_methods is None:
                global_unknown.append("required uncertainty method availability was not supplied to preflight")
            elif registered_uncertainty_methods.get(uncertainty.method_id or "") != uncertainty.method_version:
                failures.append(
                    f"required uncertainty method {uncertainty.method_id}@{uncertainty.method_version} is not registered at the required version"
                )
        required_vars = set(method.rule.applicability.required_variables) | set(method.rule.dataset_compatibility.required_variables)
        required_modalities = set(method.rule.applicability.required_modalities) | set(method.rule.dataset_compatibility.required_modalities)
        if not required_vars.issubset(set(query.requested_variables)):
            failures.append("query does not request every method-required variable")
        if not required_modalities.issubset(set(query.requested_modalities)):
            failures.append("query does not request every method-required modality")
        entries = [entry for entry in matrix.entries if entry.scope == "dataset"]
        trust_assertions = tuple(dataset_trust_assertions or ())
        if method.required_dataset_ids:
            entries = [e for e in entries if e.dataset_id in method.required_dataset_ids]
        if query.requested_dataset_ids:
            entries = [e for e in entries if e.dataset_id in query.requested_dataset_ids]
        candidates = []
        for entry in entries:
            vars_here = {v.canonical_name or v.source_name for v in entry.variables}
            if required_vars and not required_vars.issubset(vars_here):
                continue
            if required_modalities and not required_modalities.issubset(set(entry.modalities)):
                continue
            if method.rule.dataset_compatibility.allowed_crs and entry.crs not in method.rule.dataset_compatibility.allowed_crs:
                continue
            if method.rule.dataset_compatibility.required_metadata:
                metadata = entry.dataset_metadata.metadata if entry.dataset_metadata else {}
                missing_metadata = [
                    key for key in method.rule.dataset_compatibility.required_metadata
                    if key not in metadata
                ]
                mismatched_metadata = [
                    key for key, value in method.rule.dataset_compatibility.required_metadata.items()
                    if key in metadata and metadata[key] != value
                ]
                if missing_metadata:
                    unknown.append(
                        f"dataset {entry.dataset_id} lacks required metadata keys: {sorted(missing_metadata)}"
                    )
                    continue
                if mismatched_metadata:
                    continue
            if method.rule.dataset_compatibility.required_trust_scope_ids:
                if entry.dataset_id is None:
                    unknown.append("dataset identity is required to verify trust scopes")
                    continue
                candidate_trust = [
                    assertion for assertion in trust_assertions
                    if assertion.connector_id == entry.connector_id
                    and assertion.dataset_id == entry.dataset_id
                    and assertion.dataset_version in (None, entry.dataset_version)
                ]
                missing_scopes = [
                    scope_id for scope_id in method.rule.dataset_compatibility.required_trust_scope_ids
                    if not any(
                        assertion.scope_id == scope_id
                        and assertion.status == "trusted_for_scope"
                        for assertion in candidate_trust
                    )
                ]
                if missing_scopes:
                    rejected_scopes = [
                        scope_id for scope_id in missing_scopes
                        if any(
                            assertion.scope_id == scope_id
                            and assertion.status in {"limited", "rejected"}
                            for assertion in candidate_trust
                        )
                    ]
                    if rejected_scopes:
                        continue
                    unknown.append(
                        f"dataset {entry.dataset_id} has no trusted assessment for scopes: {sorted(missing_scopes)}"
                    )
                    continue
            if method.required_uncertainty_categories and not set(method.required_uncertainty_categories).issubset(entry.uncertainty_metadata):
                continue
            quality = entry.quality_metadata
            q = method.rule.required_quality
            if q.minimum_quality_score is not None and quality.get("quality_score") is None:
                unknown.append(f"dataset {entry.dataset_id} has no declared quality score")
                continue
            if q.minimum_quality_score is not None and quality.get("quality_score", -1) < q.minimum_quality_score:
                continue
            if q.minimum_completeness is not None and quality.get("completeness") is None:
                unknown.append(f"dataset {entry.dataset_id} has no declared completeness")
                continue
            if q.minimum_completeness is not None and quality.get("completeness", -1) < q.minimum_completeness:
                continue
            if q.require_validated_observation and quality.get("validation_status") is None:
                unknown.append(f"dataset {entry.dataset_id} has no declared validation status")
                continue
            if q.require_validated_observation and quality.get("validation_status") != "valid":
                continue
            if query.temporal_start or query.temporal_end:
                extent = entry.temporal_coverage or entry.historical_coverage or entry.forecast_coverage
                if extent is None or (query.temporal_start and (extent.start is None or extent.start > query.temporal_start)) or (query.temporal_end and (extent.end is None or extent.end < query.temporal_end)):
                    continue
            if method.rule.applicability.require_spatial_support and entry.spatial_coverage is None:
                unknown.append(f"dataset {entry.dataset_id} has no declared spatial coverage")
                continue
            if query.point is not None or query.bbox is not None or query.geometry is not None:
                if entry.spatial_coverage is None or entry.crs is None:
                    unknown.append(f"dataset {entry.dataset_id} spatial coverage cannot be verified")
                    continue
                try:
                    intersects = query_intersects_coverage(
                        query, entry.spatial_coverage, coverage_crs=entry.crs
                    )
                except (RuntimeError, ValueError, TypeError):
                    unknown.append(f"dataset {entry.dataset_id} spatial intersection could not be assessed")
                    continue
                if not intersects:
                    continue
            if query.spatial_resolution is not None:
                if entry.spatial_resolution is None or entry.resolution_unit is None:
                    unknown.append(f"dataset {entry.dataset_id} spatial resolution is undeclared")
                    continue
                if query.resolution_unit is None or query.resolution_unit != entry.resolution_unit:
                    unknown.append(f"dataset {entry.dataset_id} resolution units are not directly comparable")
                    continue
                if query.spatial_resolution < entry.spatial_resolution:
                    continue
            if method.spatial_resolution_unit is not None:
                if entry.spatial_resolution is None or entry.resolution_unit is None:
                    unknown.append(f"dataset {entry.dataset_id} spatial resolution is undeclared")
                    continue
                if entry.resolution_unit != method.spatial_resolution_unit:
                    unknown.append(f"dataset {entry.dataset_id} resolution units do not match method requirements")
                    continue
                if method.minimum_spatial_resolution is not None and entry.spatial_resolution < method.minimum_spatial_resolution:
                    continue
                if method.maximum_spatial_resolution is not None and entry.spatial_resolution > method.maximum_spatial_resolution:
                    continue
            candidates.append(entry)
        if candidates:
            satisfied.append("at least one declared dataset meets observable variable/modality/coverage constraints")
        else:
            failures.append("no declared dataset can be verified to satisfy method requirements")
        if not candidates and unknown:
            failures = [item for item in failures if item != "no declared dataset can be verified to satisfy method requirements"]
        status = (
            "rejected" if failures
            else "indeterminate" if global_unknown
            else "eligible" if candidates
            else "indeterminate" if unknown
            else "rejected"
        )
        details = tuple(failures + global_unknown + unknown)
        return MethodEligibility(
            method_id=method.method_id, version=method.version, status=status,
            capability_matrix_revision=matrix.revision,
            compatible_dataset_ids=tuple(sorted({e.dataset_id for e in candidates if e.dataset_id})),
            satisfied_requirements=tuple(satisfied), unmet_requirements=details,
            explanation=("At least one dataset declaration is compatible with the assessed query constraints; this does not establish observation availability, method runtime readiness, or scientific sufficiency." if status == "eligible" else "; ".join(details)),
        )
