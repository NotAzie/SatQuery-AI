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


class EarthSelection(BaseModel):
    entity_id: str
    position: LngLat | None = None
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class EarthDrawing(BaseModel):
    id: str
    name: str
    kind: Literal["point", "line", "polygon", "rectangle", "circle"]
    geometry: GeoJSONGeometry


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
    layers: list[LayerState] = Field(default_factory=list)
    time: TimeRange | None = None
    instant: datetime | None = None
    selection: EarthSelection | None = None
    drawings: list[EarthDrawing] = Field(default_factory=list)
    captures: list[EarthCaptureMetadata] = Field(default_factory=list)
    selected_evidence_ids: list[str] = Field(default_factory=list)
    bookmarks: list[EarthBookmarkRef] = Field(default_factory=list)
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
