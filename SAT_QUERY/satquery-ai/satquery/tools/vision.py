"""Stage 2 visual evidence tools.

These tools accept provider output or configured lazy providers. They never
turn a text request into a fabricated detection or segmentation.
"""

from __future__ import annotations

import time
from typing import Any

from ..schemas import BackendKind, ToolName
from ..vision.measure import count_detections, measure_detections, measure_mask
from ..vision.providers import Detector, Segmenter
from .base import Tool, ToolContext


class DetectObjectsTool(Tool):
    name = ToolName.DETECT_OBJECTS
    description = "Runs a configured object detector and returns machine-generated boxes with provenance."
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext):
        started = time.perf_counter()
        provider = context.arguments.get("provider")
        labels = context.arguments.get("labels") or ([context.target] if context.target else [])
        if not isinstance(provider, Detector):
            raise RuntimeError("No object detector is configured. Configure a Grounding DINO or EO-trained Detector provider.")
        detections = provider.detect(context.primary.pil, labels)
        return self.result(
            summary=f"Detector returned {len(detections)} machine-generated object hypotheses.",
            started=started,
            backend=BackendKind.PRACTICAL,
            model=provider.model_id,
            data={"detections": [d.__dict__ for d in detections], "labels": list(labels), "count": count_detections(detections)},
            confidence=max((item.confidence for item in detections), default=0.0),
        )


class SegmentRegionTool(Tool):
    name = ToolName.SEGMENT_REGION
    description = "Runs a configured promptable segmenter and returns measurable boolean masks."
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext):
        started = time.perf_counter()
        provider = context.arguments.get("provider")
        boxes = context.arguments.get("boxes")
        if not isinstance(provider, Segmenter):
            raise RuntimeError("No segmenter is configured. Configure a SAM2 or EO-trained Segmenter provider.")
        segmentations = provider.segment(context.primary.pil, boxes)
        return self.result(
            summary=f"Segmenter returned {len(segmentations)} machine-generated masks.",
            started=started,
            backend=BackendKind.PRACTICAL,
            model=provider.model_id,
            data={"segmentations": [measure_mask(item) for item in segmentations], "mask_count": len(segmentations)},
            confidence=max((item.confidence for item in segmentations), default=0.0),
        )


class MeasureVisualEvidenceTool(Tool):
    name = ToolName.MEASURE
    description = "Measures supplied detections or segmentation masks using deterministic EO geometry."
    min_images = 1
    max_images = 1

    def run(self, context: ToolContext):
        started = time.perf_counter()
        detections = context.arguments.get("detections") or []
        segmentation = context.arguments.get("segmentation")
        if segmentation is not None:
            data = {"measurement": measure_mask(segmentation), "provenance": segmentation.metadata}
            summary = f"Measured {segmentation.label} mask coverage over {segmentation.pixel_count} pixels."
        else:
            data = {"measurements": measure_detections(detections), "count": count_detections(detections)}
            summary = f"Measured {len(detections)} supplied detections."
        return self.result(summary=summary, started=started, backend=BackendKind.NONE, data=data, confidence=1.0)
