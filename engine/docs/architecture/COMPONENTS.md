# Subsystem guide

This map follows the checked-in application under `satquery-ai/satquery`.
Components are composed by the application and `PlatformRuntime`; their
contracts do not imply that every capability is production deployed. See
[current implementation status](../IMPLEMENTATION_STATUS.md).

## Application and interfaces

| Location | Responsibility |
|---|---|
| `satquery/api.py` | FastAPI routes, request validation, runtime-backed operations, and compatibility image/query endpoints. |
| `satquery/ui.py` | Browser workspace served by the application. It exposes platform operations and selected records; it is not a full GIS client. |
| `satquery/__main__.py` | `satquery` command tree and HTTP-backed platform CLI. |
| `satquery/connector_bootstrap.py` | Loads configured connector manifests and constructs registered connector types. |
| `satquery/application.py`, `satquery/orchestrator.py` | Application composition and compatibility between the original query task and platform runtime. |

## Platform packages

| Module | Responsibility |
|---|---|
| `platform/contracts.py` | Canonical EarthQuery, observation, measurement, provenance, capability, mission, investigation, Earth Object, evidence, and execution contracts. |
| `platform/config.py` | Validated platform settings, local/development/testing/production profiles, environment overrides, and storage locations. Profiles do not deploy infrastructure. |
| `platform/registry.py`, `platform/modalities.py`, `platform/datasets.py`, `platform/capabilities.py` | Modality, dataset, method, operator, handler, and capability discovery and selection. |
| `platform/connectors.py`, `platform/perception.py`, `platform/normalization.py`, `platform/fusion.py`, `platform/quality.py` | Connector lifecycle, observation routing, canonicalization, source-aware fusion, and quality records. |
| `platform/spatial.py`, `platform/spatiotemporal.py`, `platform/temporal.py`, `platform/raster*.py`, `platform/assets.py` | Explicit spatial/temporal utilities, optional raster processing, and source asset references. Processing is bounded by current documented operations. |
| `platform/planning.py`, `platform/intelligence.py`, `platform/investigations.py`, `platform/workflows.py` | Deterministic intent planning, evidence requirements, investigation lifecycle, workflow compilation, and DAG orchestration. |
| `platform/earth_objects.py`, `platform/observation_graph.py` | Canonical Earth Object model/materialization and explicit evidence/observation relationships. |
| `platform/reasoning.py`, `platform/scientific_inference.py`, `platform/scientific_methods.py`, `platform/scientific_knowledge.py`, `platform/scientific_library.py`, `platform/scientific_governance.py`, `platform/method_readiness.py` | Diagnostic operators, rule/method registries, knowledge records, preflight, benchmark/certification governance, and conservative inference bookkeeping. No bundled scientific method is certified for general conclusions. |
| `platform/earth_memory.py`, `platform/execution_journal.py` | Deterministic artifact search and lineage, plus optional SQLite execution checkpoints/event history. |
| `platform/monitoring.py`, monitoring methods in `runtime.py` | Mission-linked recurring runs, trigger/event history, local dispatch/recovery, and operational monitoring policies. |
| `platform/reports.py`, `platform/comparisons.py`, `platform/observability.py`, `platform/cache.py` | Reproducibility/report serialization, deterministic investigation comparison, structured diagnostics, and cache abstractions. |
| `platform/models.py`, `platform/tools.py` | Provider-neutral model and tool interfaces. They do not imply an active LLM reasoning service. |

## Data adapters

The connector package contains STAC, NASA Earthdata CMR, NASA POWER, NASA
FIRMS, Open-Meteo, OpenStreetMap, USGS 3DEP, USGS Water, NOAA CO-OPS, and the
optional Esri imagery fetcher. These implementations, including the named
STAC catalog presets, are available through explicit manifest factories; they
are not automatically enabled. Each adapter has narrower product/query
coverage than its provider's full catalog. Configuration and known limits are
documented under [`../datasets/`](../datasets/SUPPORTED_DATASETS.md).

## Tests and configuration

The outer `tests/` directory contains contract, adapter, planning, perception,
execution, memory, monitoring, API, and optional model acceptance tests.
`configs/connectors.example.json` is an opt-in manifest, not an automatically
loaded default. Detailed commands are in the [testing guide](../testing/TESTING_GUIDE.md)
and [setup guide](../development/SETUP.md).
