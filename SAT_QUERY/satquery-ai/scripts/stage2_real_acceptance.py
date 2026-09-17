r"""Run optional real Stage 2 inference on an existing EO-like image.

From satquery-ai:
  ..\..\.venv\Scripts\python.exe scripts/stage2_real_acceptance.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PIL import Image

from satquery.vision import GroundingDinoDetector, Sam2Segmenter, render_evidence
from satquery.vision.measure import count_detections, measure_detections, measure_mask

ROOT = Path(__file__).resolve().parents[1]
IMAGE = sorted((ROOT / "data" / "fetched_images").glob("*.jpg"))[0]
OUTPUT = ROOT.parent / "artifacts" / "outputs"
OUTPUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    detector_id = os.getenv("SATQUERY_DETECTOR_MODEL", "IDEA-Research/grounding-dino-tiny")
    segmenter_id = os.getenv("SATQUERY_SEGMENTER_MODEL", "facebook/sam2.1-hiera-tiny")
    image = Image.open(IMAGE).convert("RGB")
    started = time.perf_counter()
    detector = GroundingDinoDetector(detector_id, device=os.getenv("SATQUERY_DEVICE", "cpu"))
    detections = detector.detect(image, ["building", "water", "road", "vehicle"])
    detector_seconds = time.perf_counter() - started
    segmentations = []
    segmenter_seconds = None
    if detections:
        started = time.perf_counter()
        segmenter = Sam2Segmenter(segmenter_id, device=os.getenv("SATQUERY_DEVICE", "cpu"))
        segmentations = segmenter.segment(image, [d.box for d in detections[:3]])
        segmenter_seconds = time.perf_counter() - started
    output_image = OUTPUT / f"stage2-{IMAGE.stem}.jpg"
    render_evidence(image, detections=detections, segmentations=segmentations, output_path=output_image)
    report = {
        "image": str(IMAGE),
        "detector": detector_id,
        "segmenter": segmenter_id,
        "detector_seconds": round(detector_seconds, 3),
        "segmenter_seconds": round(segmenter_seconds, 3) if segmenter_seconds is not None else None,
        "detections": [d.__dict__ for d in detections],
        "detection_counts": count_detections(detections),
        "detection_measurements": measure_detections(detections),
        "segmentations": [measure_mask(item) for item in segmentations],
        "rendered_evidence": str(output_image),
        "geospatial_measurements": "unavailable: fetched JPEG has no CRS/transform",
    }
    report_path = OUTPUT / "stage2-real-acceptance.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
