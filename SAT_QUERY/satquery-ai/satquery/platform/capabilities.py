"""Deterministic, evidence-preserving Earth capability matrix snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, Literal, Optional

from pydantic import Field

from .contracts import (
    ConnectorMetadata,
    Contract,
    DatasetMetadata,
    DatasetReference,
    TemporalExtent,
)
from .modalities import (
    EARTH_SENSING_MODALITIES,
    SensingModalityRegistry,
    infer_modalities,
)
from .ontology import EARTH_VARIABLE_ONTOLOGY, EarthVariableOntology


class EarthCapabilityVariable(Contract):
    """A dataset's source variable and its conservative ontology mapping."""

    source_name: str = Field(min_length=1)
    canonical_name: Optional[str] = None
    concept_id: Optional[str] = None
    ontology_uri: Optional[str] = None
    unit: Optional[str] = None


class EarthCapabilityEntry(Contract):
    """Capabilities declared by one dataset or one connector implementation."""

    connector_id: str = Field(min_length=1)
    connector_name: str = Field(min_length=1)
    connector_version: str = Field(min_length=1)
    provider_version: Optional[str] = None
    provider: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_version: Optional[str] = None
    dataset_reference: Optional[DatasetReference] = None
    dataset_metadata: Optional[DatasetMetadata] = Field(default=None, exclude=True)
    scope: Literal["dataset", "implementation"]
    implementation_capabilities: tuple[str, ...] = ()
    declared_dataset_references: tuple[DatasetReference, ...] = ()
    modalities: tuple[str, ...] = ()
    variables: tuple[EarthCapabilityVariable, ...] = ()
    capabilities: tuple[str, ...] = ()
    spatial_coverage: Optional[dict[str, object]] = None
    temporal_coverage: Optional[TemporalExtent] = None
    connector_temporal_coverage: Optional[TemporalExtent] = None
    historical_coverage: Optional[TemporalExtent] = None
    forecast_coverage: Optional[TemporalExtent] = None
    supports_historical: Optional[bool] = None
    supports_forecast: Optional[bool] = None
    spatial_resolution: Optional[float] = None
    resolution_unit: Optional[str] = None
    crs: Optional[str] = None
    latency: Optional[str] = None
    update_frequency: Optional[str] = None
    quality_metadata: dict[str, object] = Field(default_factory=dict)
    uncertainty_metadata: dict[str, object] = Field(default_factory=dict)
    confidence_available: Optional[bool] = None
    licensing: Optional[str] = None
    access_policy: dict[str, object] = Field(default_factory=dict)
    access_limitations: tuple[str, ...] = ()
    authentication_required: Optional[bool] = None
    authentication_schemes: tuple[str, ...] = ()
    asset_references_declared: bool = False
    asset_reference_count: int = Field(default=0, ge=0)
    supports_streaming: Optional[bool] = None
    connector_registered: bool = False
    connector_available: Optional[bool] = None
    connector_health: Literal["unknown", "healthy", "degraded", "unhealthy"] = "unknown"
    connector_priority: int = 0
    supported_regions: tuple[str, ...] = ()
    supported_spatial_types: tuple[str, ...] = ()
    supports_temporal_query: bool = False
    supported_query_fields: tuple[str, ...] = ()
    fallback_for: tuple[str, ...] = ()
    quota_metadata: dict[str, object] = Field(default_factory=dict)
    documentation_url: Optional[str] = None
    field_provenance: dict[str, str] = Field(default_factory=dict)
    source_metadata: dict[str, object] = Field(default_factory=dict, exclude=True)
    provider_metadata: dict[str, object] = Field(default_factory=dict, exclude=True)


class EarthModalityCapability(Contract):
    modality_id: str = Field(min_length=1)
    label: Optional[str] = None
    description: Optional[str] = None
    status: Literal["registered", "unavailable", "declared", "not_registered"]
    implementation_ids: tuple[str, ...] = ()
    dataset_ids: tuple[str, ...] = ()
    variables: tuple[str, ...] = ()


class EarthCapabilityMatrix(Contract):
    """A point-in-time metadata view; registration is not an availability promise."""

    revision: str = Field(min_length=1)
    entries: tuple[EarthCapabilityEntry, ...] = ()
    modalities: tuple[EarthModalityCapability, ...] = ()

    @property
    def datasets(self) -> tuple[DatasetMetadata, ...]:
        """Dataset records represented by this snapshot, for legacy selectors."""
        values = {
            (
                entry.dataset_metadata.connector_id,
                entry.dataset_metadata.dataset_id,
                entry.dataset_metadata.version,
            ): entry.dataset_metadata
            for entry in self.entries
            if entry.dataset_metadata is not None
        }
        return tuple(
            values[key]
            for key in sorted(
                values, key=lambda item: (item[0], item[1], item[2] or "")
            )
        )


def build_earth_capability_matrix(
    connectors: Iterable[ConnectorMetadata],
    datasets: Iterable[DatasetMetadata],
    *,
    modality_registry: SensingModalityRegistry = EARTH_SENSING_MODALITIES,
    ontology: EarthVariableOntology = EARTH_VARIABLE_ONTOLOGY,
) -> EarthCapabilityMatrix:
    """Build a stable matrix without upgrading missing metadata into claims."""
    connector_values = tuple(sorted(connectors, key=lambda item: item.connector_id))
    dataset_values = tuple(
        sorted(
            datasets,
            key=lambda item: (
                item.connector_id,
                item.dataset_id,
                item.version or "",
            ),
        )
    )
    by_connector: dict[str, list[DatasetMetadata]] = {}
    for dataset in dataset_values:
        by_connector.setdefault(dataset.connector_id, []).append(dataset)

    entries: list[EarthCapabilityEntry] = []
    for connector in connector_values:
        connector_datasets = by_connector.get(connector.connector_id, [])
        if connector_datasets:
            entries.extend(
                _dataset_entry(
                    connector,
                    dataset,
                    modality_registry=modality_registry,
                    ontology=ontology,
                )
                for dataset in connector_datasets
            )
        else:
            entries.append(
                _implementation_entry(
                    connector,
                    modality_registry=modality_registry,
                    ontology=ontology,
                )
            )
    registered_connector_ids = {item.connector_id for item in connector_values}
    for dataset in dataset_values:
        if dataset.connector_id not in registered_connector_ids:
            entries.append(
                _unbound_dataset_entry(
                    dataset,
                    modality_registry=modality_registry,
                    ontology=ontology,
                )
            )

    entries.sort(
        key=lambda item: (
            item.connector_id,
            item.dataset_id or "",
            item.dataset_version or "",
            item.scope,
        )
    )
    modality_capabilities = _summarize_modalities(entries, modality_registry)
    payload = {
        "entries": [item.model_dump(mode="json") for item in entries],
        "modalities": [item.model_dump(mode="json") for item in modality_capabilities],
        "dataset_metadata": [item.model_dump(mode="json") for item in dataset_values],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return EarthCapabilityMatrix(
        revision=hashlib.sha256(encoded).hexdigest(),
        entries=tuple(entries),
        modalities=modality_capabilities,
    )


def _dataset_entry(
    connector: ConnectorMetadata,
    dataset: DatasetMetadata,
    *,
    modality_registry: SensingModalityRegistry,
    ontology: EarthVariableOntology,
) -> EarthCapabilityEntry:
    variables = _variables(dataset.variables, dataset.units, ontology)
    inferred = infer_modalities(dataset.variables, modality_registry)
    modalities = tuple(modality_registry.canonicalize((*dataset.modalities, *inferred)))
    provider = dataset.provider
    if provider.casefold() == "unknown":
        candidate = connector.provider_metadata.get("provider")
        provider = (
            candidate if isinstance(candidate, str) and candidate.strip() else None
        )
    limitations = dataset.access_policy.get("limitations", ())
    if isinstance(limitations, str):
        limitations = (limitations,)
    if not isinstance(limitations, (list, tuple)) or any(
        not isinstance(value, str) for value in limitations
    ):
        limitations = ()
    return EarthCapabilityEntry(
        connector_id=connector.connector_id,
        connector_name=connector.name,
        connector_version=connector.version,
        provider_version=connector.provider_version,
        provider=provider,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_reference=_safe_dataset_reference(dataset),
        dataset_metadata=dataset,
        scope="dataset",
        implementation_capabilities=connector.capabilities,
        declared_dataset_references=tuple(
            _safe_dataset_reference(reference) for reference in connector.datasets
        ),
        modalities=modalities,
        variables=variables,
        capabilities=dataset.capabilities,
        spatial_coverage=dataset.spatial_coverage,
        temporal_coverage=dataset.temporal_coverage,
        connector_temporal_coverage=_connector_temporal_coverage(connector),
        historical_coverage=dataset.historical_coverage,
        forecast_coverage=dataset.forecast_coverage,
        supports_historical=dataset.supports_historical,
        supports_forecast=dataset.supports_forecast,
        spatial_resolution=dataset.spatial_resolution,
        resolution_unit=dataset.resolution_unit,
        crs=dataset.crs,
        latency=dataset.latency,
        update_frequency=dataset.update_frequency,
        quality_metadata=dataset.quality_characteristics,
        uncertainty_metadata=dataset.uncertainty_characteristics,
        confidence_available=dataset.confidence_available,
        licensing=dataset.licensing or connector.license,
        access_policy=dataset.access_policy,
        access_limitations=tuple(limitations),
        authentication_required=_authentication_required(connector),
        authentication_schemes=connector.authentication_schemes,
        asset_references_declared=bool(dataset.assets),
        asset_reference_count=len(dataset.assets),
        supports_streaming=connector.supports_streaming,
        connector_registered=True,
        connector_available=connector.available,
        connector_health=connector.health,
        connector_priority=connector.priority,
        supported_regions=connector.supported_regions,
        supported_spatial_types=connector.supported_spatial_types,
        supports_temporal_query=connector.supports_temporal_query,
        supported_query_fields=connector.supported_query_fields,
        fallback_for=connector.fallback_for,
        quota_metadata=connector.quota,
        documentation_url=connector.documentation_url,
        field_provenance=_dataset_field_provenance(dataset, connector),
        source_metadata=dataset.metadata,
        provider_metadata=connector.provider_metadata,
    )


def _implementation_entry(
    connector: ConnectorMetadata,
    *,
    modality_registry: SensingModalityRegistry,
    ontology: EarthVariableOntology,
) -> EarthCapabilityEntry:
    return EarthCapabilityEntry(
        connector_id=connector.connector_id,
        connector_name=connector.name,
        connector_version=connector.version,
        provider_version=connector.provider_version,
        provider=(
            connector.provider_metadata.get("provider")
            if isinstance(connector.provider_metadata.get("provider"), str)
            else None
        ),
        scope="implementation",
        implementation_capabilities=connector.capabilities,
        declared_dataset_references=tuple(
            _safe_dataset_reference(reference) for reference in connector.datasets
        ),
        modalities=tuple(modality_registry.canonicalize(connector.modalities)),
        variables=_variables(connector.supported_variables, {}, ontology),
        capabilities=connector.capabilities,
        temporal_coverage=_connector_temporal_coverage(connector),
        connector_temporal_coverage=_connector_temporal_coverage(connector),
        supports_historical=None,
        licensing=connector.license,
        authentication_required=_authentication_required(connector),
        authentication_schemes=connector.authentication_schemes,
        supports_streaming=connector.supports_streaming,
        connector_registered=True,
        connector_available=connector.available,
        connector_health=connector.health,
        connector_priority=connector.priority,
        supported_regions=connector.supported_regions,
        supported_spatial_types=connector.supported_spatial_types,
        supports_temporal_query=connector.supports_temporal_query,
        supported_query_fields=connector.supported_query_fields,
        fallback_for=connector.fallback_for,
        quota_metadata=connector.quota,
        documentation_url=connector.documentation_url,
        field_provenance={
            "modalities": "connector-declaration",
            "variables": "connector-declaration+ontology-resolution",
            "authentication": (
                "connector-declaration"
                if connector.authentication_required is not None
                or connector.authentication_schemes
                else "unknown"
            ),
            "streaming": (
                "connector-declaration"
                if connector.supports_streaming is not None
                else "unknown"
            ),
        },
        provider_metadata=connector.provider_metadata,
    )


def _variables(
    source_names: Iterable[str],
    units: dict[str, str],
    ontology: EarthVariableOntology,
) -> tuple[EarthCapabilityVariable, ...]:
    result = []
    for source_name in sorted(set(source_names), key=str.casefold):
        variable = ontology.resolve_variable(source_name)
        result.append(
            EarthCapabilityVariable(
                source_name=source_name,
                canonical_name=variable.canonical_name if variable else None,
                concept_id=variable.concept_id if variable else None,
                ontology_uri=variable.ontology_uri if variable else None,
                unit=units.get(source_name),
            )
        )
    return tuple(result)


def _authentication_required(connector: ConnectorMetadata) -> Optional[bool]:
    if connector.authentication_required is not None:
        return connector.authentication_required
    if connector.authentication_schemes:
        return True
    return None


def _safe_dataset_reference(
    reference: DatasetMetadata | DatasetReference,
) -> DatasetReference:
    """Expose catalog identity without serializing raw metadata or asset URLs."""
    return DatasetReference(
        connector_id=reference.connector_id,
        dataset_id=reference.dataset_id,
        version=reference.version,
    )


def _connector_temporal_coverage(
    connector: ConnectorMetadata,
) -> Optional[TemporalExtent]:
    if connector.temporal_start is None and connector.temporal_end is None:
        return None
    return TemporalExtent(start=connector.temporal_start, end=connector.temporal_end)


def _unbound_dataset_entry(
    dataset: DatasetMetadata,
    *,
    modality_registry: SensingModalityRegistry,
    ontology: EarthVariableOntology,
) -> EarthCapabilityEntry:
    """Keep manually registered metadata visible without implying an adapter exists."""
    placeholder = ConnectorMetadata(
        connector_id=dataset.connector_id,
        name=dataset.connector_id,
        version="unknown",
    )
    entry = _dataset_entry(
        placeholder,
        dataset,
        modality_registry=modality_registry,
        ontology=ontology,
    )
    provenance = dict(entry.field_provenance)
    provenance.update(
        {
            "connector": "not-registered",
            "authentication": "unknown",
            "streaming": "unknown",
            "health": "unknown",
        }
    )
    return entry.model_copy(
        update={
            "connector_registered": False,
            "connector_available": None,
            "supports_streaming": None,
            "authentication_required": None,
            "authentication_schemes": (),
            "field_provenance": provenance,
        }
    )


def _dataset_field_provenance(
    dataset: DatasetMetadata, connector: ConnectorMetadata
) -> dict[str, str]:
    provenance = {
        field: "dataset-metadata"
        for field in (
            "variables",
            "units",
            "modalities",
            "spatial_coverage",
            "temporal_coverage",
            "historical_coverage",
            "forecast_coverage",
            "spatial_resolution",
            "resolution_unit",
            "crs",
            "latency",
            "update_frequency",
            "quality_metadata",
            "uncertainty_metadata",
            "confidence_available",
            "licensing",
            "access_policy",
            "assets",
        )
    }
    provenance["licensing"] = (
        "dataset-metadata"
        if dataset.licensing is not None
        else "connector-declaration"
        if connector.license is not None
        else "unknown"
    )
    provenance["provider"] = (
        "dataset-metadata"
        if dataset.provider.casefold() != "unknown"
        else "connector-provider-metadata"
        if isinstance(connector.provider_metadata.get("provider"), str)
        else "unknown"
    )
    provenance.update(
        {
            "canonical_variable": "earth-variable-ontology",
            "authentication": (
                "connector-declaration"
                if connector.authentication_required is not None
                or connector.authentication_schemes
                else "unknown"
            ),
            "streaming": (
                "connector-declaration"
                if connector.supports_streaming is not None
                else "unknown"
            ),
            "health": "connector-diagnostic",
        }
    )
    return provenance


def _summarize_modalities(
    entries: Iterable[EarthCapabilityEntry],
    modality_registry: SensingModalityRegistry,
) -> tuple[EarthModalityCapability, ...]:
    values = tuple(entries)
    summaries = []
    known_modalities = {
        modality.modality_id: modality for modality in modality_registry.modalities()
    }
    modality_ids = sorted(
        set(known_modalities)
        | {modality for entry in values for modality in entry.modalities}
    )
    for modality_id in modality_ids:
        modality = known_modalities.get(modality_id)
        matching = tuple(item for item in values if modality_id in item.modalities)
        available = tuple(
            item
            for item in matching
            if item.connector_registered
            and item.connector_available
            and item.connector_health != "unhealthy"
        )
        registered = tuple(item for item in matching if item.connector_registered)
        contributing = available or registered or matching
        status = (
            "registered"
            if available
            else "unavailable"
            if registered
            else "declared"
            if matching
            else "not_registered"
        )
        dataset_ids = tuple(
            sorted(
                {
                    f"{item.connector_id}:{item.dataset_id}"
                    for item in contributing
                    if item.dataset_id is not None
                }
            )
        )
        variables = tuple(
            sorted(
                {
                    variable.canonical_name
                    for item in contributing
                    for variable in item.variables
                    if variable.canonical_name is not None
                }
            )
        )
        summaries.append(
            EarthModalityCapability(
                modality_id=modality_id,
                label=modality.label if modality is not None else None,
                description=modality.description if modality is not None else None,
                status=status,
                implementation_ids=tuple(
                    sorted({item.connector_id for item in contributing})
                ),
                dataset_ids=dataset_ids,
                variables=variables,
            )
        )
    return tuple(summaries)
