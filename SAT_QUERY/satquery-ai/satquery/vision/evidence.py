"""Machine-generated visual evidence schemas and pixel-to-geo transforms."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import numpy as np

from ..eo.data import EOData


@dataclass(frozen=True)
class GeoFootprint:
    geometry: Dict[str, Any]
    crs: str
    method: str


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: Tuple[float, float, float, float]
    source: str
    model: str
    model_version: Optional[str] = None
    image_id: Optional[str] = None
    tile_id: Optional[str] = None
    geo_footprint: Optional[GeoFootprint] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Detection confidence must be between 0 and 1.")
        x0, y0, x1, y1 = self.box
        if not (0 <= x0 <= x1 and 0 <= y0 <= y1):
            raise ValueError("Detection box must be ordered as x0,y0,x1,y1.")


@dataclass(frozen=True)
class Segmentation:
    label: str
    confidence: float
    mask: np.ndarray
    source: str
    model: str
    model_version: Optional[str] = None
    image_id: Optional[str] = None
    geo_footprint: Optional[GeoFootprint] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.mask.ndim != 2 or self.mask.dtype != bool:
            raise ValueError("Segmentation mask must be a 2-D boolean NumPy array.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Segmentation confidence must be between 0 and 1.")

    @property
    def pixel_count(self) -> int:
        return int(self.mask.sum())

    @property
    def pixel_box(self) -> Tuple[int, int, int, int]:
        ys, xs = np.where(self.mask)
        if len(xs) == 0:
            return (0, 0, 0, 0)
        return (int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1))


def pixel_box_to_geo(box: Tuple[float, float, float, float], raster: EOData) -> Optional[GeoFootprint]:
    """Transform a pixel box to a polygon only when raster georeferencing exists."""
    if not raster.is_georeferenced:
        return None
    try:
        from affine import Affine
        from pyproj import CRS
        from shapely.geometry import Polygon, mapping

        transform = Affine(*raster.transform)
        x0, y0, x1, y1 = box
        points = [
            transform * (x0, y0),
            transform * (x1, y0),
            transform * (x1, y1),
            transform * (x0, y1),
            transform * (x0, y0),
        ]
        return GeoFootprint(mapping(Polygon(points)), CRS.from_user_input(raster.crs).to_string(), "affine_pixel_transform")
    except Exception:
        return None
