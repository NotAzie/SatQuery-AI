# Current implementation status

This is the repository-grounded status reference for SatQuery. It describes
capabilities present in the checked-in code and distinguishes them from the
long-term direction in the [roadmap](foundation/ROADMAP.md). It is not a
release certification. Update this document when a capability's runtime
boundary changes.

## What SatQuery runs today

SatQuery has one FastAPI application, one browser workspace, and one CLI. The
Earth Intelligence platform runtime is the main path for missions,
investigations, perception, Earth Objects, evidence, reports, memory,
governance, and monitoring. The earlier image question-answering capability
remains available through its API and CLI as one image-perception task; it is
not the general Earth observation engine.

Start it from `satquery-ai/` with `python -m satquery serve`. The service binds
to `127.0.0.1:8000` by default. Connector manifests are opt-in; the example
manifest is `configs/connectors.example.json`. A manifest selects only
registered local connector factories and does not guarantee provider access,
dataset availability, licensing, or coverage.

The default platform stores are in memory. Local SQLite durability can be
enabled with platform storage paths. A single configured Earth Memory path is
used as the fallback database path for lifecycle, execution, audit, and
monitoring stores. SQLite is a single-host persistence option, not a
distributed database.

## Implemented capability boundary

| Area | Implemented and integrated | Important boundary |
|---|---|---|
| Core runtime | Validated configuration, typed contracts, component registries, async connector lifecycle, bounded DAG execution, cancellation, task retries under explicit safety policy, workflow compiler registry, runtime diagnostics and structured logs. | Connector factories and installed Python extensions execute trusted code in-process. There is no worker queue, sandbox, or distributed scheduler. |
| Earth Perception | Modality-first capability selection, dataset discovery, canonical EarthQuery and observations, provenance, quality records, fusion without invented values, progressive streaming, caching, and capability inspection. | Connector manifests must be configured. Declared capability is not live availability. Many modalities and datasets remain uncovered; coverage metadata may be unknown. |
| Current source adapters | STAC, NASA Earthdata CMR, NASA POWER daily points, NASA FIRMS, Open-Meteo endpoints, OpenStreetMap/Overpass, USGS 3DEP EPQS, USGS daily discharge, NOAA CO-OPS, and the optional Esri imagery fetcher. | Each adapter has restricted query shapes and product coverage; see [supported sources](datasets/SUPPORTED_DATASETS.md). FIRMS requires a NASA MAP_KEY. STAC assets are generally references, not downloaded data. |
| Raster operations | Optional Rasterio/PyProj/Shapely support for explicitly requested raster point samples, polygon zonal summaries, and connected-component polygonization of caller-declared categorical codes. | No automatic classification, spectral-index derivation, general reprojection/resampling, mosaicking, or scientifically validated uncertainty propagation. |
| Earth Understanding | Explicit candidate extraction and evidence-backed Earth Object materialization; OSM features, FIRMS detections, NOAA station metadata, and caller-mapped categorical raster components can enter the same canonical object layer. Object revisions, source attributes, relationships, provenance, and extraction batches are inspectable. | Explicit source records are not validated detections or ground truth. No general segmentation, unconstrained entity resolution, inferred lifecycle, or object-level scientific conclusions. |
| Investigation | Deterministic planning, clarification/candidate plans, mission and investigation lifecycle, evidence design, versioned workflow compilation, DAG execution, cancellation, compatible checkpoint resume, reports, and investigation comparison. | Natural-language parsing is bounded and ontology-driven; it is not an LLM scientist. A ready plan does not guarantee acquisition success or a scientific answer. |
| Reasoning and methods | Evidence coverage diagnostics, hypotheses and lifecycle history, operator/rule registries, method manifests, sufficiency checks, explicit uncertainty inventories, certification ledger, benchmark runner, cited knowledge records, and configuration-only workflow templates. | No bundled domain method is certified to produce scientific conclusions. Reference metadata and passing exact-output replay do not establish scientific validity. No general causal inference or calibrated probability engine is active. |
| Governance | Append-only investigation audit events, method certification transitions, plugin manifest compatibility/signature-verifier interfaces, reference benchmark execution, and versioned reproducibility exports. SQLite audit and benchmark inputs can be supplied locally. | No benchmark truth data, external reviewer identity, signed institutional certification, package sandbox, or cryptographic protection against a storage administrator is bundled. |
| Earth Memory | Deterministic artifact indexing and search, source links, Earth Object and observation lineage, spatial-envelope/time filters, revision-bound cursors, and optional SQLite schema migrations. | Default memory is process-local. Spatial queries are same-CRS envelope overlaps; no reprojection, exact geometry predicate, semantic embedding search, or learning is performed. |
| Continuous observation | Mission-linked recurring EarthQuery schedules, durable local leases/events when configured, explicit run-due operation or opt-in local polling, recovery, bounded dispatch, overlap and retry policy, operational trigger rules, local notifications, history pages, and run comparisons. | Trigger thresholds are user-authored operational predicates, not validated change detection. No external notifications, exactly-once upstream acquisition, distributed scheduling, or guaranteed provider freshness. |
| Interfaces | FastAPI/OpenAPI, grouped synchronous Python SDK resources for platform, Earth, missions, investigations, monitoring, objects, memory, and science; CLI commands for planning, observation, investigation, objects, reasoning inspection, memory, science catalogs, monitoring, and runtime; browser workspace exposes mission/investigation state and selected platform records. | The client returns raw server JSON and does not negotiate schema versions or retry ambiguous writes. The workspace is a local operations console, not a production multi-user GIS, interactive map, or organization dashboard. |

## Persistence and configuration

`SATQUERY_PLATFORM_CONFIG` selects a JSON platform configuration file.
`SATQUERY_PLATFORM_PROFILE` selects `local`, `development`, `testing`, or
`production`; these names adjust configuration defaults and do not provision
deployment infrastructure. `SATQUERY_PLATFORM__<SECTION>__<FIELD>` supplies
validated platform overrides. From the repository root, for example in
PowerShell:

```powershell
$env:SATQUERY_PLATFORM__STORAGE__EARTH_MEMORY_PATH = ".\data\satquery.sqlite"
$env:SATQUERY_CONNECTORS_CONFIG = ".\configs\connectors.example.json"
```

The Earth Memory path is the fallback for the local lifecycle, execution,
audit, and monitoring SQLite adapters. Separate paths can be configured when
independent files are wanted. See [setup](development/SETUP.md) for complete
examples. Do not commit credentials or real `.env` files.

## Verification and delivery status

The repository has deterministic unit and integration tests, optional
real-model acceptance tests, connector fixtures, and one GitHub Actions
workflow. CI installs the development and geospatial extras and runs a
selected deterministic regression set on Python 3.12; it is not a deployment
pipeline and does not run provider-backed live acceptance. Raster-specific
tests require the `raster` extra. Hugging Face model acceptance requires model
weights and network access or a populated local cache.

The `deployment/` directory contains no container, Kubernetes, Terraform, or
production service configuration. There is no production authentication,
authorization, tenant isolation, secret manager, backup/restore procedure, or
availability commitment. Keep the local service on loopback unless it is
placed behind owner-configured authentication and network controls.

## Roadmap status at a glance

The roadmap is a capability direction, not a claim that all listed objectives
are implemented. Phases 0–3 have substantial working local paths but retain
coverage, availability, durability, and scale limits. Phase 4 has conservative
reasoning infrastructure but lacks a populated, independently validated
scientific method library. Phase 5 has no multi-agent execution runtime. Phase
6 has deterministic local Earth Memory but not planetary-scale semantic
retrieval or learning. Phase 7 has local recurring investigations and
operator-authored triggers, not validated autonomous change detection. Phase 8
has local API/CLI/workspace interfaces but lacks production multi-user and
deployment services. Phase 9 has extension contracts and trusted local
registration, not a governed public ecosystem or marketplace.

For system design see [architecture](foundation/SYSTEM_ARCHITECTURE.md) and
[components](architecture/COMPONENTS.md). For exact route behavior see the
[API reference](api/API_REFERENCE.md); for data scope see [supported sources](datasets/SUPPORTED_DATASETS.md).
