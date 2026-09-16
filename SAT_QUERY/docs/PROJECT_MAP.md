# Project Map

| Directory | Purpose | Belongs here | Does not belong here | AI normally reads? |
|---|---|---|---|---|
| `satquery-ai/` | Product | Python package, tests, runtime fixtures, package config | Research papers, old reports, generated run archives | Yes |
| `docs/` | Authoritative documentation | Architecture, baseline, development plans, AI context | Raw research and generated outputs | Yes, selectively |
| `research/` | External/reference knowledge | Open-source inventory, papers, dataset/model notes | Runtime imports and product code | Only when relevant |
| `benchmarks/` | Formal evaluation | Baseline manifests, queries, runners, metrics, preserved results | Ad hoc experiments and caches | When benchmarking |
| `configs/` | Reproducible configuration | Baseline and future experiment configs | Secrets and generated state | When configuration matters |
| `satquery-ai/satquery/eo/` | EO foundation | Metadata, STAC discovery, raster math, spectral indices | VLM prompting and UI code | Yes for EO tasks |
| `artifacts/` | Generated outputs | Phase reports, predictions, logs, temporary outputs | Source code and benchmark definitions | Usually no |
| `archive/` | Preserved historical material | Legacy modules and superseded audits | Active implementation | Usually no |
| `experiments/` | Experimental work | Future prototypes, notebooks, model trials, experiment outputs | Product code and formal baseline results | Only for experiment tasks |

## Canonical paths

- Product: `satquery-ai/satquery`
- Tests: `satquery-ai/tests`
- Phase 0 baseline: `benchmarks/baseline` and `docs/baseline/BASELINE.md`
- Phase 1 generated reports: `artifacts/reports/phase1`
- Research inventory: `research/open_source/OPEN_SOURCE_STACK.md`
