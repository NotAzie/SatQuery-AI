"""Deterministic EO tools exposed through SatQuery's existing tool contract."""

from __future__ import annotations

import time
from typing import Any, Dict

from ..eo.data import EOData, load_eo_raster
from ..eo.raster import calculate_area, raster_statistics
from ..eo.spectral import calculate_index, list_indices
from ..schemas import BackendKind, ToolName, ToolResult
from .base import Tool, ToolContext


def _load(context: ToolContext) -> EOData:
    path = context.arguments.get("path") or context.primary.source
    if path and path != "upload" and path != "memory":
        try:
            return load_eo_raster(path)
        except (FileNotFoundError, RuntimeError, ValueError):
            pass
    return EOData(
        data=context.primary.array.astype("float32").transpose(2, 0, 1),
        source=context.primary.source,
        band_names=("red", "green", "blue"),
        dtype="float32",
        warnings=(),
    )


class EOInspectionTool(Tool):
    name = ToolName.EO_INSPECTION
    description = "Inspects EO raster bands, metadata, georeferencing, and provenance without guessing missing fields."
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        raster = _load(context)
        data = {
            "source": raster.source,
            "shape": list(raster.shape),
            "dtype": raster.dtype,
            "band_names": list(raster.band_names),
            "band_descriptions": list(raster.band_descriptions),
            "wavelengths": list(raster.wavelengths),
            "crs": raster.crs,
            "transform": raster.transform,
            "bounds": raster.bounds,
            "resolution": raster.resolution,
            "acquisition_time": raster.acquisition_time,
            "sensor": raster.sensor,
            "platform": raster.platform,
            "nodata": raster.nodata,
            "georeferenced": raster.is_georeferenced,
            "eo_native": raster.is_eo_native,
            "warnings": [warning.__dict__ for warning in raster.warnings],
            "provenance": raster.provenance("inspect_eo_data"),
        }
        mode = "georeferenced EO raster" if raster.is_georeferenced else "non-georeferenced image fallback"
        summary = f"Inspected {mode}: {raster.band_count} band(s), {raster.width}x{raster.height}, dtype {raster.dtype}."
        if raster.warnings:
            summary += " " + " ".join(warning.message for warning in raster.warnings)
        return self.result(summary=summary, started=started, backend=BackendKind.NONE, data=data, confidence=1.0 if raster.is_georeferenced else 0.5)


class RasterStatisticsTool(Tool):
    name = ToolName.RASTER_STATISTICS
    description = "Computes valid-pixel raster statistics and optional physical area for a threshold mask."
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        raster = _load(context)
        band = context.arguments.get("band")
        values = raster.band(band) if band is not None else raster.data
        stats = raster_statistics(raster, values)
        data: Dict[str, Any] = {"statistics": stats, "provenance": raster.provenance("raster_statistics", band=band)}
        return self.result(summary=f"Raster statistics computed for {stats['count']} valid values.", started=started, backend=BackendKind.NONE, data=data, confidence=1.0)


class SpectralIndexTool(Tool):
    name = ToolName.SPECTRAL_INDEX
    description = "Calculates a registered spectral index from explicitly resolved bands and reports statistics/provenance."
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        raster = _load(context)
        index = str(context.arguments.get("index") or "ndvi")
        bands = context.arguments.get("bands")
        result = calculate_index(raster, index, bands=bands)
        stats = raster_statistics(raster, result.values)
        data = {
            "index": index.upper(),
            "formula": result.provenance["parameters"]["formula"],
            "statistics": stats,
            "warnings": list(result.warnings),
            "provenance": result.provenance,
            "available_indices": [definition.name for definition in list_indices()],
        }
        return self.result(summary=f"Calculated {index.upper()} over {stats['count']} valid pixels.", started=started, backend=BackendKind.NONE, data=data, confidence=1.0)
