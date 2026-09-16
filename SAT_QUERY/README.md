# SatQuery AI

The canonical product is [`satquery-ai`](satquery-ai/). This repository is organized into product, documentation, research, benchmarks, artifacts, and archive areas.

Start with [docs/AI_CONTEXT.md](docs/AI_CONTEXT.md) and [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md). Read product setup and usage in [satquery-ai/README.md](satquery-ai/README.md), and the authoritative baseline in [docs/baseline/BASELINE.md](docs/baseline/BASELINE.md).

Repository areas:

- `satquery-ai/` - active product and tests
- `docs/` - authoritative project documentation
- `research/` - reference-only material
- `benchmarks/` - formal evaluation infrastructure and preserved baseline results
- `configs/` - reproducible configuration
- `artifacts/` - generated reports and outputs
- `archive/` - historical material

Run commands from the canonical package directory:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m satquery doctor
..\.venv\Scripts\python.exe -m satquery warmup
..\.venv\Scripts\python.exe -m satquery serve
```
