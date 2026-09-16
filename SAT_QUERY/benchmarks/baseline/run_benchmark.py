r"""Run the Phase 0 real-model smoke benchmark.

Run from satquery-ai:
    ..\..\.venv\Scripts\python.exe ..\benchmarks\baseline\run_benchmark.py --profile fast

The runner intentionally reports runtime and structured predictions only. The
checked-in fixture set has no ground truth, so it does not invent accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "satquery-ai"
BASELINE_ROOT = REPOSITORY_ROOT / "benchmarks" / "baseline"
FIXTURE_ROOT = PACKAGE_ROOT / "data" / "fetched_images"
QUERY_FILE = BASELINE_ROOT / "queries" / "core.json"

sys.path.insert(0, str(PACKAGE_ROOT))


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _failure_category(exc: Exception) -> str:
    code = getattr(exc, "code", "")
    if code in {"image_error", "image_not_found"}:
        return "INVALID_INPUT"
    if code in {"resource_not_configured", "dependency_missing", "model_load_error"}:
        return "MODEL_UNAVAILABLE"
    if code == "query_error":
        return "QUERY_MISMATCH"
    if code == "tool_execution_error":
        return "INTERNAL_ERROR"
    return "INTERNAL_ERROR"


def _environment(settings: Any) -> Dict[str, Any]:
    import importlib.metadata as metadata

    versions: Dict[str, str | None] = {}
    for distribution in ("torch", "transformers", "fastapi", "pydantic", "numpy", "Pillow", "httpx"):
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = None
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "device": settings.device,
        "profile": settings.profile,
        "versions": versions,
    }


def _sample_files(all_samples: bool) -> List[Path]:
    candidates = sorted(FIXTURE_ROOT.glob("*.jpg")) + sorted(FIXTURE_ROOT.glob("*.png"))
    unique: List[Path] = []
    seen: set[str] = set()
    for path in candidates:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(path)
    return unique if all_samples else unique[:1]


def _compact_response(response: Any) -> Dict[str, Any]:
    result = response.results[0] if response.results else None
    return {
        "answer": response.answer,
        "intent": response.intent.value,
        "tools_used": [tool.value for tool in response.tools_used],
        "backend": response.backend.value,
        "confidence": response.confidence,
        "warnings": response.warnings,
        "region_count": len(result.regions) if result else 0,
        "top_labels": [label.model_dump(mode="json") for label in result.labels[:5]] if result else [],
        "tool_data_keys": sorted(result.data.keys()) if result else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SatQuery Phase 0 baseline queries.")
    parser.add_argument("--profile", choices=("fast", "quality"), default="fast")
    parser.add_argument("--all-samples", action="store_true", help="Run the query set on every unique fixture.")
    parser.add_argument("--repeat", type=int, default=1, help="Warm repetitions per sample/query.")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    os.environ["SATQUERY_PROFILE"] = args.profile
    # Make the benchmark profile reproducible even when the user's .env pins
    # the quality model explicitly.
    if args.profile == "fast":
        os.environ["SATQUERY_CLIP_MODEL"] = "openai/clip-vit-base-patch32"
        os.environ["SATQUERY_GROUNDING_SCALES"] = "0.5"
        os.environ["SATQUERY_GROUNDING_MAX_WINDOWS"] = "16"
        os.environ["SATQUERY_GROUNDING_STRIDE_RATIO"] = "0.9"
    else:
        os.environ["SATQUERY_CLIP_MODEL"] = "openai/clip-vit-large-patch14"
    from satquery.config import Settings
    from satquery.orchestrator import SatQueryEngine

    settings = Settings.from_env()
    engine = SatQueryEngine(settings)
    started = time.perf_counter()
    warmup = engine.warmup()
    warmup_seconds = round(time.perf_counter() - started, 3)
    queries = json.loads(QUERY_FILE.read_text(encoding="utf-8"))["queries"]
    samples = _sample_files(args.all_samples)
    if not samples:
        raise SystemExit(f"No image fixtures found under {FIXTURE_ROOT}")

    run_id = _timestamp()
    output_dir = BASELINE_ROOT / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / f"{run_id}.jsonl"
    summary_path = output_dir / f"{run_id}.summary.json"
    records: List[Dict[str, Any]] = []

    for sample in samples:
        for query_spec in queries:
            for repetition in range(args.repeat):
                started = time.perf_counter()
                record: Dict[str, Any] = {
                    "run_id": run_id,
                    "sample_id": sample.name,
                    "task": query_spec["task"],
                    "query_id": query_spec["id"],
                    "query": query_spec["query"],
                    "model": {
                        "caption": settings.caption_model,
                        "vqa": settings.vqa_model,
                        "clip": settings.clip_model,
                    },
                    "input": {"path": str(sample), "sha256": hashlib.sha256(sample.read_bytes()).hexdigest()},
                    "ground_truth": None,
                    "metrics": {"accuracy": "not_evaluable", "iou": "not_evaluable"},
                    "confidence": None,
                    "warnings": [],
                    "failure_category": None,
                    "latency_ms": None,
                    "repetition": repetition + 1,
                    "environment": _environment(settings),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    response = engine.answer(query_spec["query"], image_paths=[str(sample)], include_trace=True)
                    record["prediction"] = _compact_response(response)
                    record["confidence"] = response.confidence
                    record["warnings"] = response.warnings
                except Exception as exc:
                    record["prediction"] = None
                    record["failure_category"] = _failure_category(exc)
                    record["warnings"] = list(getattr(exc, "remediation", []))
                    record["error"] = str(exc)
                record["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
                records.append(record)

    jsonl_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    successful = [record for record in records if record["failure_category"] is None]
    latencies = sorted(record["latency_ms"] for record in successful if record["latency_ms"] is not None)
    median = latencies[len(latencies) // 2] if latencies else None
    summary = {
        "schema_version": "0.1",
        "run_id": run_id,
        "profile": args.profile,
        "samples": [sample.name for sample in samples],
        "query_count": len(records),
        "successful_queries": len(successful),
        "failed_queries": len(records) - len(successful),
        "warmup": warmup,
        "warmup_seconds": warmup_seconds,
        "warm_query_latency_ms": {"median": median, "min": min(latencies) if latencies else None, "max": max(latencies) if latencies else None},
        "accuracy_metrics": "not_evaluable_without_ground_truth",
        "results_file": str(jsonl_path.relative_to(PACKAGE_ROOT.parent)),
        "environment": _environment(settings),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if warmup.get("ready") and not warmup.get("errors") and not summary["failed_queries"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
