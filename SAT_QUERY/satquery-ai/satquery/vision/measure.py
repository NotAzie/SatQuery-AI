"""Deterministic measurements over visual evidence."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

import numpy as np

from ..eo.data import EOData
from ..eo.raster import calculate_area
from .evidence import Detection, Segmentation


def count_detections(detections: Iterable[Detection], *, label: Optional[str] = None, minimum_confidence: float = 0.0) -> dict[str, Any]:
    selected = [item for item in detections if item.confidence >= minimum_confidence and (label is None or item.label.lower() == label.lower())]
    by_class: dict[str, int] = {}
    for item in selected:
        by_class[item.label] = by_class.get(item.label, 0) + 1
    return {"count": len(selected), "by_class": by_class, "minimum_confidence": minimum_confidence}


def measure_mask(segmentation: Segmentation, raster: Optional[EOData] = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "label": segmentation.label,
        "confidence": segmentation.confidence,
        "pixel_count": segmentation.pixel_count,
        "image_fraction": float(segmentation.mask.mean()),
        "pixel_box": segmentation.pixel_box,
        "area_m2": None,
        "area_ha": None,
        "area_available": False,
    }
    if raster is not None:
        result.update(calculate_area(segmentation.mask, raster))
    return result


def measure_detections(detections: Sequence[Detection], raster: Optional[EOData] = None) -> list[dict[str, Any]]:
    results = []
    for detection in detections:
        x0, y0, x1, y1 = detection.box
        result: dict[str, Any] = {
            "label": detection.label,
            "confidence": detection.confidence,
            "box": detection.box,
            "pixel_area": max(0.0, x1 - x0) * max(0.0, y1 - y0),
            "area_m2": None,
            "area_available": False,
            "provenance": {"source": detection.source, "model": detection.model, "model_version": detection.model_version},
        }
        if raster is not None and raster.is_georeferenced:
            mask = np.zeros((raster.height, raster.width), dtype=bool)
            left, top, right, bottom = (int(round(value)) for value in detection.box)
            mask[max(0, top):min(raster.height, bottom), max(0, left):min(raster.width, right)] = True
            result.update(calculate_area(mask, raster))
        results.append(result)
    return results
