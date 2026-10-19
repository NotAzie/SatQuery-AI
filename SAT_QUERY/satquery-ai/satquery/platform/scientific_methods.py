"""Versioned metadata contracts for scientific methods and uncertainty.

This module contains declarations only. It does not certify a method; a
validated status requires an explicit validation record and cited references.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Literal, Optional

from pydantic import Field, model_validator

from .contracts import Contract, utc_now


class ScientificReference(Contract):
    reference_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    doi: Optional[str] = None
    uri: Optional[str] = None
    publication_year: Optional[int] = Field(default=None, ge=1600, le=2200)

    @model_validator(mode="after")
    def reference_has_locator(self) -> "ScientificReference":
        if not self.doi and not self.uri:
            raise ValueError("scientific references require a DOI or URI locator")
        return self


class RuleValidationRecord(Contract):
    validation_id: str = Field(min_length=1)
    validation_status: Literal["validated"]
    validated_by: str = Field(min_length=1)
    validated_at: datetime = Field(default_factory=utc_now)
    validation_suite_id: str = Field(min_length=1)
    validation_suite_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    implementation_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    reference_ids: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()


class RuleApplicability(Contract):
    minimum_observations: int = Field(default=1, ge=1)
    required_variables: tuple[str, ...] = ()
    required_modalities: tuple[str, ...] = ()
    require_temporal_support: bool = False
    require_spatial_support: bool = False
    require_declared_dataset_metadata: bool = False
    assumptions: tuple[str, ...] = ()


class ScientificEvidenceRequirement(Contract):
    requirement_id: str = Field(min_length=1)
    evidence_type: Literal[
        "variable",
        "modality",
        "temporal_support",
        "spatial_support",
        "dataset_metadata",
    ]
    target: str = Field(min_length=1)
    minimum_observations: int = Field(default=1, ge=1)
    rationale: str = Field(min_length=1)


class RuleDatasetCompatibility(Contract):
    """Provider-neutral compatibility criteria evaluated from dataset metadata."""

    required_variables: tuple[str, ...] = ()
    required_modalities: tuple[str, ...] = ()
    allowed_crs: tuple[str, ...] = ()
    required_metadata: dict[str, Any] = Field(default_factory=dict)
    required_trust_scope_ids: tuple[str, ...] = ()


class RequiredObservationQuality(Contract):
    minimum_quality_score: Optional[float] = Field(default=None, ge=0, le=1)
    minimum_completeness: Optional[float] = Field(default=None, ge=0, le=1)
    require_validated_observation: bool = False


class ExpectedUncertaintyPropagation(Contract):
    status: Literal["not_required", "required", "unsupported"] = "unsupported"
    method_id: Optional[str] = None
    method_version: Optional[str] = None
    required_inputs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def required_method_is_named(self) -> "ExpectedUncertaintyPropagation":
        if self.status == "required" and (
            not self.method_id or not self.method_version
        ):
            raise ValueError(
                "required uncertainty propagation must name a versioned method"
            )
        return self


class ScientificRuleManifest(Contract):
    rule_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    description: str = Field(min_length=1)
    validation_status: Literal["draft", "experimental", "validated", "deprecated"]
    scientific_references: tuple[ScientificReference, ...] = ()
    validation_record: Optional[RuleValidationRecord] = None
    implementation_sha256: Optional[str] = Field(
        default=None, pattern=r"^[a-fA-F0-9]{64}$"
    )
    applicability: RuleApplicability = Field(default_factory=RuleApplicability)
    dataset_compatibility: RuleDatasetCompatibility = Field(
        default_factory=RuleDatasetCompatibility
    )
    required_evidence: tuple[ScientificEvidenceRequirement, ...] = ()
    required_quality: RequiredObservationQuality = Field(
        default_factory=RequiredObservationQuality
    )
    uncertainty_propagation: ExpectedUncertaintyPropagation = Field(
        default_factory=ExpectedUncertaintyPropagation
    )
    deterministic: bool = True
    output_semantics: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validated_rule_has_audit_record(self) -> "ScientificRuleManifest":
        if self.validation_status == "validated":
            if self.validation_record is None:
                raise ValueError("validated rules require a validation record")
            if self.implementation_sha256 is None:
                raise ValueError(
                    "validated rules require an implementation SHA-256 digest"
                )
            if (
                self.validation_record.implementation_sha256
                != self.implementation_sha256
            ):
                raise ValueError(
                    "validation record must attest to the registered implementation digest"
                )
            known = {item.reference_id for item in self.scientific_references}
            if not set(self.validation_record.reference_ids).issubset(known):
                raise ValueError(
                    "validation record references must exist in the rule manifest"
                )
            if self.uncertainty_propagation.status == "unsupported":
                raise ValueError(
                    "validated rules must declare uncertainty propagation as required or not_required"
                )
        elif self.validation_record is not None:
            raise ValueError("only validated rules may carry a validation record")
        return self


class ScientificUncertainty(Contract):
    status: Literal[
        "quantified", "partially_quantified", "not_quantified", "not_applicable"
    ]
    standard_uncertainty: Optional[float] = Field(default=None, ge=0)
    unit: Optional[str] = None
    distribution: Optional[str] = None
    method_id: Optional[str] = None
    method_version: Optional[str] = None
    reference_ids: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    reason: Optional[str] = None

    @model_validator(mode="after")
    def uncertainty_is_explicit(self) -> "ScientificUncertainty":
        if self.status == "quantified" and self.standard_uncertainty is None:
            raise ValueError(
                "quantified uncertainty requires an explicit standard uncertainty"
            )
        if self.status == "quantified" and (
            not self.method_id or not self.method_version or not self.unit
        ):
            raise ValueError(
                "quantified uncertainty requires a unit and versioned method"
            )
        if self.status == "partially_quantified" and (
            not self.method_id or not self.method_version
        ):
            raise ValueError(
                "partially quantified uncertainty requires a versioned method"
            )
        return self


class CalibratedEvidenceWeight(Contract):
    """Optional likelihood evidence; never estimated by the platform."""

    status: Literal["available", "unavailable"] = "unavailable"
    log_likelihood_ratio: Optional[float] = None
    method_id: Optional[str] = None
    method_version: Optional[str] = None
    calibration_reference_ids: tuple[str, ...] = ()
    dependence_group: Optional[str] = None
    uncertainty: ScientificUncertainty = Field(
        default_factory=lambda: ScientificUncertainty(
            status="not_quantified", reason="No calibrated uncertainty was supplied."
        )
    )

    @model_validator(mode="after")
    def available_weight_is_calibrated(self) -> "CalibratedEvidenceWeight":
        if self.status == "available":
            if (
                self.log_likelihood_ratio is None
                or not self.method_id
                or not self.method_version
            ):
                raise ValueError(
                    "available evidence weights require an explicit value and versioned method"
                )
            if not self.calibration_reference_ids or not self.dependence_group:
                raise ValueError(
                    "available evidence weights require calibration references and dependence grouping"
                )
            if not isfinite(self.log_likelihood_ratio):
                raise ValueError("log likelihood ratios must be finite")
        return self
