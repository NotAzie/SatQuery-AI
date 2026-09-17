"""Provider-agnostic visual evidence and deterministic measurement primitives."""

from .evidence import Detection, GeoFootprint, Segmentation, pixel_box_to_geo
from .merge import Tile, generate_tiles, merge_detections, non_max_suppression
from .providers import Detector, GroundingDinoDetector, Segmenter, Sam2Segmenter
from .measure import count_detections, measure_detections, measure_mask
from .render import render_evidence

__all__ = [
    "Detection",
    "Detector",
    "GeoFootprint",
    "GroundingDinoDetector",
    "Sam2Segmenter",
    "Segmenter",
    "Segmentation",
    "Tile",
    "count_detections",
    "generate_tiles",
    "merge_detections",
    "measure_detections",
    "measure_mask",
    "non_max_suppression",
    "pixel_box_to_geo",
    "render_evidence",
]
