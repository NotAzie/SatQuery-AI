"""Versionable data contracts shared by platform subsystems."""

from __future__ import annotations

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
    """A source-adapter declaration of an entity candidate, not a conclusion."""

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
            geometry_type = self.geometry.get("type")
            if not isinstance(geometry_type, str) or geometry_type not in {
                "Point",
                "MultiPoint",
                "LineString",
                "MultiLineString",
                "Polygon",
                "MultiPolygon",
                "GeometryCollection",
            }:
                raise ValueError("geometry must contain a GeoJSON geometry type")
            coordinate_field = (
                "geometries" if geometry_type == "GeometryCollection" else "coordinates"
            )
            if not isinstance(self.geometry.get(coordinate_field), list):
                raise ValueError(
                    f"geometry {geometry_type} must contain {coordinate_field}"
                )
            if geometry_type == "Point":
                coordinates = self.geometry[coordinate_field]
                if len(coordinates) < 2 or any(
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    for value in coordinates[:2]
                ):
                    raise ValueError(
                        "GeoJSON Point requires finite numeric coordinates"
                    )
                x, y = coordinates[:2]
                if _is_geographic_crs(self.crs) and (
                    not -180 <= x <= 180 or not -90 <= y <= 90
                ):
                    raise ValueError(
                        "GeoJSON Point must use longitude/latitude within Earth bounds"
                    )
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
    spatial_alignment: Literal["exact_pixel_support"]
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
            if (
                metadata.get("pixel_support_geometry") != self.spatial_support_geometry
                or metadata.get("pixel_support_crs") != self.spatial_support_crs
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
