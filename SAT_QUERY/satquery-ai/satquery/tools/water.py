"""Phase 8 spectral water intelligence tool."""

from __future__ import annotations

import time
from typing import Any

from ..eo.data import EOData, load_eo_raster
from ..eo.water import analyze_water
from ..schemas import BackendKind, ToolName
from ..vision.evidence import Segmentation
from ..vision.render import render_evidence
from .base import Tool, ToolContext


class WaterAnalysisTool(Tool):
    name = ToolName.WATER_ANALYSIS
    description = "Extracts water from multispectral NDWI/MNDWI, filters small components, and measures area and fraction."
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext):
        started = time.perf_counter()
        path = context.arguments.get("path") or context.primary.source
        raster = load_eo_raster(path)
        index = str(context.arguments.get("index") or "ndwi")
        threshold = float(context.arguments.get("threshold", 0.0))
        minimum_pixels = int(context.arguments.get("minimum_pixels", 1))
        bands = context.arguments.get("bands")
        analysis = analyze_water(raster, index=index, threshold=threshold, minimum_pixels=minimum_pixels, bands=bands)
        data: dict[str, Any] = {
            "index": analysis.index,
            "threshold": analysis.threshold,
            "statistics": analysis.statistics,
            "area": analysis.area,
            "mask_shape": list(analysis.mask.shape),
            "mask": analysis.mask.tolist(),
            "provenance": analysis.provenance,
            "warnings": list(analysis.warnings),
            "source": raster.source,
        }
        output_path = context.arguments.get("output_path")
        if output_path:
            from PIL import Image

            image = Image.open(path).convert("RGB")
            segmentation = Segmentation("water", 1.0, analysis.mask, "spectral_water", analysis.index, metadata=analysis.provenance)
            render_evidence(image, segmentations=[segmentation], output_path=output_path)
            data["evidence_path"] = str(output_path)
        return self.result(
            summary=f"Water analysis using {analysis.index} found {analysis.statistics['water_pixels']} water pixels ({analysis.statistics['water_fraction']:.2%} of valid pixels).",
            started=started,
            backend=BackendKind.NONE,
            data=data,
            confidence=1.0 if not analysis.warnings else 0.7,
            warnings=analysis.warnings,
        )
