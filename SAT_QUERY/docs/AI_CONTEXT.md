# SatQuery AI Context

- **Purpose:** RGB satellite/aerial image question answering with routed captioning, VQA, scene classification, semantic grounding, counting, modality heuristics, and two-image change analysis.
- **Stage:** Phase 0 baseline complete; Phase 1/2 implementation exists; current work is repository organization before the next stage.
- **Product source:** `satquery-ai/satquery/`
- **Product tests:** `satquery-ai/tests/`
- **Essential docs:** `satquery-ai/README.md`, `docs/baseline/BASELINE.md`, `docs/development/PHASE1_TEST_PLAN.md`
- **Architecture entry point:** `satquery-ai/satquery/orchestrator.py`; API in `satquery-ai/satquery/api.py`; CLI in `satquery-ai/satquery/__main__.py`.
- **Formal benchmarks:** `benchmarks/`; Phase 0 results are authoritative and must not be rewritten.
- **Research:** `research/`; external projects/models/datasets only.
- **Experiments:** `experiments/` when created; prototypes and notebooks do not belong in product source.
- **Archive:** `archive/`; historical code and superseded reports only.
- **Rules:** preserve `v0.1-baseline`; inspect current code before editing; keep product source/tests/configs focused; verify licenses before reuse; do not claim unmeasured accuracy; use the canonical package path.
- **Normally do not scan:** `archive/`, `artifacts/`, model caches, virtual environments, `__pycache__/`, `.pytest_cache/`, and large runtime image collections unless the task explicitly concerns them.
