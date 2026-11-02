"""Serializable Earth workspace contracts shared by sessions and Earth presentation modules."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from earth_platform.shared.geo import BoundingBox, GeoJSONGeometry, LngLat, TimeRange


class CameraState(BaseModel):
    position: LngLat
    height_m: float
    heading_deg: float = 0
    pitch_deg: float = -90
    roll_deg: float = 0
    view_rect: BoundingBox | None = None


class LayerState(BaseModel):
    layer_id: str
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0, le=1)


class EarthViewport(BaseModel):
    width_px: int = Field(gt=0, le=16384)
    height_px: int = Field(gt=0, le=16384)
    pixel_ratio: float = Field(default=1.0, ge=0.1, le=8, allow_inf_nan=False)


class EarthTimelinePlayback(BaseModel):
    playing: bool = False
    speed: float = Field(default=1.0, gt=0, le=10000, allow_inf_nan=False)


class EarthSelection(BaseModel):
    entity_id: str
    position: LngLat | None = None
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class EarthDrawing(BaseModel):
    id: str
    name: str
    kind: Literal["point", "line", "polygon", "rectangle", "circle"]
    geometry: GeoJSONGeometry


class EarthImageryRef(BaseModel):
    asset_id: str = Field(min_length=1, max_length=128)
    source: Literal["capture", "attachment"]
    attached: bool = False
    captured_at: datetime | None = None
    region: BoundingBox | None = None
    camera: CameraState | None = None
    mime_type: Literal["image/png", "image/jpeg", "image/webp", "image/tiff"] | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class EarthOverlayFeature(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    geometry: GeoJSONGeometry
    properties: dict[str, object] = Field(default_factory=dict)


class EarthOverlayOmission(BaseModel):
    object_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=512)


class EarthOverlay(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=256)
    investigation_id: str | None = Field(default=None, min_length=1, max_length=128)
    features: list[EarthOverlayFeature] = Field(default_factory=list, max_length=4096)
    omitted_objects: list[EarthOverlayOmission] = Field(default_factory=list, max_length=4096)
    geometry_policy: str | None = Field(default=None, max_length=512)


class EarthSecondaryView(BaseModel):
    camera: CameraState
    viewport: EarthViewport | None = None
    layers: list[LayerState] = Field(default_factory=list, max_length=64)
    overlays: list[EarthOverlay] = Field(default_factory=list, max_length=32)
    selected_evidence_ids: list[str] = Field(default_factory=list, max_length=64)


class EarthInvestigationState(BaseModel):
    known_ids: list[str] = Field(default_factory=list, max_length=64)
    visible_ids: list[str] = Field(default_factory=list, max_length=64)


class EarthCameraHistory(BaseModel):
    past: list[CameraState] = Field(default_factory=list, max_length=100)
    present: CameraState | None = None
    future: list[CameraState] = Field(default_factory=list, max_length=100)


class EarthBookmarkRef(BaseModel):
    id: str
    name: str
    camera: CameraState
    time: TimeRange | None = None
    instant: datetime | None = None


class EarthSplitView(BaseModel):
    enabled: bool = False
    sync_cameras: bool = False


class EarthMeasurement(BaseModel):
    kind: Literal["distance", "area", "coordinates", "elevation"]
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: Literal["m", "km", "m2", "km2", "degrees", "m elevation"]
    position: LngLat


class PixelRegion(BaseModel):
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class EarthCaptureMetadata(BaseModel):
    id: str
    asset_id: str
    captured_at: datetime
    source: Literal["viewport", "region"]
    camera: CameraState
    region: BoundingBox | None = None
    pixel_region: PixelRegion | None = None
    viewport_width_px: int | None = Field(default=None, gt=0)
    viewport_height_px: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check_pixel_crop(self) -> "EarthCaptureMetadata":
        if (self.viewport_width_px is None) != (self.viewport_height_px is None):
            raise ValueError("viewport dimensions must be provided together")
        if self.pixel_region is not None:
            if self.viewport_width_px is None or self.viewport_height_px is None:
                raise ValueError("pixel crops require the source viewport dimensions")
            if (
                self.pixel_region.left + self.pixel_region.width > self.viewport_width_px
                or self.pixel_region.top + self.pixel_region.height > self.viewport_height_px
            ):
                raise ValueError("pixel crop must fit within the captured viewport")
        return self


class EarthContext(BaseModel):
    camera: CameraState
    viewport: EarthViewport | None = None
    layers: list[LayerState] = Field(default_factory=list, max_length=64)
    time: TimeRange | None = None
    instant: datetime | None = None
    timeline_playback: EarthTimelinePlayback = Field(default_factory=EarthTimelinePlayback)
    selection: EarthSelection | None = None
    drawings: list[EarthDrawing] = Field(default_factory=list, max_length=32)
    captures: list[EarthCaptureMetadata] = Field(default_factory=list, max_length=128)
    imagery: list[EarthImageryRef] = Field(default_factory=list, max_length=128)
    overlays: list[EarthOverlay] = Field(default_factory=list, max_length=32)
    secondary_view: EarthSecondaryView | None = None
    investigations: EarthInvestigationState = Field(default_factory=EarthInvestigationState)
    selected_evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    bookmarks: list[EarthBookmarkRef] = Field(default_factory=list, max_length=32)
    camera_history: EarthCameraHistory = Field(default_factory=EarthCameraHistory)
    split_view: EarthSplitView = Field(default_factory=EarthSplitView)
    measurement: EarthMeasurement | None = None


class EarthBookmark(BaseModel):
    id: str
    name: str
    context: EarthContext
    created_at: datetime
    updated_at: datetime


class EarthWorkspaceState(BaseModel):
    camera_history: EarthCameraHistory = Field(default_factory=EarthCameraHistory)
    bookmarks: list[EarthBookmark] = Field(default_factory=list)
    captures: list[EarthCaptureMetadata] = Field(default_factory=list)
