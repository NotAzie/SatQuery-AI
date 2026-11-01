"""Geospatial and temporal value types used across module boundaries.

These are *transport* types, not a geometry library. Computation belongs to the Engine.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

# A GeoJSON geometry object (RFC 7946). Kept as a plain mapping on purpose.
GeoJSONGeometry = dict[str, Any]


class LngLat(BaseModel):
    lng: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)


class BoundingBox(BaseModel):
    """WGS84 degrees. west > east means the box crosses the antimeridian."""

    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def _check_latitudes(self) -> "BoundingBox":
        if self.south > self.north:
            raise ValueError("south must be <= north")
        return self


class TimeRange(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _check_order(self) -> "TimeRange":
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self
