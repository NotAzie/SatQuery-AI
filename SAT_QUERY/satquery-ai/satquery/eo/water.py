"""Deterministic multispectral water extraction and statistics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import numpy as np

from .data import EOData
from .raster import calculate_area, raster_statistics
from .spectral import calculate_index


@dataclass(frozen=True)
class WaterAnalysis:
    index: str
    threshold: float
    mask: np.ndarray
    index_values: np.ndarray
    statistics: dict[str, Any]
    area: dict[str, Any]
    provenance: dict[str, Any]
    warnings: tuple[str, ...] = ()


def _components(mask: np.ndarray, minimum_pixels: int) -> np.ndarray:
    """Keep connected 4-neighbour water components above a pixel threshold."""
    source = np.asarray(mask, dtype=bool)
    height, width = source.shape
    visited = np.zeros_like(source)
    output = np.zeros_like(source)
    for row, col in zip(*np.where(source & ~visited)):
        if visited[row, col]:
            continue
        stack = [(int(row), int(col))]
        visited[row, col] = True
        members = []
        while stack:
            current_row, current_col = stack.pop()
            members.append((current_row, current_col))
            for next_row, next_col in ((current_row - 1, current_col), (current_row + 1, current_col), (current_row, current_col - 1), (current_row, current_col + 1)):
                if 0 <= next_row < height and 0 <= next_col < width and source[next_row, next_col] and not visited[next_row, next_col]:
                    visited[next_row, next_col] = True
                    stack.append((next_row, next_col))
        if len(members) >= minimum_pixels:
            rows, cols = zip(*members)
            output[list(rows), list(cols)] = True
    return output


def analyze_water(
    raster: EOData,
    *,
    index: str = "ndwi",
    threshold: float = 0.0,
    minimum_pixels: int = 1,
    bands: Optional[Mapping[str, str | int]] = None,
) -> WaterAnalysis:
    if index.lower() not in {"ndwi", "mndwi"}:
        raise ValueError("Water extraction supports NDWI or MNDWI only.")
    result = calculate_index(raster, index, bands=bands)
    index_values = result.values
    valid = np.isfinite(index_values)
    raw_mask = valid & (index_values >= threshold)
    mask = _components(raw_mask, max(1, int(minimum_pixels)))
    statistics = raster_statistics(raster, index_values)
    area = calculate_area(mask, raster)
    valid_pixels = int(valid.sum())
    water_pixels = int(mask.sum())
    statistics.update({"valid_pixels": valid_pixels, "water_pixels": water_pixels, "water_fraction": water_pixels / valid_pixels if valid_pixels else 0.0})
    provenance = raster.provenance("water_analysis", index=index.upper(), threshold=threshold, minimum_pixels=minimum_pixels, bands=bands or {name: name for name in ("green", "nir") if name in raster.band_names})
    warnings = list(result.warnings)
    if not raster.is_georeferenced:
        warnings.append("Physical water area is unavailable because the source is not georeferenced.")
    return WaterAnalysis(index.upper(), threshold, mask, index_values, statistics, area, provenance, tuple(warnings))
