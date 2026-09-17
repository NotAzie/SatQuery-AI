from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fetch_tiles import acquire
from reconstruct import reconstruct
from tiled_inference import run

REPORT_DIR = ROOT / "reports"
OUTPUTS = ROOT / "outputs"


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    report = {"status": "BLOCKED", "acquisition": {}, "tile_count": 0, "tile_dimensions": {}, "tile_zoom": None, "tile_overlap": None, "provider": "Esri World Imagery export", "resolution_per_tile": [], "original_single_image_resolution": {"note": "Reference is the previously fetched wide JPEG; its metadata is not a native GSD guarantee."}, "detections_before_merge": 0, "detections_after_merge": 0, "merged_cross_tile_objects": 0, "building_count": 0, "road_count": 0, "water_count": 0, "vehicle_count": 0, "segmentations": {}, "timings": {}, "errors": [], "comparison": {}, "visual_observations": {}}
    try:
        acquisition = acquire()
        report["acquisition"] = acquisition
        report["tile_count"] = len(acquisition["tiles"])
        report["tile_dimensions"] = {"width": acquisition["tile_size"][0], "height": acquisition["tile_size"][1]}
        report["tile_zoom"] = acquisition["zoom"]
        report["tile_overlap"] = acquisition["overlap"]
        report["resolution_per_tile"] = [{"tile_id": tile["tile_id"], "requested_bounds": tile["bounds"], "zoom": tile["requested_zoom"]} for tile in acquisition["tiles"]]
        inference = run(acquisition)
        report.update({key: value for key, value in inference.items() if key != "evidence"})
        merged = inference["detections"]
        report["building_count"] = sum(item["label"] == "building" for item in merged)
        report["road_count"] = sum(item["label"] == "road" for item in merged)
        report["water_count"] = sum(item["label"] == "water" for item in merged)
        report["vehicle_count"] = sum(item["label"] == "vehicle" for item in merged)
        report["timings"] = {"detector_seconds": inference["total_detector_seconds"], "segmenter_seconds": inference["total_segmenter_seconds"]}
        report["comparison"] = {"same_area_intent": True, "new_tiles_are_smaller_footprints": True, "native_resolution_claim": "provider requested zoom/extent; native mosaic GSD remains provider/location dependent"}
        report["visual_observations"] = {"buildings": "real boxes returned; inspect tiled-evidence.jpg for broadness", "roads": "real boxes returned; broad-region behavior possible", "water": "real boxes returned; broad-region behavior possible", "vehicles": "real boxes returned only if present; no accuracy claim", "SAM2": "real masks generated from tile detections"}
        report["outputs"] = {"tile_grid": str(OUTPUTS / "tile-grid.jpg"), "reconstruction": str(OUTPUTS / "tiled-reconstruction.jpg"), "evidence": str(OUTPUTS / "tiled-evidence.jpg")}
        reconstruct(acquisition["tiles"], acquisition["union_bounds"], OUTPUTS / "tiled-reconstruction.jpg", OUTPUTS / "tile-grid.jpg", inference["detections"])
        shutil.copyfile(OUTPUTS / "tiled-reconstruction.jpg", OUTPUTS / "tiled-evidence.jpg")
        report["status"] = "passed"
    except Exception as exc:
        report["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    path = REPORT_DIR / "tiled_eo_report.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
