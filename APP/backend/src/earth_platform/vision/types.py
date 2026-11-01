import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from earth_platform.shared.clock import utcnow
from earth_platform.shared.earth import EarthCaptureMetadata
from earth_platform.shared.geo import BoundingBox, LngLat

ImageOrigin = Literal["upload", "drag_drop", "clipboard", "screen_capture", "earth_capture", "url"]


class GeoReference(BaseModel):
    """Best-known placement of an image on Earth when it is known (e.g. an Earth capture or a
    GeoTIFF). Absent for ordinary photos; locating those is an investigation, not metadata."""

    bounds: BoundingBox | None = None
    center: LngLat | None = None
    crs: str = Field(default="EPSG:4326", min_length=1, max_length=128)
    orientation_deg: float = Field(default=0, allow_inf_nan=False)
    pixel_resolution_m: tuple[float, float] | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("pixel_resolution_m")
    @classmethod
    def _positive_resolution(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and any(not math.isfinite(item) or item <= 0 for item in value):
            raise ValueError("pixel resolutions must be positive")
        return value


class ImageAsset(BaseModel):
    id: str
    session_id: str | None = None
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    sha256: str
    origin: ImageOrigin
    filename: str | None = None
    georef: GeoReference | None = None
    created_at: datetime = Field(default_factory=utcnow)
    source_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class VisionContext(BaseModel):
    assets: list[ImageAsset] = Field(default_factory=list)
    earth_captures: list[EarthCaptureMetadata] = Field(default_factory=list)
    georeference: GeoReference | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class PrepareVisionRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1)
    context: VisionContext = Field(default_factory=VisionContext)


class UpdateImageAssetRequest(BaseModel):
    filename: str | None = None
    georef: GeoReference | None = None


class PreparedVisionAsset(BaseModel):
    asset: ImageAsset
    data_base64: str


class PreparedVisionPayload(BaseModel):
    """Provider-neutral binary and metadata payload, not a provider request format."""

    version: int = 1
    context: VisionContext
    assets: list[PreparedVisionAsset]
