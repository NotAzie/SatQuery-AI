"""Evidence-grounded Earth Object materialization and relationship graphs.

This module does not detect entities or infer their properties. The extraction
pipeline validates and reconciles explicit source candidates; the materializer
copies cited canonical measurements and preserves source geometry/provenance.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .contracts import (
    Contract,
    EarthObject,
    EarthObjectCandidate,
    EarthObjectGraph,
    EarthObjectPropertyAssertion,
    EarthObjectRelationship,
    EarthObjectSourceAttribute,
    EarthQuery,
    Evidence,
    Observation,
    RasterComponentExtractionSpec,
    TemporalExtent,
)


class EarthObjectRevisionTransition(Contract):
    """Explicit, auditable reclassification or lifecycle change.

    A transition records a reviewer/source assertion. It is not an automated
    scientific validation or an inferred lifecycle event.
    """

    prior_object_id: str = Field(min_length=1)
    transition_type: Literal["reclassification", "lifecycle"]
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    observation_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    prior_object_type: str | None = None
    new_object_type: str | None = None
    prior_lifecycle: Literal[
        "observed", "active", "inactive", "superseded", "retracted", "unknown"
    ] | None = None
    new_lifecycle: Literal[
        "observed", "active", "inactive", "superseded", "retracted", "unknown"
    ] | None = None

    @model_validator(mode="after")
    def validate_transition_shape(self) -> EarthObjectRevisionTransition:
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("Earth Object transition observation IDs must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Earth Object transition evidence IDs must be unique")
        if self.transition_type == "reclassification":
            if (
                not self.prior_object_type
                or not self.new_object_type
                or self.prior_object_type == self.new_object_type
                or self.prior_lifecycle is not None
                or self.new_lifecycle is not None
            ):
                raise ValueError("reclassification requires distinct prior and new object types")
        elif (
            self.prior_lifecycle is None
            or self.new_lifecycle is None
            or self.prior_lifecycle == self.new_lifecycle
            or self.prior_object_type is not None
            or self.new_object_type is not None
        ):
            raise ValueError("lifecycle transition requires distinct prior and new states")
        return self


class EarthObjectDeclaration(Contract):
    """Explicit identity and semantic declaration supplied by an evidence source."""

    identity_namespace: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    declared_by: str = Field(min_length=1)
    investigation_id: str | None = None
    created_at: datetime | None = None
    observation_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    conflicting_evidence_ids: tuple[str, ...] = ()
    unresolved_evidence_ids: tuple[str, ...] = ()
    lifecycle: (
        Literal["observed", "active", "inactive", "superseded", "retracted", "unknown"]
        | None
    ) = None
    revision_transition: EarthObjectRevisionTransition | None = None
    declared_provenance: dict[str, Any] = Field(default_factory=dict)
    derived_geometry: dict[str, Any] | None = None
    derived_crs: str | None = None
    derived_assertions: tuple[EarthObjectPropertyAssertion, ...] = ()
    derived_uncertainty: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_declaration(self) -> EarthObjectDeclaration:
        if (self.derived_geometry is None) != (self.derived_crs is None):
            raise ValueError("derived geometry and CRS must be supplied together")
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("Earth Object declaration has duplicate observation IDs")
        all_classified = (
            set(self.supporting_evidence_ids)
            | set(self.conflicting_evidence_ids)
            | set(self.unresolved_evidence_ids)
        )
        if not all_classified.issubset(set(self.evidence_ids)):
            raise ValueError("classified evidence must be included in evidence_ids")
        classes = (
            set(self.supporting_evidence_ids),
            set(self.conflicting_evidence_ids),
            set(self.unresolved_evidence_ids),
        )
        if any(
            classes[left] & classes[right]
            for left in range(3)
            for right in range(left + 1, 3)
        ):
            raise ValueError("evidence classifications must be mutually exclusive")
        if self.revision_transition is not None and (
            not set(self.revision_transition.observation_ids).issubset(
                set(self.observation_ids)
            )
            or not set(self.revision_transition.evidence_ids).issubset(
                set(self.evidence_ids)
            )
        ):
            raise ValueError(
                "transition support must be included in the Earth Object declaration"
            )
        for assertion in self.derived_assertions:
            if not set(assertion.observation_ids).issubset(set(self.observation_ids)):
                raise ValueError("derived assertion references an undeclared observation")
            if not set(assertion.evidence_ids).issubset(set(self.evidence_ids)):
                raise ValueError("derived assertion references undeclared evidence")
        return self


class EarthObjectExtractionIssue(Contract):
    """A candidate the deterministic extraction pipeline could not reconcile."""

    identity: str = Field(min_length=1)
    observation_ids: tuple[str, ...] = ()
    code: Literal[
        "conflicting_declaration",
        "raster_asset_missing",
        "raster_band_invalid",
        "raster_crs_missing",
        "raster_no_matching_class",
        "raster_component_limit_exceeded",
        "raster_processing_failed",
        "materialization_rejected",
    ]
    message: str = Field(min_length=1)


class EarthObjectExtractionBatch(Contract):
    """Deterministic candidate-to-declaration output for one observation set."""

    pipeline_id: str = Field(min_length=1)
    pipeline_version: str = Field(min_length=1)
    declarations: tuple[EarthObjectDeclaration, ...] = ()
    issues: tuple[EarthObjectExtractionIssue, ...] = ()
    input_observation_ids: tuple[str, ...] = ()
    materialized_object_ids: tuple[str, ...] = ()
    reproducibility: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_batch(self) -> EarthObjectExtractionBatch:
        if len(self.input_observation_ids) != len(set(self.input_observation_ids)):
            raise ValueError("extraction batch contains duplicate input observation IDs")
        if len(self.materialized_object_ids) != len(set(self.materialized_object_ids)):
            raise ValueError("extraction batch contains duplicate materialized object IDs")
        input_ids = set(self.input_observation_ids)
        identities = [
            f"{item.identity_namespace}:{item.identity_value}"
            for item in self.declarations
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("extraction batch contains duplicate object declarations")
        if any(
            not set(item.observation_ids).issubset(input_ids)
            for item in self.declarations
        ):
            raise ValueError("extraction declaration references a non-input observation")
        if any(
            not set(item.observation_ids).issubset(input_ids) for item in self.issues
        ):
            raise ValueError("extraction issue references a non-input observation")
        return self


class EarthObjectExtractionPipeline:
    """Convert explicit candidates and configured raster classes to declarations.

    It reconciles explicit candidate identities and optionally polygonizes exact
    categorical values selected by the query. It never assigns class meaning,
    classifies imagery, or upgrades a method's validation status.
    """

    PIPELINE_ID = "satquery.earth-object-candidate-extraction"
    VERSION = "1.1.0"

    def __init__(self, raster_component_extractor=None) -> None:
        self.raster_component_extractor = raster_component_extractor

    def extract(
        self,
        observations: tuple[Observation, ...],
        *,
        investigation_id: str | None = None,
        query: EarthQuery | None = None,
    ) -> EarthObjectExtractionBatch:
        by_id = {item.observation_id: item for item in observations}
        if len(by_id) != len(observations):
            raise ValueError("extraction received duplicate observation IDs")

        groups: dict[str, list[tuple[Observation, EarthObjectCandidate]]] = {}
        for observation in observations:
            candidate = observation.earth_object_candidate
            if candidate is None:
                continue
            identity = f"{candidate.identity_namespace}:{candidate.identity_value}"
            groups.setdefault(identity, []).append((observation, candidate))

        declarations: list[EarthObjectDeclaration] = []
        issues: list[EarthObjectExtractionIssue] = []
        candidate_digests: dict[str, str] = {}
        for identity, members in sorted(groups.items()):
            object_types = {candidate.object_type for _, candidate in members}
            observation_ids = tuple(
                sorted(observation.observation_id for observation, _ in members)
            )
            if len(object_types) != 1:
                issues.append(
                    EarthObjectExtractionIssue(
                        identity=identity,
                        observation_ids=observation_ids,
                        code="conflicting_declaration",
                        message=(
                            "Observations declared different canonical object types "
                            "for the same stable source identity. No object was emitted."
                        ),
                    )
                )
                continue

            object_type = next(iter(object_types))
            declarers = tuple(sorted({candidate.declared_by for _, candidate in members}))
            method_identities = tuple(sorted({candidate.mapping_id for _, candidate in members}))
            declared_by = (
                declarers[0]
                if len(declarers) == 1
                else self.PIPELINE_ID
            )
            candidate_records: dict[str, Any] = {}
            input_context: dict[str, Any] = {}
            for observation, candidate in sorted(
                members, key=lambda value: value[0].observation_id
            ):
                candidate_payload = candidate.model_dump(mode="json")
                candidate_records[observation.observation_id] = candidate_payload
                candidate_digests[observation.observation_id] = _digest(
                    candidate_payload
                )
                input_context[observation.observation_id] = {
                    "dataset": observation.dataset.model_dump(mode="json")
                    if observation.dataset
                    else None,
                    "observation_type": observation.observation_type,
                    "modalities": observation.modalities,
                    "declared_by": candidate.declared_by,
                    "method_identity": candidate.mapping_id,
                }

            declarations.append(
                EarthObjectDeclaration(
                    identity_namespace=members[0][1].identity_namespace,
                    identity_value=members[0][1].identity_value,
                    object_type=object_type,
                    declared_by=declared_by,
                    investigation_id=investigation_id,
                    observation_ids=observation_ids,
                    declared_provenance={
                        "extraction_pipeline": {
                            "pipeline_id": self.PIPELINE_ID,
                            "pipeline_version": self.VERSION,
                            "status": "source_declared_candidate",
                            "method_identities": method_identities,
                            "source_declarers": declarers,
                            "validation_status": "not_independently_validated",
                            "object_type_basis": "explicit_source_candidate",
                            "applicability_context": input_context,
                            "limitations": (
                            "The source candidates are not independent ground-truth validation.",
                            "Candidates are combined only when they share the same explicit identity namespace, identity value, and canonical object type.",
                            "The pipeline does not infer geometry, class, measurements, or confidence.",
                            ),
                            "extraction_uncertainty": "not_reported_by_candidate",
                        },
                        "source_candidates": candidate_records,
                    },
                )
            )

        if query is not None and query.raster_component_extraction:
            extractor = self.raster_component_extractor
            if extractor is None:
                from .raster_objects import RasterCategoricalComponentExtractor

                extractor = RasterCategoricalComponentExtractor()
            for observation in sorted(observations, key=lambda item: item.observation_id):
                for specification in query.raster_component_extraction:
                    try:
                        components = extractor.extract(
                            observation, query, specification
                        )
                    except Exception as exc:
                        code = getattr(exc, "code", "raster_processing_failed")
                        issues.append(
                            EarthObjectExtractionIssue(
                                identity=(
                                    f"{observation.observation_id}:"
                                    f"{specification.asset_key}:{specification.band_index}"
                                ),
                                observation_ids=(observation.observation_id,),
                                code=code,
                                message=str(exc) or type(exc).__name__,
                            )
                        )
                        continue
                    for component in components:
                        class_value = component["class_value"]
                        mapping = next(
                            item for item in specification.class_mappings
                            if item.class_value == class_value
                        )
                        component_identity = component["component_identity"]
                        observation_id = observation.observation_id
                        assertion = EarthObjectPropertyAssertion(
                            property_id=f"{component_identity}:pixel-count",
                            name="raster.component.pixel_count",
                            value=component["pixel_count"],
                            unit="pixel",
                            source_variable=specification.source_variable,
                            observation_ids=(observation_id,),
                            uncertainty={"status": "not_estimated"},
                            provenance={
                                "operator_id": component["operator_id"],
                                "operator_version": component["operator_version"],
                                "interpretation": (
                                    "Exact cell count conditional on the encoded class mask, "
                                    "AOI selection, and connectivity rule."
                                ),
                            },
                        )
                        declarations.append(
                            EarthObjectDeclaration(
                                identity_namespace="urn:satquery:raster-component:v1",
                                identity_value=component_identity,
                                object_type=mapping.object_type,
                                declared_by=component["operator_id"],
                                investigation_id=investigation_id,
                                observation_ids=(observation_id,),
                                declared_provenance={
                                    "extraction_pipeline": {
                                        "pipeline_id": component["operator_id"],
                                        "pipeline_version": component["operator_version"],
                                        "status": "deterministic_categorical_polygonization",
                                        "validation_status": "not_independently_validated",
                                        "semantic_mapping_origin": "explicit_query_configuration",
                                        "source_variable": specification.source_variable,
                                        "class_value": class_value,
                                        "object_type_mapping": mapping.object_type,
                                        "connectivity": specification.connectivity,
                                        "pixel_selection": specification.pixel_selection,
                                        "minimum_component_pixels": specification.minimum_component_pixels,
                                        "limitations": (
                                            "The operator polygonizes explicitly selected encoded raster class values.",
                                            "Class meaning is supplied by the request and is not inferred or validated by this operator.",
                                            "No classification, object recognition, uncertainty estimate, or cross-scene identity resolution is performed.",
                                        ),
                                    },
                                    "raster_source": component["source"],
                                    "raster_processing": component["processing"],
                                },
                                derived_geometry=component["geometry"],
                                derived_crs=component["crs"],
                                derived_assertions=(assertion,),
                                derived_uncertainty={
                                    "status": "not_assessed",
                                    "classification_uncertainty": "not_assessed",
                                    "geometry_uncertainty": "not_assessed",
                                    "conditional_pixel_count": "exact_for_selected_encoded_cells",
                                },
                            )
                        )

        ordered_observation_ids = tuple(sorted(by_id))
        input_digests = {
            observation_id: _digest(by_id[observation_id].model_dump(mode="json"))
            for observation_id in ordered_observation_ids
        }
        return EarthObjectExtractionBatch(
            pipeline_id=self.PIPELINE_ID,
            pipeline_version=self.VERSION,
            declarations=tuple(declarations),
            issues=tuple(issues),
            input_observation_ids=ordered_observation_ids,
            reproducibility={
                "input_observation_digests": input_digests,
                "candidate_digests": candidate_digests,
                "identity_order": tuple(sorted(groups)),
                "candidate_policy": "explicit_candidate_only_no_detection",
                "raster_component_spec_digests": tuple(
                    _digest(item.model_dump(mode="json"))
                    for item in query.raster_component_extraction
                ) if query else (),
            },
        )


class EarthObjectMaterializer:
    """Create deterministic object snapshots without semantic inference."""

    MATERIALIZER_ID = "satquery.earth-object-materializer"
    MATERIALIZER_VERSION = "1.0.0"

    def materialize(
        self,
        declaration: EarthObjectDeclaration,
        observations: tuple[Observation, ...],
        *,
        evidence: tuple[Evidence, ...] = (),
        previous: EarthObject | None = None,
    ) -> EarthObject:
        by_id = {item.observation_id: item for item in observations}
        if len(by_id) != len(observations):
            raise ValueError("materialization received duplicate observation IDs")
        missing = set(declaration.observation_ids) - set(by_id)
        if missing:
            raise ValueError(f"declared observations are absent: {sorted(missing)}")
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise ValueError("materialization received duplicate evidence IDs")
        missing_evidence = set(declaration.evidence_ids) - set(evidence_by_id)
        if missing_evidence:
            raise ValueError(f"declared evidence is absent: {sorted(missing_evidence)}")
        observation_ids = set(declaration.observation_ids)
        if previous is not None:
            observation_ids.update(previous.source_observation_ids)
        for item in (evidence_by_id[key] for key in declaration.evidence_ids):
            if (
                item.observation_id is not None
                and item.observation_id not in observation_ids
            ):
                raise ValueError(
                    "declared evidence cites an observation outside this object"
                )
            if (
                declaration.investigation_id
                and item.investigation_id != declaration.investigation_id
            ):
                raise ValueError("declared evidence belongs to another investigation")

        identity = f"{declaration.identity_namespace}:{declaration.identity_value}"
        if previous is not None and previous.stable_identity != identity:
            raise ValueError("previous object revision has a different stable identity")
        if previous is None and declaration.revision_transition is not None:
            raise ValueError("an Earth Object transition requires a prior revision")

        selected_evidence_ids = set(declaration.evidence_ids)
        supporting_evidence_ids = set(declaration.supporting_evidence_ids)
        conflicting_evidence_ids = set(declaration.conflicting_evidence_ids)
        unresolved_evidence_ids = set(declaration.unresolved_evidence_ids)
        if previous is not None:
            for record in previous.provenance.get("source_records", ()):
                source_observation = Observation.model_validate(record)
                current_observation = by_id.get(source_observation.observation_id)
                if (
                    current_observation is not None
                    and current_observation != source_observation
                ):
                    raise ValueError(
                        "an observation ID cannot be rebound to different content"
                    )
                by_id.setdefault(source_observation.observation_id, source_observation)
            for record in previous.provenance.get("evidence_records", ()):
                source_evidence = Evidence.model_validate(record)
                existing = evidence_by_id.get(source_evidence.evidence_id)
                if existing is not None and existing != source_evidence:
                    raise ValueError(
                        "an evidence ID cannot be rebound to different content"
                    )
                evidence_by_id.setdefault(source_evidence.evidence_id, source_evidence)
                selected_evidence_ids.add(source_evidence.evidence_id)
            supporting_evidence_ids.update(previous.supporting_evidence_ids)
            conflicting_evidence_ids.update(previous.conflicting_evidence_ids)
            unresolved_evidence_ids.update(previous.unresolved_evidence_ids)
        classes = (
            supporting_evidence_ids,
            conflicting_evidence_ids,
            unresolved_evidence_ids,
        )
        if any(
            classes[left] & classes[right]
            for left in range(3)
            for right in range(left + 1, 3)
        ):
            raise ValueError(
                "an evidence record cannot change classification across object revisions"
            )
        if not selected_evidence_ids.issubset(evidence_by_id):
            raise ValueError(
                "previous object revision references evidence that cannot be restored"
            )

        transition = declaration.revision_transition
        if previous is not None:
            lifecycle = declaration.lifecycle or previous.lifecycle
            type_changed = previous.object_type != declaration.object_type
            lifecycle_changed = previous.lifecycle != lifecycle
            if type_changed:
                if (
                    transition is None
                    or transition.transition_type != "reclassification"
                    or transition.prior_object_id != previous.object_id
                    or transition.prior_object_type != previous.object_type
                    or transition.new_object_type != declaration.object_type
                ):
                    raise ValueError(
                        "an object type change requires a matching explicit reclassification transition"
                    )
            elif transition is not None and transition.transition_type == "reclassification":
                raise ValueError("reclassification transition does not change object type")
            if lifecycle_changed:
                if (
                    transition is None
                    or transition.transition_type != "lifecycle"
                    or transition.prior_object_id != previous.object_id
                    or transition.prior_lifecycle != previous.lifecycle
                    or transition.new_lifecycle != lifecycle
                ):
                    raise ValueError(
                        "an object lifecycle change requires a matching explicit transition"
                    )
            elif transition is not None and transition.transition_type == "lifecycle":
                raise ValueError("lifecycle transition does not change object state")
            if transition is not None:
                if not set(transition.observation_ids).issubset(observation_ids):
                    raise ValueError("transition cites an observation outside this object")
                if not set(transition.evidence_ids).issubset(selected_evidence_ids):
                    raise ValueError("transition cites evidence outside this object")

        evidence_by_observation: dict[str, set[str]] = {}
        for item in evidence_by_id.values():
            if item.evidence_id in selected_evidence_ids and item.observation_id:
                evidence_by_observation.setdefault(item.observation_id, set()).add(
                    item.evidence_id
                )

        ordered = tuple(by_id[key] for key in sorted(observation_ids))
        geometry_fingerprints = {
            _digest(item.geometry) for item in ordered if item.geometry is not None
        }
        geometries = [item.geometry for item in ordered if item.geometry is not None]
        source_geometry = (
            geometries[0]
            if geometries
            and len(geometry_fingerprints) == 1
            and all(item.geometry is not None for item in ordered)
            else None
        )
        crss = {item.crs for item in ordered if item.crs is not None}
        crs = (
            next(iter(crss))
            if len(crss) == 1 and all(item.crs is not None for item in ordered)
            else None
        )
        geometry = declaration.derived_geometry or source_geometry
        crs = declaration.derived_crs or crs
        temporal_fingerprints = {
            _digest(item.temporal_extent.model_dump(mode="json"))
            for item in ordered
            if item.temporal_extent is not None
        }
        temporal_values = [
            item.temporal_extent for item in ordered if item.temporal_extent is not None
        ]
        temporal_validity: TemporalExtent | None = (
            temporal_values[0]
            if temporal_values
            and len(temporal_fingerprints) == 1
            and all(item.temporal_extent is not None for item in ordered)
            else None
        )

        measurements = []
        assertions = []
        source_attributes = []
        for observation in ordered:
            observation_evidence = tuple(
                sorted(evidence_by_observation.get(observation.observation_id, ()))
            )
            for measurement in observation.canonical_measurements:
                if measurement.observation_id not in {None, observation.observation_id}:
                    raise ValueError(
                        "canonical measurement cites a different source observation"
                    )

                linked_measurement = (
                    measurement.model_copy(
                        update={"observation_id": observation.observation_id}
                    )
                    if measurement.observation_id is None
                    else measurement
                )
                measurements.append(linked_measurement)
                assertions.append(
                    EarthObjectPropertyAssertion(
                        property_id=f"{observation.observation_id}:{measurement.canonical_variable}:{len(assertions)}",
                        name=measurement.canonical_variable,
                        value=measurement.value,
                        unit=measurement.unit,
                        source_variable=measurement.source_variable,
                        ontology_uri=measurement.ontology_uri,
                        observation_ids=(observation.observation_id,),
                        evidence_ids=observation_evidence,
                        uncertainty=observation.uncertainty,
                        provenance={
                            "dataset": observation.dataset.model_dump(mode="json")
                            if observation.dataset
                            else None,
                            "observation_provenance": observation.provenance,
                            "provider_metadata": observation.provider_metadata,
                            "measurement_source_metadata": measurement.source_metadata,
                        },
                    )
                )
            candidate = observation.earth_object_candidate
            raw_attributes = (
                candidate.provenance.get("source_attributes", {})
                if candidate is not None
                else {}
            )
            if candidate is not None and isinstance(raw_attributes, dict):
                candidate_context = {
                    key: value
                    for key, value in candidate.provenance.items()
                    if key != "source_attributes"
                }
                candidate_provenance_digest = _digest(candidate.provenance)
                for source_key, value in sorted(raw_attributes.items()):
                    if not isinstance(source_key, str) or not source_key:
                        continue
                    attribute_identity = {
                        "observation_id": observation.observation_id,
                        "source_key": source_key,
                        "value": value,
                    }
                    source_attributes.append(
                        EarthObjectSourceAttribute(
                            attribute_id=f"source-attribute:{_digest(attribute_identity)}",
                            source_observation_id=observation.observation_id,
                            source_dataset=observation.dataset,
                            source_key=source_key,
                            value=value,
                            extraction_method_id=(candidate.mapping_id if candidate else None),
                            uncertainty={},
                            provenance={
                                "semantic_status": "unmapped_source_attribute",
                                "interpretation": "raw_source_value_no_canonical_mapping_asserted",
                                "attribute_uncertainty_status": "not_reported",
                                "candidate_provenance": candidate_context,
                                "candidate_provenance_sha256": candidate_provenance_digest,
                            },
                        )
                    )

        assertions.extend(declaration.derived_assertions)

        # Retain the full canonical source record. Curated summaries can be
        # useful for search, but may not silently discard future contract fields.
        source_snapshot = tuple(item.model_dump(mode="json") for item in ordered)
        evidence_snapshot = tuple(
            evidence_by_id[key].model_dump(mode="json")
            for key in sorted(selected_evidence_ids)
        )
        reproducibility = {
            "materializer_id": self.MATERIALIZER_ID,
            "materializer_version": self.MATERIALIZER_VERSION,
            "source_observation_digests": {
                item.observation_id: _digest(item.model_dump(mode="json"))
                for item in ordered
            },
            "evidence_digests": {
                item["evidence_id"]: _digest(item) for item in evidence_snapshot
            },
        }
        content = {
            "schema_version": "1.0",
            "identity_key": identity,
            "stable_identity": identity,
            "object_type": declaration.object_type,
            "investigation_id": declaration.investigation_id
            or next(
                (
                    item.investigation_id
                    for item in evidence_by_id.values()
                    if item.evidence_id in selected_evidence_ids
                ),
                None,
            ),
            "investigation_ids": tuple(
                sorted(
                    {
                        item.investigation_id
                        for item in evidence_by_id.values()
                        if item.evidence_id in selected_evidence_ids
                    }
                    | (
                        {declaration.investigation_id}
                        if declaration.investigation_id
                        else set()
                    )
                    | (set(previous.investigation_ids) if previous else set())
                )
            ),
            "geometry": geometry,
            "crs": crs,
            "temporal_validity": temporal_validity.model_dump(mode="json")
            if temporal_validity
            else None,
            "measurements": [item.model_dump(mode="json") for item in measurements],
            "property_assertions": [
                item.model_dump(mode="json") for item in assertions
            ],
            "source_attributes": [
                item.model_dump(mode="json") for item in source_attributes
            ],
            "uncertainty": {
                **{item.observation_id: item.uncertainty for item in ordered},
                **({"derived": declaration.derived_uncertainty}
                   if declaration.derived_uncertainty else {}),
            },
            "source_observation_ids": tuple(item.observation_id for item in ordered),
            "evidence_ids": tuple(sorted(selected_evidence_ids)),
            "supporting_evidence_ids": tuple(sorted(supporting_evidence_ids)),
            "conflicting_evidence_ids": tuple(sorted(conflicting_evidence_ids)),
            "unresolved_evidence_ids": tuple(sorted(unresolved_evidence_ids)),
            "lifecycle": declaration.lifecycle
            or (previous.lifecycle if previous else "unknown"),
            "created_at": declaration.created_at
            or (previous.created_at if previous else None),
            "provenance": {
                "declaration": declaration.model_dump(mode="json"),
                "declared_provenance": declaration.declared_provenance,
                "source_records": source_snapshot,
                "evidence_records": evidence_snapshot,
            },
            "reproducibility": reproducibility,
        }
        content_sha256 = _digest(content)
        if previous is not None and previous.content_sha256 == content_sha256:
            return previous
        revision = previous.revision + 1 if previous else 1
        object_id = (
            f"earth-object:{_digest(identity)[:16]}:r{revision}-{content_sha256[:12]}"
        )
        content.pop("identity_key")
        return EarthObject(
            **content,
            object_id=object_id,
            revision=revision,
            content_sha256=content_sha256,
            supersedes_object_id=previous.object_id if previous else None,
        )


class EarthObjectCatalog:
    """Thread-safe immutable object revisions and evidence-backed edges."""

    def __init__(self) -> None:
        self._objects: dict[str, EarthObject] = {}
        self._relationships: dict[str, EarthObjectRelationship] = {}
        self._lock = threading.RLock()

    def put(self, item: EarthObject) -> None:
        with self._lock:
            current = self._objects.get(item.object_id)
            if current is not None and current != item:
                raise ValueError(
                    "Earth Object revisions are immutable; use a new revision ID"
                )
            if current == item:
                return
            history = tuple(
                value
                for value in self._objects.values()
                if value.stable_identity == item.stable_identity
            )
            latest = max(history, key=lambda value: value.revision, default=None)
            if latest is None:
                if item.revision != 1 or item.supersedes_object_id is not None:
                    raise ValueError(
                        "the first Earth Object revision must start at revision 1"
                    )
            elif (
                item.supersedes_object_id != latest.object_id
                or item.revision != latest.revision + 1
            ):
                raise ValueError(
                    "Earth Object revision does not extend the latest catalog revision"
                )
            if item.supersedes_object_id:
                previous = self._objects.get(item.supersedes_object_id)
                if (
                    previous is None
                    or previous.stable_identity != item.stable_identity
                    or item.revision != previous.revision + 1
                ):
                    raise ValueError(
                        "superseded object revision is missing or has another identity"
                    )
            self._objects[item.object_id] = item

    def put_relationship(self, item: EarthObjectRelationship) -> None:
        with self._lock:
            if (
                item.source_object_id not in self._objects
                or item.target_object_id not in self._objects
            ):
                raise ValueError(
                    "Earth Object relationship endpoints must exist in the catalog"
                )
            valid_evidence = set(
                self._objects[item.source_object_id].evidence_ids
            ) | set(self._objects[item.target_object_id].evidence_ids)
            if not set(item.evidence_ids).issubset(valid_evidence):
                raise ValueError(
                    "relationship references evidence absent from its endpoint objects"
                )
            valid_observations = set(
                self._objects[item.source_object_id].source_observation_ids
            ) | set(self._objects[item.target_object_id].source_observation_ids)
            if not set(item.observation_ids).issubset(valid_observations):
                raise ValueError(
                    "relationship references observations absent from its endpoint objects"
                )
            current = self._relationships.get(item.relationship_id)
            if current is not None and current != item:
                raise ValueError("Earth Object relationships are immutable")
            self._relationships[item.relationship_id] = item

    def get(self, object_id: str) -> EarthObject | None:
        with self._lock:
            return self._objects.get(object_id)

    def all(self) -> tuple[EarthObject, ...]:
        with self._lock:
            return tuple(self._objects[key] for key in sorted(self._objects))

    def current(self) -> tuple[EarthObject, ...]:
        """Return one latest immutable revision per stable object identity."""
        with self._lock:
            latest: dict[str, EarthObject] = {}
            for item in self._objects.values():
                identity = item.stable_identity or item.object_id
                previous = latest.get(identity)
                if previous is None or (item.revision, item.object_id) > (
                    previous.revision,
                    previous.object_id,
                ):
                    latest[identity] = item
        return tuple(sorted(latest.values(), key=lambda item: (item.stable_identity or "", item.object_id)))

    def graph(self, object_ids: tuple[str, ...] | None = None) -> EarthObjectGraph:
        with self._lock:
            selected_ids = (
                set(object_ids) if object_ids is not None else set(self._objects)
            )
            selected = tuple(
                self._objects[key]
                for key in sorted(selected_ids)
                if key in self._objects
            )
            edges = tuple(
                self._relationships[key]
                for key in sorted(self._relationships)
                if self._relationships[key].source_object_id in selected_ids
                and self._relationships[key].target_object_id in selected_ids
            )
        if object_ids is not None and len(selected) != len(selected_ids):
            raise KeyError("one or more requested Earth Objects were not found")
        revision = _digest(
            {
                "objects": [
                    item.content_sha256 or _digest(item.model_dump(mode="json"))
                    for item in selected
                ],
                "relationships": [item.model_dump(mode="json") for item in edges],
            }
        )
        return EarthObjectGraph(
            graph_id="earth-object-graph:" + revision[:24],
            revision=revision,
            objects=selected,
            relationships=edges,
        )


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
