# SatQuery Phase 0 Baseline Benchmark

This directory defines the reproducible benchmark surface for the current reference system. It does not claim calibrated task accuracy because the checked-in real images have no ground-truth labels, boxes, masks, or temporal annotations.

## Contents

- `manifest.json`: fixed local fixture inventory, hashes, provenance status, and task eligibility.
- `queries/core.json`: versioned natural-language smoke queries.
- `ground_truth/`: ground-truth status and schema notes.
- `run_benchmark.py`: runs real-model queries and writes JSONL results plus summary metrics.
- `results/`: machine-readable run outputs.
- `metrics/`: metric definitions and interpretation.
- `reports/`: human-readable run reports.

## Run

From `satquery-ai`:

```powershell
..\..\.venv\Scripts\python.exe ..\benchmarks\baseline\run_benchmark.py --profile fast
```

For the quality profile, use `--profile quality`; CPU grounding is substantially slower. The runner warms the same engine process used for the queries, records cold warmup time and warm query latency, and writes timestamped files below `benchmarks/baseline/results/`.

## Interpretation

The current fixture set is an acceptance/smoke set, not a scientific benchmark. It supports qualitative review and runtime measurement only. Classification accuracy, VQA correctness, grounding IoU, counting error, change F1, and modality accuracy remain `not_evaluable` until labeled data and provenance are added.

The seven files currently under `satquery-ai/data/fetched_images` were fetched by the optional Esri/Nominatim/Photon plugin or are duplicate outputs. Their filenames and hashes are recorded; exact provider response metadata is not stored by the current application.
