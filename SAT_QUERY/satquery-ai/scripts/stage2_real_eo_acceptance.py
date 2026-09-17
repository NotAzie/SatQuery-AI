"""Opt-in, evidence-first multi-scale EO Stage 2 acceptance run.

It is deliberately outside pytest: this downloads EO data and loads real models.
"""
from __future__ import annotations

import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np
import rasterio
from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parents[1]
REAL = PROJECT / "tests" / "real_eo"
for name in ("images", "crops", "tiles", "outputs", "reports", "expected"):
    (REAL / name).mkdir(parents=True, exist_ok=True)
sys.path[:0] = [str(PROJECT), str(REAL)]
from fetch_latest_eo import fetch  # noqa: E402
from satquery.config import Settings  # noqa: E402
from satquery.eo.data import load_eo_raster  # noqa: E402
from satquery.orchestrator import SatQueryEngine  # noqa: E402
from satquery.vision import Detection, GroundingDinoDetector, Sam2Segmenter, Segmentation, generate_tiles, merge_detections, render_evidence  # noqa: E402
from satquery.vision.measure import measure_detections, measure_mask  # noqa: E402

OUT, CROPS, TILES, REPORTS = REAL / "outputs", REAL / "crops", REAL / "tiles", REAL / "reports"
CLASSES = {"building": ["building", "residential building"], "road": ["road", "street"], "water": ["water body", "water"], "vehicle": ["vehicle", "car"]}


def rgb(path: Path) -> Image.Image:
    with rasterio.open(path) as ds: a = ds.read([3, 2, 1]).astype(np.float32)
    lo, hi = np.percentile(a, (2, 98)); return Image.fromarray(np.moveaxis(np.clip((a-lo)*255/max(hi-lo, 1), 0, 255).astype(np.uint8), 0, -1), "RGB")


def source() -> tuple[Path, dict[str, Any], list[str]]:
    warnings: list[str] = []
    try:
        item = fetch(); return Path(item["raster"]), {**item, "fresh_download": True}, warnings
    except Exception as exc:
        old = sorted((REAL / "data" / "processed").glob("*.tif"))
        if not old: raise RuntimeError(f"Fresh EO fetch failed ({exc}) and no prior EO raster is available.") from exc
        warnings.append(f"Fresh fetch failed: {type(exc).__name__}: {exc}; using existing real EO raster, not a JPEG.")
        return old[-1], {"raster": str(old[-1]), "fresh_download": False}, warnings


def metadata(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as ds:
        return {"path":str(path),"format":ds.driver,"width":ds.width,"height":ds.height,"bands":list(ds.descriptions),"crs":str(ds.crs) if ds.crs else None,"transform":list(ds.transform),"resolution":list(ds.res),"bounds":list(ds.bounds),"file_size_bytes":path.stat().st_size,"georeferenced":bool(ds.crs and ds.transform and not ds.transform.is_identity),"tags":ds.tags()}


def map_detection(d: Detection, tile: Any, scale: str) -> Detection:
    x1,y1,x2,y2=d.box; box=(x1+tile.left,y1+tile.top,x2+tile.left,y2+tile.top)
    return Detection(d.label,d.confidence,box,d.source,d.model,tile_id=tile.tile_id,metadata={**d.metadata,"tile_box":d.box,"source_tile":[tile.left,tile.top,tile.right,tile.bottom],"scale":scale})


def valid(d: Detection, image: Image.Image, label: str) -> tuple[bool, str | None]:
    x1,y1,x2,y2=d.box; area=(x2-x1)*(y2-y1)
    if not all(np.isfinite(d.box)) or not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height): return False, "invalid_geometry"
    # Whole-tile boxes are a known DINO boundary failure for object prompts.
    if label in {"building", "vehicle"} and area / (image.width*image.height) > .85: return False, "absurd_image_coverage"
    return True, None


def crops(image: Image.Image, detections: list[Detection], masks: list[Segmentation], label: str) -> list[str]:
    files=[]
    for i,d in enumerate(detections):
        x1,y1,x2,y2=map(int,map(round,d.box)); pad=40; box=(max(0,x1-pad),max(0,y1-pad),min(image.width,x2+pad),min(image.height,y2+pad))
        view=image.crop(box).resize((max(1,(box[2]-box[0])*2),max(1,(box[3]-box[1])*2)))
        draw=ImageDraw.Draw(view); draw.rectangle(((x1-box[0])*2,(y1-box[1])*2,(x2-box[0])*2,(y2-box[1])*2),outline="red",width=3); draw.text((4,4),f"{label} {d.confidence:.2f} {d.tile_id}",fill="yellow")
        name=f"{label}_{i:03d}.png"; view.save(CROPS/name); files.append(name)
    return files


def run_class(label: str, image: Image.Image, raster: Any, detector: Any, segmenter: Any, tiles: list[Any], vehicle_supported: bool, nms: float) -> dict[str, Any]:
    start=time.perf_counter(); raw: list[Detection]=[]; rejected=[]
    if label == "vehicle" and not vehicle_supported:
        files=[f"{label}_raw_detections.png",f"{label}_filtered_detections.png",f"{label}_segmentations.png"]
        for name in files: render_evidence(image,output_path=OUT/name)
        return {"status":"NEEDS REVIEW","reason":"Vehicle analysis unsupported at this imagery resolution (10 m GSD; vehicles are sub-pixel).","raw_detection_count":0,"filtered_detection_count":0,"merged_count":0,"mask_count":0,"latency_seconds":0,"evidence":files,"qualitative_note":"Evidence is intentionally empty: the source resolution cannot resolve vehicles."}
    for scale, group in (("overview", tiles[:1]), ("medium", tiles[1:])):
        for tile in group:
            crop=image.crop((tile.left,tile.top,tile.right,tile.bottom)); crop.save(TILES/f"{label}_{scale}_{tile.tile_id}.jpg")
            for prompt in CLASSES[label]:
                for d in detector.detect(crop,[prompt]): raw.append(map_detection(d,tile,scale))
    filtered=[]
    for d in raw:
        ok, why=valid(d,image,label)
        if ok: filtered.append(d)
        else: rejected.append({"box":d.box,"tile":d.tile_id,"reason":why,"confidence":d.confidence})
    merged=merge_detections(filtered,iou_threshold=nms)
    masks=[]; mask_records=[]
    # SAM2 operates in source coordinates only after detection has been validated.
    for d in merged[:8]:
        tile=next(t for t in tiles if t.tile_id==d.tile_id); local=d.metadata["tile_box"]
        local_masks=segmenter.segment(image.crop((tile.left,tile.top,tile.right,tile.bottom)),[local])
        for m in local_masks:
            full=np.zeros((image.height,image.width),dtype=bool); full[tile.top:tile.bottom,tile.left:tile.right]=m.mask
            full_m=Segmentation(label,m.confidence,full,m.source,m.model,metadata={"source_detection":d.box,"tile":tile.tile_id,"scale":d.metadata["scale"]}); masks.append(full_m); mask_records.append(measure_mask(full_m,raster))
    raw_file=f"{label}_raw_detections.png"; filtered_file=f"{label}_filtered_detections.png"; seg_file=f"{label}_segmentations.png"
    render_evidence(image,detections=raw,output_path=OUT/raw_file); render_evidence(image,detections=merged,output_path=OUT/filtered_file); render_evidence(image,detections=merged,segmentations=masks,output_path=OUT/seg_file)
    huge=[x for x in mask_records if x["image_fraction"]>.85]
    status="NEEDS REVIEW" if merged else "FAIL"
    if merged and not huge: status="NEEDS REVIEW"  # no EO ground truth: never claim accuracy
    return {"status":status,"prompts":CLASSES[label],"raw_detection_count":len(raw),"raw_detections":[d.__dict__ for d in raw],"rejected_count":len(rejected),"rejected":rejected,"filtered_detection_count":len(filtered),"merged_count":len(merged),"duplicate_merge_count":len(filtered)-len(merged),"merged_detections":[d.__dict__ for d in merged],"sam2_prompt_count":len(merged[:8]),"mask_count":len(masks),"masks":mask_records,"implausibly_large_masks":len(huge),"measurements":measure_detections(merged,raster),"latency_seconds":round(time.perf_counter()-start,3),"evidence":[raw_file,filtered_file,seg_file],"crops":crops(image,merged,masks,label),"qualitative_note":"Inspectable output exists; no labeled EO ground truth, so this is NEEDS REVIEW rather than an accuracy claim."}


def engine(path: Path) -> dict[str, Any]:
    os.environ.setdefault("SATQUERY_DETECTOR_MODEL","IDEA-Research/grounding-dino-tiny"); os.environ.setdefault("SATQUERY_SEGMENTER_MODEL","facebook/sam2.1-hiera-tiny")
    e=SatQueryEngine(Settings.from_env()); out={}
    for q in ("detect buildings","detect roads","detect vehicles","detect water","segment buildings"):
        t=time.perf_counter()
        try: r=e.answer(q,image_paths=[str(path)],include_trace=False); out[q]={"status":"PASS","model":r.results[0].model,"count":len(r.results[0].data.get("detections",r.results[0].data.get("segmentations",[]))),"seconds":round(time.perf_counter()-t,3)}
        except Exception as x: out[q]={"status":"FAIL","error":str(x),"seconds":round(time.perf_counter()-t,3)}
    return out


def main() -> int:
    t=time.perf_counter(); path, src, warnings=source(); image=rgb(path); raster=load_eo_raster(path); meta=metadata(path)
    size=int(os.getenv("SATQUERY_TILE_SIZE","640")); overlap=float(os.getenv("SATQUERY_TILE_OVERLAP","0.2")); maximum=int(os.getenv("SATQUERY_MAX_TILES","6")); threshold=float(os.getenv("SATQUERY_DETECTOR_THRESHOLD","0.25")); nms=float(os.getenv("SATQUERY_NMS_IOU","0.5"))
    tiles=generate_tiles(image.width,image.height,tile_size=size,overlap=overlap)[:maximum]; overview=type(tiles[0])("overview",0,0,image.width,image.height); tiles=[overview,*tiles]
    device=os.getenv("SATQUERY_DEVICE","cpu"); detector=GroundingDinoDetector(device=device,threshold=threshold); segmenter=Sam2Segmenter(device=device)
    report={"test":"stage2_real_eo_tiled_acceptance","timestamp_utc":datetime.now(timezone.utc).isoformat(),"source":{**src,"metadata":meta},"models":{"detector":detector.model_id,"segmenter":segmenter.model_id,"device":device},"tile_configuration":{"tile_size":size,"overlap":overlap,"max_tiles":maximum,"actual_tiles":len(tiles),"scales":["overview","medium"],"detail_scale":os.getenv("SATQUERY_DETAIL_SCALE","not used: 10 m source cannot resolve vehicles"),"detector_threshold":threshold,"nms_iou":nms},"ground_truth":"Not available. This report does not claim accuracy, precision, recall, IoU, or mAP.","warnings":warnings,"classes":{},"errors":[]}
    try:
        for label in CLASSES: report["classes"][label]=run_class(label,image,raster,detector,segmenter,tiles,meta["resolution"] and min(meta["resolution"])<=1.0,nms)
        report["engine"]=engine(path)
    except Exception as exc: report["errors"].append(f"{type(exc).__name__}: {exc}")
    report["total_seconds"]=round(time.perf_counter()-t,3); report["diagnosis"]={"full_image_scale":"Tiled runs are recorded separately from overview output; compare raw_detection_count by tile/scale.","vehicles":"Unsupported at 10 m GSD; no false vehicle claim is made.","giant_boxes":"Rejected for buildings/vehicles and retained diagnostically for road/water.","sam2":"Masks covering >85% of the image are recorded as implausibly large, not proof of useful segmentation.","georeferencing":"Source GeoTIFF CRS/transform are retained; tile boxes are translated back to source pixels before measurement.","domain_limit":"Grounding DINO and SAM2 are general models. EO-specific detector/segmenter, finer imagery, or fine-tuning is required for validated operational results."}
    json_path=REPORTS/"stage2_real_eo_report.json"; json_path.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    rows="".join(f"<tr><td>{k}</td><td>{v['status']}</td><td>{v.get('raw_detection_count')}</td><td>{v.get('merged_count')}</td><td>{v.get('mask_count')}</td><td>{v.get('latency_seconds')}</td></tr>" for k,v in report["classes"].items()); html=f"<h1>Stage 2 Real EO Report</h1><p>No ground truth: qualitative evidence only.</p><pre>{json.dumps(report['source']['metadata'],indent=2)}</pre><table border=1><tr><th>class</th><th>status</th><th>raw</th><th>merged</th><th>masks</th><th>seconds</th></tr>{rows}</table><h2>Evidence</h2>"+"".join(f'<img src="../outputs/{x}" width="480">' for v in report["classes"].values() for x in v.get("evidence",[])); (REPORTS/"stage2_real_eo_report.html").write_text(html,encoding="utf-8")
    for k,v in report["classes"].items(): print(f"{k.upper()}: raw={v.get('raw_detection_count')} merged={v.get('merged_count')} masks={v.get('mask_count')} status={v['status']}")
    print(f"Report: {json_path}"); return 1 if report["errors"] else 0

if __name__ == "__main__": raise SystemExit(main())
