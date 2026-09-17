from __future__ import annotations

import json
import os
import time
from pathlib import Path

import rasterio
from PIL import Image

from fetch_zoomed_eo import fetch_zoomed_geotiff
from plugins.image_fetcher.satellite_fetcher import FetcherSettings, SatelliteFetchError
from satquery.vision import GroundingDinoDetector, Sam2Segmenter, render_evidence
from satquery.vision.measure import measure_detections, measure_mask
from satquery.eo.data import load_eo_raster

ROOT = Path(__file__).resolve().parent
IMAGES = ROOT / "images"
OUTPUTS = ROOT / "outputs"
REPORT = ROOT / "report.json"


def main() -> int:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    lat = float(os.getenv("SATQUERY_ZOOM_LAT", "12.8500"))
    lon = float(os.getenv("SATQUERY_ZOOM_LON", "80.1800"))
    target = os.getenv("SATQUERY_ZOOM_TARGET", "building")
    zoom = int(os.getenv("SATQUERY_ZOOM_LEVEL", "19"))
    width = int(os.getenv("SATQUERY_ZOOM_WIDTH", "1024"))
    height = int(os.getenv("SATQUERY_ZOOM_HEIGHT", "1024"))
    report = {"status": "BLOCKED", "target": target, "requested_zoom": zoom, "requested_size": [width, height], "source": {}, "detector": {}, "segmenter": {}, "limitations": []}
    try:
        image_path, metadata_path = fetch_zoomed_geotiff(latitude=lat, longitude=lon, target=target, zoom=zoom, width=width, height=height, output_dir=str(IMAGES))
        with rasterio.open(image_path) as dataset:
            report["source"] = {"image": str(image_path), "metadata": str(metadata_path), "shape": [dataset.width, dataset.height], "crs": str(dataset.crs), "bounds": list(dataset.bounds), "resolution": list(dataset.res), "tags": dataset.tags()}
        eo_raster = load_eo_raster(image_path)
        image = Image.open(image_path).convert("RGB")
        detector = GroundingDinoDetector(os.getenv("SATQUERY_DETECTOR_MODEL", "IDEA-Research/grounding-dino-tiny"), device=os.getenv("SATQUERY_DEVICE", "cpu"))
        started = time.perf_counter()
        detections = detector.detect(image, [target.rstrip("s"), "road", "water", "vehicle"])
        report["detector"] = {"model": detector.model_id, "seconds": round(time.perf_counter() - started, 3), "count": len(detections), "labels": [item.label for item in detections], "measurements": measure_detections(detections, eo_raster)}
        segmenter = Sam2Segmenter(os.getenv("SATQUERY_SEGMENTER_MODEL", "facebook/sam2.1-hiera-tiny"), device=os.getenv("SATQUERY_DEVICE", "cpu"))
        started = time.perf_counter()
        masks = segmenter.segment(image, [item.box for item in detections[:3]]) if detections else []
        report["segmenter"] = {"model": segmenter.model_id, "seconds": round(time.perf_counter() - started, 3), "count": len(masks), "measurements": [measure_mask(item, eo_raster) for item in masks]}
        evidence_path = OUTPUTS / f"zoom-z{zoom}-{target}.jpg"
        render_evidence(image, detections=detections, segmentations=masks, output_path=evidence_path)
        report["evidence"] = str(evidence_path)
        report["status"] = "passed"
        report["limitations"] = ["Provider output is server-rendered; zoom reduces geographic extent but does not guarantee native GSD.", "Current 10m/imagery-provider model results may still merge broad regions; no accuracy claim is made."]
    except SatelliteFetchError as exc:
        report["failures"] = [{"type": "SatelliteFetchError", "message": str(exc), "remediation": exc.remediation}]
    except Exception as exc:
        report["failures"] = [{"type": type(exc).__name__, "message": str(exc)}]
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
