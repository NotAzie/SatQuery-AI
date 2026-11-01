"""Conservative semantic naming for measurements without unit conversion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .contracts import CanonicalMeasurement, DatasetMetadata, Observation
from .ontology import EARTH_VARIABLE_ONTOLOGY, EarthVariableOntology


@dataclass(frozen=True)
class VariableSemantic:
    canonical_name: str
    standard_name: Optional[str] = None
    ontology_uri: Optional[str] = None
    aliases: tuple[str, ...] = ()
    unit_dimension: Optional[str] = None


class SemanticNormalizer:
    """Maps known source variable names to canonical names, preserving inputs."""

    VERSION = "1.0"

    def __init__(
        self,
        aliases: Optional[
            Mapping[str, VariableSemantic | str | Mapping[str, Any]]
        ] = None,
        *,
        observation_types: Optional[Mapping[str, str]] = None,
        categories: Optional[Mapping[str, Mapping[str, str]]] = None,
        dataset_vocabulary: Optional[Mapping[str, str]] = None,
        ontology: EarthVariableOntology = EARTH_VARIABLE_ONTOLOGY,
    ) -> None:
        self._aliases: dict[str, VariableSemantic] = {}
        for source_name, semantic in (aliases or {}).items():
            if isinstance(semantic, VariableSemantic):
                resolved = semantic
            elif isinstance(semantic, str):
                resolved = VariableSemantic(canonical_name=semantic)
            elif isinstance(semantic, Mapping):
                resolved = VariableSemantic(**dict(semantic))
            else:
                raise ValueError(f"invalid semantic mapping for {source_name!r}")
            self._aliases[source_name.casefold()] = resolved
            for alias in resolved.aliases:
                self._aliases[alias.casefold()] = resolved
        self._observation_types = {
            source.casefold(): canonical
            for source, canonical in (observation_types or {}).items()
        }
        self._categories = {
            variable.casefold(): {
                source.casefold(): canonical for source, canonical in mapping.items()
            }
            for variable, mapping in (categories or {}).items()
        }
        self._dataset_vocabulary = {
            source.casefold(): canonical
            for source, canonical in (dataset_vocabulary or {}).items()
        }
        self.ontology = ontology
        self.revision = _normalizer_revision(
            self._aliases,
            self._observation_types,
            self._categories,
            self._dataset_vocabulary,
            ontology,
        self.VERSION,
        )

    def normalize_measurement(
        self,
        source_name: str,
        value: Any,
        *,
        unit: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        semantic = self._aliases.get(source_name.casefold())
        if semantic is None:
            earth_variable = self.ontology.resolve_variable(source_name)
            semantic = (
                VariableSemantic(
                    canonical_name=earth_variable.canonical_name,
                    standard_name=earth_variable.standard_name,
                    ontology_uri=earth_variable.ontology_uri
                    or f"urn:satquery:earth-variable:{earth_variable.canonical_name}",
                    unit_dimension=earth_variable.unit_dimension,
                )
                if earth_variable is not None
                else VariableSemantic(canonical_name=source_name)
            )
        result: dict[str, Any] = {
            "value": value,
            "unit": unit,
            "source_name": source_name,
            "source_unit": unit,
        }
        if semantic.standard_name is not None:
            result["standard_name"] = semantic.standard_name
        if semantic.ontology_uri is not None:
            result["ontology_uri"] = semantic.ontology_uri
        if semantic.unit_dimension is not None:
            result["unit_dimension"] = semantic.unit_dimension
        if metadata:
            result["source_metadata"] = dict(metadata)
        return {semantic.canonical_name: result}

    def normalize_category(self, variable: str, value: Any) -> dict[str, Any]:
        """Map an explicitly declared category while preserving the source label."""
        if not isinstance(value, str):
            return {"value": value, "source_value": value}
        canonical = self._categories.get(variable.casefold(), {}).get(value.casefold())
        return {
            "value": canonical if canonical is not None else value,
            "source_value": value,
            "normalized": canonical is not None,
        }

    def harmonize_observation(self, observation: Observation) -> Observation:
        """Normalize known semantics without mutating source measurements or metadata."""
        normalized: dict[str, Any] = {}
        canonical_measurements: list[CanonicalMeasurement] = []
        for source_name, raw in observation.measured_variables.items():
            semantic = self._aliases.get(source_name.casefold())
            resolved = (
                semantic is not None
                or self.ontology.resolve_variable(source_name) is not None
            )
            if isinstance(raw, Mapping) and "value" in raw:
                unit = raw.get("unit") if isinstance(raw.get("unit"), str) else None
                raw_value = raw["value"]
                measurement = self.normalize_measurement(
                    source_name,
                    raw_value,
                    unit=unit,
                    metadata=raw,
                )
            else:
                raw_value = raw
                unit = None
                measurement = self.normalize_measurement(source_name, raw)
            for canonical, value in measurement.items():
                values = value if isinstance(value, list) else [value]
                for item in values:
                    canonical_measurements.append(
                        CanonicalMeasurement(
                            canonical_variable=canonical,
                            value=item.get("value")
                            if isinstance(item, Mapping)
                            else raw_value,
                            unit=item.get("unit")
                            if isinstance(item, Mapping)
                            else unit,
                            source_variable=source_name,
                            source_unit=unit,
                            ontology_uri=(
                                item.get("ontology_uri")
                                if isinstance(item, Mapping)
                                else None
                            ),
                            semantic_status="resolved" if resolved else "unresolved",
                            source_metadata=(
                                dict(raw) if isinstance(raw, Mapping) else {}
                            ),
                            observation_id=observation.observation_id,
                        )
                    )
                if canonical in normalized:
                    previous = normalized[canonical]
                    previous_values = (
                        previous if isinstance(previous, list) else [previous]
                    )
                    normalized[canonical] = [*previous_values, value]
                else:
                    normalized[canonical] = value
        properties = dict(observation.properties)
        properties["source_observation_type"] = observation.observation_type
        normalized_type = (
            self._observation_types.get(observation.observation_type.casefold())
            if observation.observation_type is not None
            else None
        )
        if observation.crs is not None:
            from .spatial import normalize_crs

            properties["source_crs"] = observation.crs
            canonical_crs = normalize_crs(observation.crs)
        else:
            canonical_crs = None
        return observation.model_copy(
            update={
                "measured_variables": normalized,
                "canonical_measurements": tuple(canonical_measurements),
                "observation_type": normalized_type or observation.observation_type,
                "crs": canonical_crs or observation.crs,
                "properties": properties,
            }
        )

    def canonicalize_observation(self, observation: Observation) -> Observation:
        """Add semantic measurement records while preserving provider fields.

        This is the safe default for platform ingestion: ``measured_variables``
        remains the provider's original mapping. Existing connector-supplied
        canonical records are authoritative and are retained unchanged.
        """
        existing = list(observation.canonical_measurements)
        represented_sources = {item.source_variable for item in existing}
        additions: list[CanonicalMeasurement] = []
        for source_name, raw in observation.measured_variables.items():
            if source_name in represented_sources:
                continue
            if isinstance(raw, Mapping) and "value" in raw:
                source_value = raw["value"]
                source_unit = raw.get("unit") if isinstance(raw.get("unit"), str) else None
                source_metadata = dict(raw)
            else:
                source_value = raw
                source_unit = None
                source_metadata = {}
            normalized = self.normalize_measurement(
                source_name,
                source_value,
                unit=source_unit,
                metadata=source_metadata,
            )
            for canonical_variable, metadata in normalized.items():
                semantic = self._aliases.get(source_name.casefold())
                resolved = semantic is not None or self.ontology.resolve_variable(source_name) is not None
                additions.append(CanonicalMeasurement(
                    canonical_variable=canonical_variable,
                    value=source_value,
                    unit=source_unit,
                    source_variable=source_name,
                    source_unit=source_unit,
                    ontology_uri=metadata.get("ontology_uri"),
                    semantic_status="resolved" if resolved else "unresolved",
                    source_metadata=source_metadata,
                    observation_id=observation.observation_id,
                ))
        if not additions:
            return observation
        return observation.model_copy(update={
            "canonical_measurements": tuple((*existing, *additions)),
        })

    def harmonize_dataset(self, dataset: DatasetMetadata) -> DatasetMetadata:
        """Normalize declared dataset vocabulary and retain source terms."""
        normalized_variables = tuple(
            self._dataset_vocabulary.get(
                variable.casefold(),
                (
                    earth_variable.canonical_name
                    if (earth_variable := self.ontology.resolve_variable(variable))
                    is not None
                    else variable
                ),
            )
            for variable in dataset.variables
        )
        metadata = dict(dataset.metadata)
        metadata["source_variables"] = dataset.variables
        return dataset.model_copy(
            update={"variables": normalized_variables, "metadata": metadata}
        )


def _normalizer_revision(
    aliases: Mapping[str, VariableSemantic],
    observation_types: Mapping[str, str],
    categories: Mapping[str, Mapping[str, str]],
    dataset_vocabulary: Mapping[str, str],
    ontology: EarthVariableOntology,
    version: str,
) -> str:
    payload = {
        "normalizer_version": version,
        "aliases": {
            key: {
                "canonical_name": value.canonical_name,
                "standard_name": value.standard_name,
                "ontology_uri": value.ontology_uri,
                "aliases": value.aliases,
                "unit_dimension": value.unit_dimension,
            }
            for key, value in sorted(aliases.items())
        },
        "observation_types": dict(sorted(observation_types.items())),
        "categories": {
            key: dict(sorted(value.items()))
            for key, value in sorted(categories.items())
        },
        "dataset_vocabulary": dict(sorted(dataset_vocabulary.items())),
        "ontology": [
            {
                "canonical_name": item.canonical_name,
                "concept_id": item.concept_id,
                "aliases": item.aliases,
                "standard_name": item.standard_name,
                "ontology_uri": item.ontology_uri,
                "unit_dimension": item.unit_dimension,
                "canonical_units": item.canonical_units,
            }
            for item in ontology.variables
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
