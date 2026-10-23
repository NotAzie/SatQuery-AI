"""Versionable data contracts shared by platform subsystems."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


def _is_geographic_crs(crs: str) -> bool:
    return crs.casefold() in {
        "crs84",
        "ogc:crs84",
        "epsg:4326",
        "urn:ogc:def:crs:ogc:1.3:crs84",
    }


def _validate_geojson_geometry(geometry: Dict[str, Any], crs: Optional[str]) -> None:
    """Validate GeoJSON structure and finite coordinates, not topology."""

    def position(value: Any) -> bool:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return False
        if any(
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(item)
            for item in value
        ):
            return False
        return not (
            crs is not None
            and _is_geographic_crs(crs)
            and (
                not -180 <= value[0] <= 180
                or not -90 <= value[1] <= 90
            )
        )

    def ring(value: Any) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) >= 4
            and all(position(item) for item in value)
            and value[0] == value[-1]
        )

    def line(value: Any) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and all(position(item) for item in value)
        )

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    valid = False
    if geometry_type == "GeometryCollection":
        geometries = geometry.get("geometries")
        valid = isinstance(geometries, (list, tuple)) and all(
            isinstance(item, dict)
            and _validate_geojson_geometry(item, crs) is None
            for item in geometries
        )
    elif geometry_type == "Point":
        valid = position(coordinates)
    elif geometry_type == "MultiPoint":
        valid = isinstance(coordinates, (list, tuple)) and all(
            position(item) for item in coordinates
        )
    elif geometry_type == "LineString":
        valid = isinstance(coordinates, (list, tuple)) and (
            not coordinates or line(coordinates)
        )
    elif geometry_type == "MultiLineString":
        valid = isinstance(coordinates, (list, tuple)) and all(
            line(item) for item in coordinates
        )
    elif geometry_type == "Polygon":
        valid = isinstance(coordinates, (list, tuple)) and all(
            ring(item) for item in coordinates
        )
    elif geometry_type == "MultiPolygon":
        valid = isinstance(coordinates, (list, tuple)) and all(
            isinstance(polygon, (list, tuple))
            and bool(polygon)
            and all(ring(item) for item in polygon)
            for polygon in coordinates
        )

    if not valid:
        raise ValueError(
            "geometry must be a structurally valid GeoJSON geometry with finite "
            "coordinates compatible with its declared CRS"
        )


class _FrozenDict(dict):
    """JSON-serializable dict that rejects mutation after contract creation."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("contract data is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __deepcopy__(self, _memo: dict[int, Any]) -> "_FrozenDict":
        return self


class _FrozenList(list):
    """JSON-serializable list that preserves list equality and rejects edits."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("contract data is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __deepcopy__(self, _memo: dict[int, Any]) -> "_FrozenList":
        return self


def _freeze_contract_data(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict(
            (key, _freeze_contract_data(item)) for key, item in value.items()
        )
    if isinstance(value, list):
        return _FrozenList(_freeze_contract_data(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_contract_data(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_contract_data(item) for item in value)
    return value


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_version: ClassVar[int] = 1

    def model_post_init(self, _context: Any) -> None:
        self._freeze_fields()

    def model_copy(
        self, *, update: Optional[Dict[str, Any]] = None, deep: bool = False
    ):
        copied = super().model_copy(update=update, deep=deep)
        copied._freeze_fields()
        return copied

    def _freeze_fields(self) -> None:
        for name, value in tuple(self.__dict__.items()):
            object.__setattr__(self, name, _freeze_contract_data(value))


class MissionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InvestigationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ExecutionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Mission(Contract):
    mission_id: str = Field(default_factory=_new_id, min_length=1)
    name: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    status: MissionStatus = MissionStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DatasetReference(Contract):
    connector_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    version: Optional[str] = None
    uri: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EarthStationCandidate(Contract):
    """Provider-declared station metadata for user-directed source selection."""

    station_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    name: str = Field(min_length=1)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    modalities: Tuple[str, ...] = ()
    variables: Tuple[str, ...] = ()
    source_metadata: Dict[str, Any] = Field(default_factory=dict)


class EarthStationSearchResult(Contract):
    """Spatially filtered station candidates, not observations or coverage claims."""

    provider: str = Field(min_length=1)
    bbox: Tuple[float, float, float, float]
    stations: Tuple[EarthStationCandidate, ...] = ()
    source_record_count: int = Field(ge=0)
    limitations: Tuple[str, ...] = ()


class ObservationAsset(Contract):
    uri: str = Field(min_length=1)
    media_type: Optional[str] = None
    roles: Tuple[str, ...] = ()
    title: Optional[str] = None
    description: Optional[str] = None
    checksum: Optional[str] = None
    capabilities: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TemporalExtent(Contract):
    start: Optional[datetime] = None
    end: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_order(self) -> "TemporalExtent":
        if self.start is not None and self.start.tzinfo is None:
            raise ValueError("temporal extent start must include a timezone")
        if self.end is not None and self.end.tzinfo is None:
            raise ValueError("temporal extent end must include a timezone")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("temporal extent start must not be after end")
        return self


class DatasetMetadata(Contract):
    connector_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    version: Optional[str] = None
    variables: Tuple[str, ...] = ()
    units: Dict[str, str] = Field(default_factory=dict)
    modalities: Tuple[str, ...] = ()
    capabilities: Tuple[str, ...] = ()
    spatial_coverage: Optional[Dict[str, Any]] = None
    temporal_coverage: Optional[TemporalExtent] = None
    historical_coverage: Optional[TemporalExtent] = None
    forecast_coverage: Optional[TemporalExtent] = None
    supports_historical: Optional[bool] = None
    supports_forecast: Optional[bool] = None
    spatial_resolution: Optional[float] = Field(default=None, gt=0)
    resolution_unit: Optional[str] = None
    crs: Optional[str] = None
    update_frequency: Optional[str] = None
    uncertainty_characteristics: Dict[str, Any] = Field(default_factory=dict)
    licensing: Optional[str] = None
    citation: Optional[str] = None
    latency: Optional[str] = None
    access_policy: Dict[str, Any] = Field(default_factory=dict)
    quality_characteristics: Dict[str, Any] = Field(default_factory=dict)
    confidence_available: Optional[bool] = None
    tags: Tuple[str, ...] = ()
    keywords: Tuple[str, ...] = ()
    categories: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()
    deprecated: bool = False
    assets: Dict[str, ObservationAsset] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_spatial_coverage(self) -> "DatasetMetadata":
        if self.spatial_coverage is not None and self.crs is None:
            raise ValueError("dataset spatial coverage requires a declared CRS")
        if any(not value.strip() for value in self.modalities):
            raise ValueError("modalities must not contain empty values")
        if len(self.modalities) != len(set(self.modalities)):
            raise ValueError("modalities must contain unique values")
        if any(
            not key.strip() or not value.strip() for key, value in self.units.items()
        ):
            raise ValueError(
                "unit mappings must contain non-empty variable names and units"
            )
        return self


class DatasetSearchPlan(Contract):
    """Dataset coverage for a request spanning one or more Earth modalities."""

    datasets: Tuple[DatasetMetadata, ...] = ()
    requested_modalities: Tuple[str, ...] = ()
    available_modalities: Tuple[str, ...] = ()
    unavailable_modalities: Tuple[str, ...] = ()
    requested_variables: Tuple[str, ...] = ()
    available_variables: Tuple[str, ...] = ()
    unavailable_variables: Tuple[str, ...] = ()


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
    implementation_capabilities: Tuple[str, ...] = ()
    declared_dataset_references: Tuple[DatasetReference, ...] = ()
    modalities: Tuple[str, ...] = ()
    variables: Tuple[EarthCapabilityVariable, ...] = ()
    capabilities: Tuple[str, ...] = ()
    spatial_coverage: Optional[Dict[str, object]] = None
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
    quality_metadata: Dict[str, object] = Field(default_factory=dict)
    uncertainty_metadata: Dict[str, object] = Field(default_factory=dict)
    confidence_available: Optional[bool] = None
    licensing: Optional[str] = None
    access_policy: Dict[str, object] = Field(default_factory=dict)
    access_limitations: Tuple[str, ...] = ()
    authentication_required: Optional[bool] = None
    authentication_schemes: Tuple[str, ...] = ()
    asset_references_declared: bool = False
    asset_reference_count: int = Field(default=0, ge=0)
    supports_streaming: Optional[bool] = None
    connector_registered: bool = False
    connector_available: Optional[bool] = None
    connector_health: Literal["unknown", "healthy", "degraded", "unhealthy"] = "unknown"
    connector_priority: int = 0
    supported_regions: Tuple[str, ...] = ()
    supported_spatial_types: Tuple[str, ...] = ()
    supports_temporal_query: bool = False
    supported_query_fields: Tuple[str, ...] = ()
    fallback_for: Tuple[str, ...] = ()
    quota_metadata: Dict[str, object] = Field(default_factory=dict)
    documentation_url: Optional[str] = None
    field_provenance: Dict[str, str] = Field(default_factory=dict)
    source_metadata: Dict[str, object] = Field(default_factory=dict, exclude=True)
    provider_metadata: Dict[str, object] = Field(default_factory=dict, exclude=True)


class EarthModalityCapability(Contract):
    modality_id: str = Field(min_length=1)
    label: Optional[str] = None
    description: Optional[str] = None
    status: Literal["registered", "unavailable", "declared", "not_registered"]
    implementation_ids: Tuple[str, ...] = ()
    dataset_ids: Tuple[str, ...] = ()
    variables: Tuple[str, ...] = ()


class EarthCapabilityMatrix(Contract):
    """A point-in-time metadata view; registration is not an availability promise."""

    revision: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    entries: Tuple[EarthCapabilityEntry, ...] = ()
    modalities: Tuple[EarthModalityCapability, ...] = ()

    @property
    def datasets(self) -> Tuple[DatasetMetadata, ...]:
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
            for key in sorted(values, key=lambda item: (item[0], item[1], item[2] or ""))
        )

    def capability_snapshot(self) -> "EarthCapabilitySnapshot":
        return EarthCapabilitySnapshot.from_matrix(self)


class EarthCapabilitySnapshot(Contract):
    """Integrity-checked public selection metadata for one capability revision."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    revision: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    entries: Tuple[EarthCapabilityEntry, ...] = ()
    modalities: Tuple[EarthModalityCapability, ...] = ()
    excluded_metadata: Tuple[str, ...] = (
        "dataset asset URIs and raw dataset metadata",
        "connector source metadata",
        "connector provider metadata",
    )
    snapshot_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @classmethod
    def from_matrix(cls, matrix: EarthCapabilityMatrix) -> "EarthCapabilitySnapshot":
        entries = tuple(
            EarthCapabilityEntry.model_validate(item.model_dump(mode="json"))
            for item in matrix.entries
        )
        modalities = tuple(
            EarthModalityCapability.model_validate(item.model_dump(mode="json"))
            for item in matrix.modalities
        )
        values = {
            "revision": matrix.revision,
            "entries": entries,
            "modalities": modalities,
        }
        return cls(
            **values,
            snapshot_sha256=_earth_capability_snapshot_digest(
                schema_version="1.0.0",
                revision=matrix.revision,
                entries=entries,
                modalities=modalities,
                excluded_metadata=(
                    "dataset asset URIs and raw dataset metadata",
                    "connector source metadata",
                    "connector provider metadata",
                ),
            ),
        )

    @model_validator(mode="after")
    def validate_snapshot_digest(self) -> "EarthCapabilitySnapshot":
        if any(
            item.dataset_metadata is not None
            or item.source_metadata
            or item.provider_metadata
            for item in self.entries
        ):
            raise ValueError("capability snapshot contains excluded raw metadata")
        expected = _earth_capability_snapshot_digest(
            schema_version=self.schema_version,
            revision=self.revision,
            entries=self.entries,
            modalities=self.modalities,
            excluded_metadata=self.excluded_metadata,
        )
        if self.snapshot_sha256 != expected:
            raise ValueError("capability snapshot digest does not match its content")
        return self


def _earth_capability_snapshot_digest(
    *,
    schema_version: str,
    revision: str,
    entries: Tuple[EarthCapabilityEntry, ...],
    modalities: Tuple[EarthModalityCapability, ...],
    excluded_metadata: Tuple[str, ...],
) -> str:
    payload = {
        "schema_version": schema_version,
        "revision": revision,
        "entries": [item.model_dump(mode="json") for item in entries],
        "modalities": [item.model_dump(mode="json") for item in modalities],
        "excluded_metadata": list(excluded_metadata),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ObservationQuality(Contract):
    quality_score: Optional[float] = Field(default=None, ge=0, le=1)
    completeness: Optional[float] = Field(default=None, ge=0, le=1)
    uncertainty: Dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    provider_quality_score: Optional[float] = Field(default=None, ge=0, le=1)
    freshness_seconds: Optional[float] = None
    provider_quality: Dict[str, Any] = Field(default_factory=dict)
    lineage: Tuple[Dict[str, Any], ...] = ()
    reproducibility: Literal["available", "incomplete", "unknown"] = "unknown"
    validation_status: Literal["valid", "invalid", "not_assessed"] = "not_assessed"


class RasterBandStatistics(Contract):
    """Descriptive statistics over explicitly selected raster cells."""

    variable: str = Field(min_length=1)
    source_band: str = Field(min_length=1)
    measurement_kind: Literal["numeric", "categorical"] = "numeric"
    unit: Optional[str] = None
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    selected_pixel_count: int = Field(ge=0)
    valid_pixel_count: int = Field(ge=0)
    minimum: Optional[float] = Field(default=None, allow_inf_nan=False)
    maximum: Optional[float] = Field(default=None, allow_inf_nan=False)
    cell_weighted_mean: Optional[float] = Field(default=None, allow_inf_nan=False)
    population_standard_deviation: Optional[float] = Field(default=None, ge=0)
    geodesic_area_weighted_mean: Optional[float] = Field(default=None, allow_inf_nan=False)
    geodesic_area_weighted_population_standard_deviation: Optional[float] = Field(
        default=None, ge=0
    )
    valid_area_square_metres: Optional[float] = Field(default=None, ge=0)
    category_value_counts: Tuple[Dict[str, Any], ...] = ()

    @model_validator(mode="after")
    def validate_summary_kind(self) -> "RasterBandStatistics":
        if self.valid_pixel_count > self.selected_pixel_count:
            raise ValueError("valid raster cells cannot exceed selected raster cells")
        if self.measurement_kind == "categorical":
            if any(
                value is not None
                for value in (
                    self.minimum,
                    self.maximum,
                    self.cell_weighted_mean,
                    self.population_standard_deviation,
                    self.geodesic_area_weighted_mean,
                    self.geodesic_area_weighted_population_standard_deviation,
                )
            ):
                raise ValueError(
                    "categorical raster data cannot contain numeric moments"
                )
            counts = [record.get("count") for record in self.category_value_counts]
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in counts
            ):
                raise ValueError("categorical counts must be non-negative integers")
            if self.valid_pixel_count and sum(counts) != self.valid_pixel_count:
                raise ValueError(
                    "category counts must account for every valid raster cell"
                )
            fractions = [
                record.get("fraction_of_valid_cells")
                for record in self.category_value_counts
            ]
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in fractions
            ):
                raise ValueError(
                    "categorical fractions must be finite values between zero and one"
                )
            if fractions and not math.isclose(
                sum(fractions), 1.0, rel_tol=1e-9, abs_tol=1e-9
            ):
                raise ValueError(
                    "category fractions must sum to one over valid raster cells"
                )
            area_fractions = [
                record["fraction_of_valid_area"]
                for record in self.category_value_counts
                if "fraction_of_valid_area" in record
            ]
            if area_fractions and (
                len(area_fractions) != len(self.category_value_counts)
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not 0 <= value <= 1
                    for value in area_fractions
                )
                or not math.isclose(
                    sum(area_fractions), 1.0, rel_tol=1e-9, abs_tol=1e-9
                )
            ):
                raise ValueError(
                    "area fractions must account for every valid category"
                )
            category_areas = [
                record.get("area_square_metres")
                for record in self.category_value_counts
                if "area_square_metres" in record
            ]
            if category_areas and (
                len(category_areas) != len(self.category_value_counts)
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                    for value in category_areas
                )
                or (
                    self.valid_area_square_metres is not None
                    and not math.isclose(
                        sum(category_areas),
                        self.valid_area_square_metres,
                        rel_tol=1e-9,
                        abs_tol=1e-6,
                    )
                )
            ):
                raise ValueError(
                    "category areas must account for valid raster area"
                )
        elif self.category_value_counts:
            raise ValueError("numeric raster data cannot contain category frequencies")
        elif self.valid_area_square_metres is not None and self.valid_pixel_count == 0:
            if self.valid_area_square_metres != 0:
                raise ValueError("empty numeric summaries must have zero valid area")
        return self


class RasterAnalysisProduct(Contract):
    """Reproducible raster analysis, kept distinct from acquired measurements."""

    product_id: str = Field(min_length=1)
    operation: Literal["zonal_descriptive"]
    status: Literal[
        "computed",
        "computed_partial",
        "no_matching_bands",
        "no_overlap",
        "no_selected_cells",
        "no_valid_pixels",
    ] = "computed"
    method_version: str = Field(min_length=1)
    source_observation_id: str = Field(min_length=1)
    source_dataset: Optional[DatasetReference] = None
    analysis_geometry: Dict[str, Any]
    geometry_crs: str = Field(min_length=1)
    pixel_selection: Literal["pixel_center", "all_touched"]
    weighting_method: Literal["equal_cell", "geodesic_cell_area"] = "equal_cell"
    missing_variables: Tuple[str, ...] = ()
    statistics: Tuple[RasterBandStatistics, ...] = ()
    assets: Tuple[Dict[str, Any], ...] = ()
    selected_pixel_count: int = Field(ge=0)
    reproducibility: Dict[str, Any] = Field(default_factory=dict)
    uncertainty: Dict[str, Any] = Field(default_factory=dict)
    limitations: Tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_statistics_coverage(self) -> "RasterAnalysisProduct":
        if any(
            item.selected_pixel_count != self.selected_pixel_count
            for item in self.statistics
        ):
            raise ValueError(
                "band statistics must use the product's selected-cell count"
            )
        return self


class QualityQuery(Contract):
    minimum_quality_score: Optional[float] = Field(default=None, ge=0, le=1)
    minimum_completeness: Optional[float] = Field(default=None, ge=0, le=1)
    minimum_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    minimum_provider_quality: Optional[float] = Field(default=None, ge=0, le=1)
    maximum_freshness_seconds: Optional[float] = Field(default=None, ge=0)
    validation_status: Optional[Literal["valid", "invalid", "not_assessed"]] = None


class QualityRecord(Contract):
    observation_id: str = Field(min_length=1)
    assessment: ObservationQuality


class EarthObjectCandidate(Contract):
    """A versioned extractor's declared entity candidate, not a conclusion."""

    identity_namespace: str = Field(min_length=1)
    identity_value: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    declared_by: str = Field(min_length=1)
    mapping_id: str = Field(min_length=1)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class Observation(Contract):
    observation_id: str = Field(default_factory=_new_id, min_length=1)
    source_id: Optional[str] = None
    dataset: Optional[DatasetReference] = None
    observed_at: Optional[datetime] = None
    geometry: Optional[Dict[str, Any]] = None
    bbox: Optional[Tuple[float, ...]] = Field(default=None, min_length=4, max_length=6)
    crs: Optional[str] = None
    temporal_extent: Optional[TemporalExtent] = None
    observation_type: Optional[str] = None
    earth_object_candidate: Optional[EarthObjectCandidate] = None
    measured_variables: Dict[str, Any] = Field(default_factory=dict)
    canonical_measurements: Tuple["CanonicalMeasurement", ...] = ()
    raster_analysis_products: Tuple[RasterAnalysisProduct, ...] = ()
    modalities: Tuple[str, ...] = ()
    provenance: Dict[str, Any] = Field(default_factory=dict)
    uncertainty: Dict[str, Any] = Field(default_factory=dict)
    provider_metadata: Dict[str, Any] = Field(default_factory=dict)
    quality: Dict[str, Any] = Field(default_factory=dict)
    quality_assessment: Optional[ObservationQuality] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    reproducibility: Dict[str, Any] = Field(default_factory=dict)
    properties: Dict[str, Any] = Field(default_factory=dict)
    assets: Dict[str, ObservationAsset] = Field(default_factory=dict)
    source_document: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_bbox_dimensions(self) -> "Observation":
        if self.bbox is not None and len(self.bbox) not in {4, 6}:
            raise ValueError("observation bbox must contain four or six coordinates")
        if any(not value.strip() for value in self.modalities):
            raise ValueError("modalities must not contain empty values")
        if len(self.modalities) != len(set(self.modalities)):
            raise ValueError("modalities must contain unique values")
        return self


class CanonicalMeasurement(Contract):
    """Typed, traceable view of one source measurement.

    Values and units are preserved verbatim. ``semantic_status`` describes
    name resolution only; it does not imply unit conversion or scientific
    comparability.
    """

    canonical_variable: str = Field(min_length=1)
    value: Any = None
    unit: Optional[str] = None
    source_variable: str = Field(min_length=1)
    source_unit: Optional[str] = None
    ontology_uri: Optional[str] = None
    semantic_status: Literal["resolved", "unresolved"] = "unresolved"
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    observation_id: Optional[str] = None


class RasterComponentClassMapping(Contract):
    """Caller-declared meaning of one exact class code in a categorical raster."""

    class_value: int | float
    object_type: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_class_value(self) -> "RasterComponentClassMapping":
        if isinstance(self.class_value, bool) or not math.isfinite(self.class_value):
            raise ValueError("raster class values must be finite numeric codes")
        if not self.object_type.strip():
            raise ValueError("raster class object type must not be empty")
        return self


class RasterComponentExtractionSpec(Contract):
    """Explicit rules for polygonizing declared categorical raster values.

    This contract carries caller-provided class semantics. Polygonization only
    converts matching raster cells to geometry; it does not classify imagery.
    """

    asset_key: str = Field(min_length=1)
    band_index: int = Field(ge=1)
    source_variable: str = Field(min_length=1)
    class_mappings: Tuple[RasterComponentClassMapping, ...] = Field(min_length=1)
    connectivity: Literal[4, 8]
    pixel_selection: Literal["pixel_center", "all_touched"]
    minimum_component_pixels: int = Field(default=1, ge=1)
    maximum_components: int = Field(default=10_000, ge=1, le=100_000)

    @model_validator(mode="after")
    def validate_mapping(self) -> "RasterComponentExtractionSpec":
        if not self.asset_key.strip() or not self.source_variable.strip():
            raise ValueError("raster asset and source variable names must not be empty")
        if len({item.class_value for item in self.class_mappings}) != len(
            self.class_mappings
        ):
            raise ValueError("raster class values must be unique per extraction spec")
        return self


class EarthQuery(Contract):
    bbox: Optional[Tuple[float, ...]] = Field(default=None, min_length=4, max_length=6)
    point: Optional[Tuple[float, float]] = None
    geometry: Optional[Dict[str, Any]] = None
    temporal_start: Optional[datetime] = None
    temporal_end: Optional[datetime] = None
    crs: str = "OGC:CRS84"
    spatial_resolution: Optional[float] = Field(default=None, gt=0)
    resolution_unit: Optional[str] = None
    requested_dataset_ids: Tuple[str, ...] = ()
    requested_variables: Tuple[str, ...] = ()
    requested_modalities: Tuple[str, ...] = ()
    required_capabilities: Tuple[str, ...] = ()
    region: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    asset_preferences: Tuple[str, ...] = ()
    asset_sampling: Optional[Literal["point"]] = None
    raster_analysis: Optional[Literal["zonal_descriptive"]] = None
    raster_pixel_selection: Optional[Literal["pixel_center", "all_touched"]] = None
    raster_weighting: Optional[Literal["equal_cell", "geodesic_cell_area"]] = None
    raster_semantics: Dict[str, Literal["numeric", "categorical"]] = Field(
        default_factory=dict
    )
    raster_component_extraction: Tuple[RasterComponentExtractionSpec, ...] = ()

    @model_validator(mode="after")
    def validate_query(self) -> "EarthQuery":
        spatial_fields = sum(
            item is not None for item in (self.bbox, self.point, self.geometry)
        )
        if spatial_fields > 1:
            raise ValueError("query must specify only one of bbox, point, or geometry")
        if self.bbox is not None:
            if len(self.bbox) not in {4, 6}:
                raise ValueError("bbox must contain four or six coordinates")
            if not all(math.isfinite(value) for value in self.bbox):
                raise ValueError("bbox coordinates must be finite")
            min_x, min_y = self.bbox[0:2]
            max_x, max_y = self.bbox[2:4] if len(self.bbox) == 4 else self.bbox[3:5]
            if _is_geographic_crs(self.crs):
                if not -180 <= min_x <= 180 or not -180 <= max_x <= 180:
                    raise ValueError(
                        "bbox longitude coordinates must be between -180 and 180"
                    )
                if not -90 <= min_y <= 90 or not -90 <= max_y <= 90:
                    raise ValueError(
                        "bbox latitude coordinates must be between -90 and 90"
                    )
                if min_y > max_y:
                    raise ValueError(
                        "bbox south latitude must not exceed north latitude"
                    )
            elif min_x > max_x or min_y > max_y:
                raise ValueError(
                    "projected bbox minimum coordinates must not exceed maximum"
                )
            if len(self.bbox) == 6 and self.bbox[2] > self.bbox[5]:
                raise ValueError(
                    "bbox minimum elevation must not exceed maximum elevation"
                )
        if self.point is not None:
            longitude, latitude = self.point
            if not math.isfinite(longitude) or not math.isfinite(latitude):
                raise ValueError("point coordinates must be finite")
            if _is_geographic_crs(self.crs) and (
                not -180 <= longitude <= 180 or not -90 <= latitude <= 90
            ):
                raise ValueError(
                    "point must use longitude/latitude within Earth bounds"
                )
        if self.geometry is not None:
            _validate_geojson_geometry(self.geometry, self.crs)
        if self.temporal_start is not None and self.temporal_start.tzinfo is None:
            raise ValueError("temporal_start must include a timezone")
        if self.temporal_end is not None and self.temporal_end.tzinfo is None:
            raise ValueError("temporal_end must include a timezone")
        if (
            self.temporal_start is not None
            and self.temporal_end is not None
            and self.temporal_start > self.temporal_end
        ):
            raise ValueError("temporal_start must not be after temporal_end")
        for name, values in (
            ("requested_dataset_ids", self.requested_dataset_ids),
            ("requested_variables", self.requested_variables),
            ("requested_modalities", self.requested_modalities),
            ("required_capabilities", self.required_capabilities),
            ("asset_preferences", self.asset_preferences),
        ):
            if any(not value.strip() for value in values):
                raise ValueError(f"{name} must not contain empty values")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique values")
        if self.region is not None and not self.region.strip():
            raise ValueError("region must not be empty")
        if self.resolution_unit is not None and not self.resolution_unit.strip():
            raise ValueError("resolution_unit must not be empty")
        if self.resolution_unit is not None and self.spatial_resolution is None:
            raise ValueError("resolution_unit requires spatial_resolution")
        if self.asset_sampling is not None:
            point_geometry = (
                self.geometry is not None and self.geometry.get("type") == "Point"
            )
            if self.point is None and not point_geometry:
                raise ValueError("point asset sampling requires a point query")
            if not self.requested_variables:
                raise ValueError("point asset sampling requires requested variables")
        if self.raster_analysis is not None:
            if self.geometry is None or self.geometry.get("type") not in {
                "Polygon",
                "MultiPolygon",
            }:
                raise ValueError(
                    "zonal raster analysis requires Polygon or MultiPolygon geometry"
                )
            if not self.requested_variables:
                raise ValueError("zonal raster analysis requires requested variables")
            if self.raster_pixel_selection is None:
                raise ValueError(
                    "zonal raster analysis requires explicit pixel selection"
                )
            if self.asset_sampling is not None:
                raise ValueError(
                    "point sampling and zonal raster analysis cannot be combined"
                )
        elif self.raster_pixel_selection is not None:
            raise ValueError("raster_pixel_selection requires raster_analysis")
        if self.raster_analysis is None and self.raster_weighting is not None:
            raise ValueError("raster_weighting requires raster_analysis")
        if self.raster_analysis is None and self.raster_semantics:
            raise ValueError("raster_semantics requires raster_analysis")
        if self.raster_semantics and not set(self.raster_semantics).issubset(
            set(self.requested_variables)
        ):
            raise ValueError("raster_semantics keys must be requested variables")
        if self.raster_component_extraction:
            has_area_of_interest = self.bbox is not None or (
                self.geometry is not None
                and self.geometry.get("type") in {"Polygon", "MultiPolygon"}
            )
            if not has_area_of_interest:
                raise ValueError(
                    "raster component extraction requires a bbox or polygon AOI"
                )
            extraction_keys = tuple(
                (item.asset_key, item.band_index) for item in self.raster_component_extraction
            )
            if len(set(extraction_keys)) != len(extraction_keys):
                raise ValueError(
                    "raster component extraction must declare each asset band once"
                )
        if not self.crs.strip():
            raise ValueError("crs must not be empty")
        return self


class ObservationSearchResult(Contract):
    observations: Tuple[Observation, ...] = ()
    matched: Optional[int] = Field(default=None, ge=0)
    context: Dict[str, Any] = Field(default_factory=dict)
    links: Tuple[Dict[str, Any], ...] = ()
    source_document: Dict[str, Any] = Field(default_factory=dict)


class ObservationGroup(Contract):
    group_id: str = Field(min_length=1)
    observation_ids: Tuple[str, ...] = Field(min_length=1)
    primary_observation_id: str = Field(min_length=1)
    conflicts: Tuple[Dict[str, Any], ...] = ()
    temporal_overlap: Optional[TemporalExtent] = None
    spatial_overlap: Optional[Dict[str, Any]] = None
    provider_weights: Dict[str, float] = Field(default_factory=dict)
    uncertainty_records: Dict[str, Any] = Field(default_factory=dict)
    provenance_tree: Tuple[Dict[str, Any], ...] = ()


class AssetQuery(Contract):
    dataset_id: Optional[str] = None
    roles: Tuple[str, ...] = ()
    media_types: Tuple[str, ...] = ()
    required_capabilities: Tuple[str, ...] = ()
    text: Optional[str] = None


class AssetSearchResult(Contract):
    assets: Tuple[ObservationAsset, ...] = ()
    matched: int = Field(ge=0)
    source_ids: Tuple[str, ...] = ()


class PerceptionFailure(Contract):
    connector_id: str = Field(min_length=1)
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class PerceptionProcessingFailure(Contract):
    """Failure after acquisition while processing one canonical observation."""

    observation_id: str = Field(min_length=1)
    stage: Literal["raster_asset_sampling", "raster_analysis"]
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class PerceptionPlan(Contract):
    """Transparent coverage plan across sensing modalities and implementations."""

    requested_modalities: Tuple[str, ...] = ()
    selected_modalities: Tuple[str, ...] = ()
    unavailable_modalities: Tuple[str, ...] = ()
    requested_variables: Tuple[str, ...] = ()
    selected_variables: Tuple[str, ...] = ()
    unavailable_variables: Tuple[str, ...] = ()
    implementation_ids: Tuple[str, ...] = ()
    dataset_ids: Tuple[str, ...] = ()
    capability_matrix_revision: Optional[str] = None
    capability_snapshot: Optional[EarthCapabilitySnapshot] = None

    @model_validator(mode="after")
    def validate_capability_snapshot_revision(self) -> "PerceptionPlan":
        if (
            self.capability_snapshot is not None
            and self.capability_matrix_revision != self.capability_snapshot.revision
        ):
            raise ValueError("capability snapshot revision does not match the plan")
        return self


class ObservationStackMember(Contract):
    """One unaggregated measurement in an exactly aligned observation stack."""

    observation_id: str = Field(min_length=1)
    measurement_observation_id: Optional[str] = None
    source_id: Optional[str] = None
    dataset: Optional[DatasetReference] = None
    observed_at: datetime
    value: int | float
    unit: str = Field(min_length=1)
    source_variable: str = Field(min_length=1)
    uncertainty: Dict[str, Any] = Field(default_factory=dict)
    source_measurement_metadata: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_member(self) -> "ObservationStackMember":
        if self.observed_at.tzinfo is None:
            raise ValueError("observation stack member time must include a timezone")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("observation stack member value must be numeric")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("observation stack member value must be finite")
        return self


class ObservationStack(Contract):
    """A reproducible sequence with exactly matching known spatial support."""

    stack_id: str = Field(min_length=1)
    variable_key: str = Field(min_length=1)
    canonical_variable: Optional[str] = None
    unit: str = Field(min_length=1)
    spatial_support_geometry: Dict[str, Any]
    spatial_support_crs: str = Field(min_length=1)
    spatial_alignment: Literal["exact_pixel_support", "exact_point_support"]
    temporal_alignment: Literal["source_acquisition_time"]
    members: Tuple[ObservationStackMember, ...] = Field(min_length=2)
    reproducibility: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_stack(self) -> "ObservationStack":
        times = tuple(member.observed_at for member in self.members)
        if times != tuple(sorted(times)):
            raise ValueError("observation stack members must be time ordered")
        if len(times) != len(set(times)):
            raise ValueError("observation stack member times must be unique")
        if any(member.unit != self.unit for member in self.members):
            raise ValueError("observation stack member units must match exactly")
        if len({member.observation_id for member in self.members}) != len(self.members):
            raise ValueError("observation stack member IDs must be unique")
        geometry_key, crs_key = (
            ("pixel_support_geometry", "pixel_support_crs")
            if self.spatial_alignment == "exact_pixel_support"
            else ("observation_support_geometry", "observation_support_crs")
        )
        for member in self.members:
            metadata = member.source_measurement_metadata
            if (
                metadata.get(geometry_key) != self.spatial_support_geometry
                or metadata.get(crs_key) != self.spatial_support_crs
            ):
                raise ValueError(
                    "observation stack support must match every source measurement exactly"
                )
        return self


class ObservationAlignmentIssue(Contract):
    """A recorded reason an observation could not join an exact-support stack."""

    observation_id: str = Field(min_length=1)
    canonical_variable: Optional[str] = None
    code: Literal[
        "missing_time",
        "missing_measurement",
        "unresolved_variable",
        "non_numeric_value",
        "missing_unit",
        "unknown_spatial_support",
        "support_not_shared",
        "unit_mismatch",
        "insufficient_members",
        "duplicate_time",
    ]
    message: str = Field(min_length=1)


class ObservationStackBuild(Contract):
    """Stacks and explicit blockers produced from a fixed observation set."""

    stacks: Tuple[ObservationStack, ...] = ()
    issues: Tuple[ObservationAlignmentIssue, ...] = ()
    builder_version: str = Field(min_length=1)


class TemporalDifferenceDiagnostic(Contract):
    """Descriptive difference between consecutive exactly aligned samples.

    This is arithmetic over declared measurements, not a trend test or a
    scientific conclusion. Source members are embedded so the record remains
    auditable when retrieved independently of its parent perception result.
    """

    diagnostic_id: str = Field(min_length=1)
    stack_id: str = Field(min_length=1)
    variable_key: str = Field(min_length=1)
    canonical_variable: Optional[str] = None
    unit: str = Field(min_length=1)
    spatial_support_geometry: Dict[str, Any]
    spatial_support_crs: str = Field(min_length=1)
    spatial_alignment: Literal["exact_pixel_support", "exact_point_support"] = "exact_pixel_support"
    earlier: ObservationStackMember
    later: ObservationStackMember
    elapsed_seconds: float = Field(gt=0)
    difference_value: int | float
    operation: Literal["later_minus_earlier"] = "later_minus_earlier"
    interpretation_status: Literal["descriptive_only"] = "descriptive_only"
    uncertainty_status: Literal["not_propagated"] = "not_propagated"
    method_id: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    reproducibility: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_difference(self) -> "TemporalDifferenceDiagnostic":
        expected_seconds = (self.later.observed_at - self.earlier.observed_at).total_seconds()
        if not math.isfinite(self.elapsed_seconds) or expected_seconds != self.elapsed_seconds:
            raise ValueError("elapsed_seconds must match the source observation times")
        if self.earlier.unit != self.unit or self.later.unit != self.unit:
            raise ValueError("difference members must use the declared common unit")
        if self.later.observed_at <= self.earlier.observed_at:
            raise ValueError("difference members must be in strictly increasing time order")
        if self.difference_value != self.later.value - self.earlier.value:
            raise ValueError("difference_value must equal later minus earlier")
        if isinstance(self.difference_value, float) and not math.isfinite(self.difference_value):
            raise ValueError("difference_value must be finite")
        for member in (self.earlier, self.later):
            metadata = member.source_measurement_metadata
            geometry_key, crs_key = (
                ("pixel_support_geometry", "pixel_support_crs")
                if self.spatial_alignment == "exact_pixel_support"
                else ("observation_support_geometry", "observation_support_crs")
            )
            if (
                metadata.get(geometry_key) != self.spatial_support_geometry
                or metadata.get(crs_key) != self.spatial_support_crs
            ):
                raise ValueError("difference support must match both source measurements exactly")
        return self


class TemporalDifferenceIssue(Contract):
    """A pair that could not produce a finite descriptive difference."""

    stack_id: str = Field(min_length=1)
    earlier_observation_id: str = Field(min_length=1)
    later_observation_id: str = Field(min_length=1)
    code: Literal[
        "source_dataset_unknown",
        "dataset_mismatch",
        "source_variable_mismatch",
        "non_finite_difference",
    ]
    message: str = Field(min_length=1)


class PerceptionResult(Contract):
    query_fingerprint: str = Field(min_length=1)
    observations: Tuple[Observation, ...] = ()
    connector_ids: Tuple[str, ...] = ()
    connector_versions: Tuple[str, ...] = ()
    failures: Tuple[PerceptionFailure, ...] = ()
    processing_failures: Tuple[PerceptionProcessingFailure, ...] = ()
    duplicate_count: int = Field(default=0, ge=0)
    observation_groups: Tuple[ObservationGroup, ...] = ()
    observation_stacks: Tuple[ObservationStack, ...] = ()
    temporal_differences: Tuple[TemporalDifferenceDiagnostic, ...] = ()
    temporal_difference_issues: Tuple[TemporalDifferenceIssue, ...] = ()
    alignment_issues: Tuple[ObservationAlignmentIssue, ...] = ()
    conflicts: Tuple[Dict[str, Any], ...] = ()
    observation_graph: Optional[ObservationGraph] = None
    plan: Optional[PerceptionPlan] = None
    cache_hit: bool = False
    status: Literal["complete", "partial", "failed"] = "complete"


class Evidence(Contract):
    evidence_id: str = Field(default_factory=_new_id, min_length=1)
    investigation_id: str = Field(min_length=1)
    observation_id: Optional[str] = None
    dataset: Optional[DatasetReference] = None
    claim: str = Field(min_length=1)
    artifact_uri: Optional[str] = None
    checksum: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class EarthObjectPropertyAssertion(Contract):
    """An asserted object property copied from cited source records."""

    property_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value: Any = None
    unit: Optional[str] = None
    source_variable: Optional[str] = None
    ontology_uri: Optional[str] = None
    observation_ids: Tuple[str, ...] = ()
    evidence_ids: Tuple[str, ...] = ()
    uncertainty: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class EarthObjectSourceAttribute(Contract):
    """An unmapped source attribute retained without canonical interpretation."""

    attribute_id: str = Field(min_length=1)
    source_observation_id: str = Field(min_length=1)
    source_dataset: Optional[DatasetReference] = None
    source_key: str = Field(min_length=1)
    value: Any = None
    extraction_method_id: Optional[str] = None
    uncertainty: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class EarthObjectRelationship(Contract):
    """A typed relationship whose meaning is supported by explicit evidence."""

    relationship_id: str = Field(min_length=1)
    source_object_id: str = Field(min_length=1)
    target_object_id: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    evidence_ids: Tuple[str, ...] = ()
    observation_ids: Tuple[str, ...] = ()
    provenance: Dict[str, Any] = Field(default_factory=dict)
    asserted_by: str = Field(min_length=1)
    asserted_at: datetime = Field(default_factory=utc_now)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_traceable_basis(self) -> "EarthObjectRelationship":
        if not self.evidence_ids and not self.observation_ids:
            raise ValueError("Earth Object relationships require evidence or source observations")
        if self.source_object_id == self.target_object_id:
            raise ValueError("Earth Object relationship endpoints must differ")
        return self


class EarthObjectGraph(Contract):
    """A validated object snapshot and its evidence-backed relationships."""

    objects: Tuple["EarthObject", ...] = ()
    relationships: Tuple[EarthObjectRelationship, ...] = ()
    graph_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_endpoints(self) -> "EarthObjectGraph":
        object_ids = {item.object_id for item in self.objects}
        if len(object_ids) != len(self.objects):
            raise ValueError("Earth Object graph contains duplicate object IDs")
        for edge in self.relationships:
            if edge.source_object_id not in object_ids or edge.target_object_id not in object_ids:
                raise ValueError("Earth Object relationship endpoint is absent from graph")
        return self


class EarthObject(Contract):
    object_id: str = Field(default_factory=_new_id, min_length=1)
    object_type: str = Field(min_length=1)
    schema_version: str = "1.0"
    revision: int = Field(default=1, ge=1)
    content_sha256: Optional[str] = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    stable_identity: Optional[str] = None
    investigation_id: Optional[str] = None
    investigation_ids: Tuple[str, ...] = ()
    geometry: Optional[Dict[str, Any]] = None
    crs: Optional[str] = None
    temporal_validity: Optional[TemporalExtent] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    property_assertions: Tuple[EarthObjectPropertyAssertion, ...] = ()
    source_attributes: Tuple[EarthObjectSourceAttribute, ...] = ()
    measurements: Tuple["CanonicalMeasurement", ...] = ()
    uncertainty: Dict[str, Any] = Field(default_factory=dict)
    source_observation_ids: Tuple[str, ...] = ()
    evidence_ids: Tuple[str, ...] = ()
    supporting_evidence_ids: Tuple[str, ...] = ()
    conflicting_evidence_ids: Tuple[str, ...] = ()
    unresolved_evidence_ids: Tuple[str, ...] = ()
    relationships: Tuple[EarthObjectRelationship, ...] = ()
    lifecycle: Literal["observed", "active", "inactive", "superseded", "retracted", "unknown"] = "unknown"
    supersedes_object_id: Optional[str] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)
    reproducibility: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_evidence_references(self) -> "EarthObject":
        if not self.source_observation_ids:
            raise ValueError("Earth Objects require at least one source observation")
        classified = set(self.supporting_evidence_ids) | set(self.conflicting_evidence_ids) | set(self.unresolved_evidence_ids)
        if not classified.issubset(set(self.evidence_ids)):
            raise ValueError("Earth Object evidence_ids must include all classified evidence")
        if (
            set(self.supporting_evidence_ids) & set(self.conflicting_evidence_ids)
            or set(self.supporting_evidence_ids) & set(self.unresolved_evidence_ids)
            or set(self.conflicting_evidence_ids) & set(self.unresolved_evidence_ids)
        ):
            raise ValueError("Earth Object evidence classifications must be mutually exclusive")
        known_observations = set(self.source_observation_ids)
        for measurement in self.measurements:
            if measurement.observation_id is not None and measurement.observation_id not in known_observations:
                raise ValueError("Earth Object measurement references an unlisted observation")
        for assertion in self.property_assertions:
            if not set(assertion.observation_ids).issubset(known_observations):
                raise ValueError("Earth Object property assertion references an unlisted observation")
        if any(
            item.source_observation_id not in known_observations
            for item in self.source_attributes
        ):
            raise ValueError("Earth Object source attribute references an unlisted observation")
        if len({item.attribute_id for item in self.source_attributes}) != len(
            self.source_attributes
        ):
            raise ValueError("Earth Object source attribute IDs must be unique")
        return self


class ToolResult(Contract):
    """Tool output independent of the existing query API's ToolResult schema."""

    result_id: str = Field(default_factory=_new_id, min_length=1)
    tool_id: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    status: TaskStatus
    output: Any = None
    evidence_ids: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    started_at: Optional[datetime] = None
    finished_at: datetime = Field(default_factory=utc_now)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class ModelResult(Contract):
    model_id: str = Field(min_length=1)
    model_version: Optional[str] = None
    output: Any = None
    provider: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    latency_seconds: Optional[float] = Field(default=None, ge=0)
    usage: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class ModelMetadata(Contract):
    model_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: Optional[str] = None
    provider: str = Field(min_length=1)
    capabilities: Tuple[str, ...] = ()
    input_modalities: Tuple[str, ...] = ()
    output_modalities: Tuple[str, ...] = ()
    execution_location: str = "local"
    configuration_schema: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModelRequest(Contract):
    inputs: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None


class ReasoningStep(Contract):
    step_id: str = Field(default_factory=_new_id, min_length=1)
    module_id: str = Field(min_length=1)
    input_evidence_ids: Tuple[str, ...] = ()
    output_evidence_ids: Tuple[str, ...] = ()
    explanation: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class Task(Contract):
    """Executable workflow node with explicit dependency failure policy."""

    task_id: str = Field(default_factory=_new_id, min_length=1)
    handler: str = Field(min_length=1)
    description: str = ""
    depends_on: Tuple[str, ...] = ()
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: Optional[float] = Field(default=None, gt=0)
    max_attempts: int = Field(default=1, ge=1)
    retry_delay_seconds: float = Field(default=0, ge=0)
    retry_safe: bool = False
    # Evidence aggregation stages may run with successful branches when another
    # source failed. Cancellation still blocks downstream execution.
    accept_partial_dependencies: bool = False

    @model_validator(mode="after")
    def dependencies_are_unique(self) -> "Task":
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("task dependencies must be unique")
        if self.task_id in self.depends_on:
            raise ValueError("a task cannot depend on itself")
        if self.max_attempts > 1 and not self.retry_safe:
            raise ValueError("multiple attempts require retry_safe=True")
        return self


class ToolMetadata(Contract):
    tool_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    capabilities: Tuple[str, ...] = ()
    stateless: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(Contract):
    plan_id: str = Field(default_factory=_new_id, min_length=1)
    mission_id: Optional[str] = None
    investigation_id: Optional[str] = None
    tasks: Tuple[Task, ...]
    max_concurrency: Optional[int] = Field(default=None, gt=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def tasks_form_a_valid_dag(self) -> "ExecutionPlan":
        by_id = {task.task_id: task for task in self.tasks}
        if len(by_id) != len(self.tasks):
            raise ValueError("task identifiers must be unique within an execution plan")
        for task in self.tasks:
            missing = set(task.depends_on).difference(by_id)
            if missing:
                raise ValueError(
                    f"task {task.task_id!r} depends on unknown tasks: {sorted(missing)}"
                )

        remaining = {task_id: set(task.depends_on) for task_id, task in by_id.items()}
        completed: set[str] = set()
        while remaining:
            ready = {
                task_id for task_id, deps in remaining.items() if deps <= completed
            }
            if not ready:
                raise ValueError("execution plan contains a dependency cycle")
            completed.update(ready)
            for task_id in ready:
                del remaining[task_id]
        return self


class TaskExecution(Contract):
    task_id: str = Field(min_length=1)
    handler: Optional[str] = None
    description: str = ""
    depends_on: Tuple[str, ...] = ()
    parameters: Dict[str, Any] = Field(default_factory=dict)
    execution_policy: Dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus
    attempts: int = Field(ge=0)
    output: Any = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: datetime = Field(default_factory=utc_now)
    duration_seconds: float = Field(ge=0)


class ExecutionResult(Contract):
    plan_id: str = Field(min_length=1)
    status: ExecutionStatus
    tasks: Tuple[TaskExecution, ...]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime = Field(default_factory=utc_now)
    trace_id: str = Field(default_factory=_new_id, min_length=1)
    warnings: Tuple[str, ...] = ()


class ExecutionProgress(Contract):
    trace_id: str = Field(min_length=1)
    mission_id: Optional[str] = None
    investigation_id: Optional[str] = None
    task_id: str = Field(min_length=1)
    status: TaskStatus
    completed_tasks: int = Field(ge=0)
    total_tasks: int = Field(ge=0)
    timestamp: datetime = Field(default_factory=utc_now)


class ConnectorMetadata(Contract):
    connector_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    capabilities: Tuple[str, ...] = ()
    modalities: Tuple[str, ...] = ()
    authentication_schemes: Tuple[str, ...] = ()
    authentication_required: Optional[bool] = None
    supports_async: bool = True
    supports_streaming: Optional[bool] = None
    datasets: Tuple[DatasetReference, ...] = ()
    configuration_schema: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    health: Literal["unknown", "healthy", "degraded", "unhealthy"] = "unknown"
    available: bool = True
    supported_regions: Tuple[str, ...] = ()
    supported_spatial_types: Tuple[str, ...] = ()
    supports_temporal_query: bool = False
    supported_query_fields: Tuple[str, ...] = ()
    temporal_start: Optional[datetime] = None
    temporal_end: Optional[datetime] = None
    supported_variables: Tuple[str, ...] = ()
    provider_version: Optional[str] = None
    provider_metadata: Dict[str, Any] = Field(default_factory=dict)
    fallback_for: Tuple[str, ...] = ()
    dependencies: Tuple[str, ...] = ()
    quota: Dict[str, Any] = Field(default_factory=dict)
    authentication_metadata: Dict[str, Any] = Field(default_factory=dict)
    documentation_url: Optional[str] = None
    license: Optional[str] = None

    @model_validator(mode="after")
    def validate_capability_metadata(self) -> "ConnectorMetadata":
        if self.temporal_start is not None and self.temporal_start.tzinfo is None:
            raise ValueError("connector temporal_start must include a timezone")
        if self.temporal_end is not None and self.temporal_end.tzinfo is None:
            raise ValueError("connector temporal_end must include a timezone")
        if (
            self.temporal_start is not None
            and self.temporal_end is not None
            and self.temporal_start > self.temporal_end
        ):
            raise ValueError("connector temporal_start must not be after temporal_end")
        if any(not value.strip() for value in self.supported_regions):
            raise ValueError("supported_regions must not contain empty values")
        if any(not value.strip() for value in self.supported_variables):
            raise ValueError("supported_variables must not contain empty values")
        if any(not value.strip() for value in self.modalities):
            raise ValueError("modalities must not contain empty values")
        if len(self.modalities) != len(set(self.modalities)):
            raise ValueError("modalities must contain unique values")
        if any(not value.strip() for value in self.supported_spatial_types):
            raise ValueError("supported_spatial_types must not contain empty values")
        if any(not value.strip() for value in self.supported_query_fields):
            raise ValueError("supported_query_fields must not contain empty values")
        if any(not value.strip() for value in self.fallback_for):
            raise ValueError("fallback_for must not contain empty values")
        if any(not value.strip() for value in self.dependencies):
            raise ValueError("dependencies must not contain empty values")
        return self


class ConnectorManifest(Contract):
    manifest_version: str = "1"
    metadata: ConnectorMetadata
    dependencies: Tuple[str, ...] = ()
    authentication_schemes: Tuple[str, ...] = ()
    configuration_schema: Dict[str, Any] = Field(default_factory=dict)
    quota: Dict[str, Any] = Field(default_factory=dict)
    lifecycle_hooks: Tuple[str, ...] = ()
    metadata_extensions: Dict[str, Any] = Field(default_factory=dict)


class ConnectorDiagnostic(Contract):
    connector_id: str = Field(min_length=1)
    state: Literal["stopped", "starting", "running", "degraded", "failed"] = "stopped"
    health: Literal["unknown", "healthy", "degraded", "unhealthy"] = "unknown"
    calls: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_error_type: Optional[str] = None
    last_error: Optional[str] = None
    last_duration_seconds: Optional[float] = Field(default=None, ge=0)
    average_duration_seconds: Optional[float] = Field(default=None, ge=0)
    availability_ratio: Optional[float] = Field(default=None, ge=0, le=1)
    health_probe_count: int = Field(default=0, ge=0)
    last_health_probe_at: Optional[datetime] = None
    last_health_probe_duration_seconds: Optional[float] = Field(default=None, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


ObservationRelationshipType = Literal[
    "derived_from",
    "overlaps",
    "conflicts_with",
    "supersedes",
    "corroborates",
    "spatial_neighbor",
    "temporal_neighbor",
    "same_phenomenon",
]


class ObservationRelationship(Contract):
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation: ObservationRelationshipType
    evidence: Dict[str, Any] = Field(default_factory=dict)


class ObservationGraph(Contract):
    observations: Tuple[Observation, ...] = ()
    relationships: Tuple[ObservationRelationship, ...] = ()


class ConnectorAcquisition(Contract):
    connector_id: str = Field(min_length=1)
    dataset: DatasetReference
    artifact_uri: str = Field(min_length=1)
    acquired_at: datetime = Field(default_factory=utc_now)
    checksum: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Investigation(Contract):
    investigation_id: str = Field(default_factory=_new_id, min_length=1)
    mission_id: str = Field(min_length=1)
    investigation_plan_id: Optional[str] = None
    investigation_design_id: Optional[str] = None
    status: InvestigationStatus = InvestigationStatus.PENDING
    tasks: Tuple[Task, ...] = ()
    evidence_ids: Tuple[str, ...] = ()
    result_ids: Tuple[str, ...] = ()
    report: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
