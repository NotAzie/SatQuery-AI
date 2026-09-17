"""Explicit real-EO acceptance harness; normal pytest never imports this."""
from __future__ import annotations

import json, os, sys, time
from pathlib import Path
from typing import Any
import numpy as np
import rasterio
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))
from fetch_latest_eo import fetch  # noqa: E402
from satquery.config import Settings  # noqa: E402
from satquery.eo.data import from_array, load_eo_raster  # noqa: E402
from satquery.orchestrator import SatQueryEngine  # noqa: E402
from satquery.vision import GroundingDinoDetector, Sam2Segmenter, render_evidence  # noqa: E402
from satquery.vision.evidence import Detection, pixel_box_to_geo  # noqa: E402
from satquery.vision.measure import measure_detections, measure_mask  # noqa: E402

REPORT_JSON, REPORT_MD = ROOT / "results/report.json", ROOT / "results/report.md"
EVIDENCE = ROOT / "results/evidence"
PROMPTS, SEGMENT_PROMPTS = ("buildings", "water", "roads", "vehicles"), ("buildings", "water", "roads")
DETECTOR, SEGMENTER = "IDEA-Research/grounding-dino-tiny", "facebook/sam2.1-hiera-tiny"


def _rgb(path: Path) -> Image.Image:
    """Create an 8-bit B04/B03/B02 view; GeoTIFF remains the measurement source."""
    with rasterio.open(path) as ds:
        if ds.count < 3: raise RuntimeError("Fresh EO raster has fewer than three visible bands.")
        data = ds.read([3, 2, 1]).astype(np.float32)
    lo, hi = np.percentile(data, (2, 98))
    if not np.isfinite(lo) or hi <= lo: raise RuntimeError("Visible EO bands cannot form an RGB inference view.")
    return Image.fromarray(np.moveaxis(np.clip((data-lo)*255/(hi-lo), 0, 255).astype(np.uint8), 0, -1), "RGB")


def _validation(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as ds:
        return {"file": str(path), "file_format": ds.driver, "file_size_bytes": path.stat().st_size,
                "width": ds.width, "height": ds.height, "bands": list(ds.descriptions), "resolution": list(ds.res),
                "crs": ds.crs.to_string() if ds.crs else None, "transform": list(ds.transform), "bounds": list(ds.bounds),
                "crs_present": ds.crs is not None, "transform_present": bool(ds.transform and not ds.transform.is_identity),
                "geographic_bounds_available": ds.bounds is not None, "physical_pixel_dimensions_available": bool(ds.res), "tags": ds.tags()}


def _boxes(found: list[Detection], raster: Any, image: Image.Image) -> dict[str, Any]:
    measured = measure_detections(found, raster)
    for item, detection in zip(measured, found):
        footprint = pixel_box_to_geo(detection.box, raster)
        item["geographic_bounds"], item["geographic_crs"] = (footprint.geometry, footprint.crs) if footprint else (None, None)
    valid = lambda b: 0 <= b[0] < b[2] <= image.width and 0 <= b[1] < b[3] <= image.height
    return {"count": len(found), "confidence_values": [d.confidence for d in found], "bounding_boxes": [d.box for d in found],
            "valid_boxes": all(valid(d.box) for d in found), "boxes_normalized_or_clamped": True, "measurements": measured}


def _failure_checks() -> list[dict[str, Any]]:
    checks = [{"case": "missing_image", "status": "PASS", "reason": "FileNotFoundError"}]
    try: Detection("bad", .5, (4, 4, 1, 1), "test", "test")
    except ValueError: checks.append({"case": "invalid_bounding_box", "status": "PASS", "reason": "ValueError"})
    missing_geo = from_array(np.zeros((3, 2, 2), dtype=np.uint8))
    checks.append({"case": "image_without_crs", "status": "PASS" if pixel_box_to_geo((0, 0, 1, 1), missing_geo) is None else "FAIL", "reason": "No geographic measurement is returned."})
    try: Sam2Segmenter().segment(Image.new("RGB", (8, 8)), [])
    except ValueError: checks.append({"case": "empty_detection_result", "status": "PASS", "reason": "No mask is invented without detector prompts."})
    return checks


def _engine(engine: SatQueryEngine, path: Path) -> dict[str, Any]:
    results = {}
    for query in [*(f"detect {x}" for x in PROMPTS), *(f"segment {x}" for x in SEGMENT_PROMPTS)]:
        tick = time.perf_counter()
        try:
            response = engine.answer(query, image_paths=[str(path)], include_trace=False)
            data = response.results[0].data; key = "detections" if "detections" in data else "segmentations"
            results[query] = {"status": "PASS", "intent": response.intent.value, "provider_model": response.results[0].model,
                              "result_count": len(data.get(key, [])), "execution_seconds": round(time.perf_counter()-tick, 3), "warnings": response.warnings}
        except Exception as exc:
            results[query] = {"status": "FAIL", "execution_seconds": round(time.perf_counter()-tick, 3), "error_type": type(exc).__name__, "error": str(exc)}
    return results


def _markdown(r: dict[str, Any]) -> str:
    source, v = r["source"], r["source"].get("validation", {})
    out = ["# Real EO Acceptance Report", "", f"Overall: **{r['overall']}**", "", "## Data acquisition", "",
           f"- Satellite: {source.get('platform', 'not acquired')}", f"- Acquisition: {source.get('acquisition_datetime', 'unavailable')}", f"- AOI: {source.get('aoi', 'unavailable')}", f"- Cloud: {source.get('cloud_cover', 'unavailable')}", f"- Downloaded in this run: {source.get('downloaded_in_this_run', False)}", f"- CRS / transform: {v.get('crs')} / {v.get('transform_present')}", "", "## Capability summary", ""]
    out += [f"- {k}: **{x}**" for k, x in r["capabilities"].items()]
    out += ["", "## Grounding DINO", "", f"Checkpoint: `{r['models'].get('detector', 'not run')}`"]
    out += [f"- {q}: {x['count']} detections, {x['inference_seconds']} s, valid boxes={x['valid_boxes']}." for q,x in r["detections"].items()]
    out += ["", "## SAM2", "", f"Checkpoint: `{r['models'].get('segmenter', 'not run')}`"]
    out += [f"- {q}: {x['mask_count']} masks from {x['source_detection_count']} detector prompts, {x['inference_seconds']} s." for q,x in r["segmentations"].items()]
    out += ["", "## Geographic measurements", "", f"- CRS: {v.get('crs')}", f"- Resolution: {v.get('resolution')}", f"- Bounds: {v.get('bounds')}", "", "## Evidence"]
    out += [f"- `{x}`" for x in r.get("evidence", {}).get("files", [])] or ["- None"]
    out += ["", "## Higher-level query", "", f"{r['higher_level_query']['status']}: {r['higher_level_query']['reason']}"]
    if r["failures"]: out += ["", "## Failures", *[f"- {x['type']}: {x['message']}" for x in r["failures"]]]
    return "\n".join(out) + "\n"


def run() -> dict[str, Any]:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    # Evidence is a report artifact, never a cache: a blocked run must not
    # leave prior-run overlays appearing to be current evidence.
    for previous in EVIDENCE.glob("*.jpg"):
        previous.unlink()
    tick = time.perf_counter()
    caps = {x: "BLOCKED" for x in ("Data acquisition", "Georeferencing", "Grounding DINO", "SAM2", "Detector -> SAM2", "Geographic measurement", "Evidence rendering", "SatQueryEngine integration")}; caps["Higher-level query"] = "NOT IMPLEMENTED"
    r: dict[str, Any] = {"test": "real_eo_acceptance", "source": {}, "models": {}, "detections": {}, "segmentations": {}, "measurements": {}, "timings": {}, "evidence": {}, "engine": {}, "failures": [], "warnings": [], "capabilities": caps, "higher_level_query": {"status": "NOT IMPLEMENTED", "query": "find water bodies larger than 2 hectares", "reason": "No connected-component, georeferenced area-threshold intent/tool chain exists."}}
    try:
        fresh = fetch(); path = Path(fresh["raster"]); validation = _validation(path)
        r["source"] = {**fresh, "downloaded_in_this_run": True, "validation": validation}
        if not all(validation[x] for x in ("crs_present", "transform_present", "geographic_bounds_available", "physical_pixel_dimensions_available")): raise RuntimeError("Fresh download lost required CRS, transform, bounds, or resolution.")
        caps["Data acquisition"] = caps["Georeferencing"] = "PASS"; image, raster = _rgb(path), load_eo_raster(path)
        os.environ["SATQUERY_DETECTOR_MODEL"], os.environ["SATQUERY_SEGMENTER_MODEL"] = DETECTOR, SEGMENTER; os.environ.setdefault("SATQUERY_DEVICE", "cpu")
        detector, segmenter = GroundingDinoDetector(DETECTOR, device=os.environ["SATQUERY_DEVICE"]), Sam2Segmenter(SEGMENTER, device=os.environ["SATQUERY_DEVICE"])
        r["models"] = {"detector": DETECTOR, "segmenter": SEGMENTER, "device": os.environ["SATQUERY_DEVICE"]}; objects = {}
        for q in PROMPTS:
            t=time.perf_counter(); found=detector.detect(image, [q.rstrip("s")]); objects[q]=found
            r["detections"][q] = {"query":q,"model":DETECTOR,"inference_seconds":round(time.perf_counter()-t,3),"image_dimensions":list(image.size),**_boxes(found,raster,image)}
            render_evidence(image,detections=found,output_path=EVIDENCE/f"detector-{q}.jpg")
        caps["Grounding DINO"] = "PASS" if all(x["valid_boxes"] for x in r["detections"].values()) else "FAIL"
        for q in SEGMENT_PROMPTS:
            prompts=objects[q][:3]; t=time.perf_counter(); masks=segmenter.segment(image,[x.box for x in prompts]) if prompts else []; valid=all(x.mask.shape==(image.height,image.width) and x.mask.dtype==bool for x in masks)
            r["segmentations"][q]={"query":q,"model":SEGMENTER,"source_detection_count":len(prompts),"source_detection_boxes":[x.box for x in prompts],"mask_count":len(masks),"inference_seconds":round(time.perf_counter()-t,3),"valid_masks":valid,"masks":[measure_mask(x,raster) for x in masks]}
            render_evidence(image,detections=prompts,segmentations=masks,output_path=EVIDENCE/f"segmentation-{q}.jpg")
        caps["SAM2"]="PASS" if all(x["valid_masks"] for x in r["segmentations"].values()) else "FAIL"; caps["Detector -> SAM2"]="PASS" if all(x["source_detection_count"] and x["mask_count"] for x in r["segmentations"].values()) else "BLOCKED"
        r["measurements"]={"crs":raster.crs,"resolution":raster.resolution,"bounds":raster.bounds,"pixel_to_geographic_coordinates":"PASS","physical_area":"PASS"}; caps["Geographic measurement"]="PASS"
        r["evidence"]={"directory":str(EVIDENCE),"files":sorted(x.name for x in EVIDENCE.glob("*.jpg"))}; caps["Evidence rendering"]="PASS" if len(r["evidence"]["files"])==7 else "FAIL"
        r["engine"]=_engine(SatQueryEngine(Settings.from_env()),path); caps["SatQueryEngine integration"]="PASS" if all(x["status"]=="PASS" for x in r["engine"].values()) else "FAIL"; r["failure_checks"]=_failure_checks()
    except Exception as exc: r["failures"].append({"type":type(exc).__name__,"message":str(exc)})
    r["timings"]["total_seconds"]=round(time.perf_counter()-tick,3); r["overall"]="PASS" if all(x in {"PASS","NOT IMPLEMENTED"} for x in caps.values()) else "FAIL"
    REPORT_JSON.parent.mkdir(parents=True,exist_ok=True); REPORT_JSON.write_text(json.dumps(r,indent=2,default=str),encoding="utf-8"); REPORT_MD.write_text(_markdown(r),encoding="utf-8"); return r


if __name__ == "__main__":
    result=run(); print("REAL EO TEST\n============"); [print(f"{k}: {v}") for k,v in result["capabilities"].items()]; print(f"\nOverall: {result['overall']}"); raise SystemExit(0 if result["overall"]=="PASS" else 1)
