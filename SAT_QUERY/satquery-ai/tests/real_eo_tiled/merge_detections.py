from __future__ import annotations

from typing import Iterable, List, Tuple

from satquery.vision.evidence import Detection
from satquery.vision.merge import _iou


def merge_global(detections: Iterable[Detection], iou_threshold: float = 0.35) -> tuple[list[Detection], int]:
    kept: list[Detection] = []
    merged_sources: list[list[str]] = []
    for item in sorted(detections, key=lambda value: value.confidence, reverse=True):
        match = None
        for index, existing in enumerate(kept):
            if existing.label == item.label and _iou(existing.box, item.box) >= iou_threshold:
                match = index
                break
        if match is None:
            kept.append(item)
            merged_sources.append([item.tile_id or "unknown"])
        else:
            previous = kept[match]
            union = (min(previous.box[0], item.box[0]), min(previous.box[1], item.box[1]), max(previous.box[2], item.box[2]), max(previous.box[3], item.box[3]))
            kept[match] = Detection(previous.label, max(previous.confidence, item.confidence), union, previous.source, previous.model, previous.model_version, previous.image_id, previous.tile_id, previous.geo_footprint, {**previous.metadata, "source_tiles": sorted(set(merged_sources[match] + [item.tile_id or "unknown"])), "merged": True})
            merged_sources[match].append(item.tile_id or "unknown")
    return kept, len(detections) - len(kept)
