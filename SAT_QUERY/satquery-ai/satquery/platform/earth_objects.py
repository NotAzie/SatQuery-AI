"""Evidence-grounded Earth Object materialization and relationship graphs.

This module does not detect entities or infer their properties. A caller must
declare an entity's type and stable source identity; the materializer copies
only cited canonical measurements and preserves source geometry/provenance.
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
    EarthObjectGraph,
    EarthObjectPropertyAssertion,
    EarthObjectRelationship,
    Evidence,
    Observation,
    TemporalExtent,
)


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
    declared_provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_declaration(self) -> EarthObjectDeclaration:
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
        return self


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

        ordered = tuple(by_id[key] for key in sorted(observation_ids))
        geometry_fingerprints = {
            _digest(item.geometry) for item in ordered if item.geometry is not None
        }
        geometries = [item.geometry for item in ordered if item.geometry is not None]
        geometry = (
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
        for observation in ordered:
            observation_evidence = tuple(
                sorted(
                    item.evidence_id
                    for item in evidence_by_id.values()
                    if item.observation_id == observation.observation_id
                    and item.evidence_id in selected_evidence_ids
                )
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
            "uncertainty": {item.observation_id: item.uncertainty for item in ordered},
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
