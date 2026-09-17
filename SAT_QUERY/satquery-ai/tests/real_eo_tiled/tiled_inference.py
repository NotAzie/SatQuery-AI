from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from merge_detections import merge_global
from reconstruct import global_box
from satquery.vision import GroundingDinoDetector, Sam2Segmenter, render_evidence

OUTPUTS = ROOT / "outputs"


def run(acquisition: dict) -> dict:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    tiles = acquisition["tiles"]
    union = acquisition["union_bounds"]
    tile_width, tile_height = acquisition["tile_size"]
    detector = GroundingDinoDetector(os.getenv("SATQUERY_DETECTOR_MODEL", "IDEA-Research/grounding-dino-tiny"), device=os.getenv("SATQUERY_DEVICE", "cpu"))
    segmenter = Sam2Segmenter(os.getenv("SATQUERY_SEGMENTER_MODEL", "facebook/sam2.1-hiera-tiny"), device=os.getenv("SATQUERY_DEVICE", "cpu"))
    all_detections = []
    per_tile = []
    segmentations = []
    total_detector = 0.0
    total_segmenter = 0.0
    for tile in tiles:
        image = Image.open(tile["path"]).convert("RGB")
        started = time.perf_counter()
        detections = detector.detect(image, ["building", "road", "water", "vehicle"])
        detector_seconds = time.perf_counter() - started
        total_detector += detector_seconds
        global_detections = []
        for item in detections:
            box = global_box(item.box, tile["bounds"], union, (len({t["col"] for t in tiles}) * tile_width, len({t["row"] for t in tiles}) * tile_height))
            global_detections.append(type(item)(item.label, item.confidence, box, item.source, item.model, item.model_version, item.image_id, tile["tile_id"], item.geo_footprint, {**item.metadata, "tile_box": item.box}))
        all_detections.extend(global_detections)
        started = time.perf_counter()
        masks = segmenter.segment(image, [item.box for item in detections[:3]]) if detections else []
        segmenter_seconds = time.perf_counter() - started
        total_segmenter += segmenter_seconds
        segmentations.extend(masks)
        per_tile.append({"tile_id": tile["tile_id"], "detections": len(detections), "detector_seconds": round(detector_seconds, 3), "masks": len(masks), "segmenter_seconds": round(segmenter_seconds, 3), "labels": [item.label for item in detections]})
    merged, merged_count = merge_global(all_detections)
    source_image = Image.open(tiles[0]["path"]).convert("RGB")
    evidence_path = OUTPUTS / "tiled-evidence.jpg"
    render_evidence(source_image, detections=[], segmentations=[], output_path=evidence_path)
    return {"per_tile": per_tile, "detections_before_merge": len(all_detections), "detections_after_merge": len(merged), "merged_cross_tile_objects": merged_count, "detections": [item.__dict__ for item in merged], "total_detector_seconds": round(total_detector, 3), "total_segmenter_seconds": round(total_segmenter, 3), "evidence": str(evidence_path)}
