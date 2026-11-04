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
enabled with platform storage paths. A configured Earth Memory path is used as
the fallback database path for lifecycle, execution, audit, monitoring, and
agent-session stores. SQLite is a single-host persistence option, not a
distributed database.

## Implemented capability boundary

| Area | Implemented and integrated | Important boundary |
|---|---|---|
| Core runtime | Validated configuration, typed contracts with a 64-container-level nesting guard, component registries, async connector lifecycle, bounded DAG execution, cancellation, task retries under explicit safety policy, workflow compiler registry, runtime diagnostics and structured logs. | Connector factories and installed Python extensions execute trusted code in-process. There is no worker queue, sandbox, or distributed scheduler. |
| Earth Perception | Modality-first capability selection, dataset discovery, canonical EarthQuery and observations, provenance, quality records, fusion without invented values, progressive streaming, caching, and capability inspection. Plans retain integrity-checked snapshots of the public capability-selection metadata used for their revision. | Connector manifests must be configured. Declared capability is not live availability. Many modalities and datasets remain uncovered; coverage metadata may be unknown. Snapshot exports deliberately omit raw dataset metadata, asset URIs, and connector source/provider payloads. |
| Current source adapters | Manifest-configurable STAC, NASA Earthdata CMR, NASA POWER daily points, NASA FIRMS, Open-Meteo endpoints with GeoJSON MultiPoint batching, OpenStreetMap/Overpass, USGS 3DEP EPQS, USGS daily discharge, NOAA CO-OPS with read-only station-candidate search, three provider-identifying STAC catalog presets, and the optional Esri point-imagery fetcher. | Adapters remain explicitly opt-in and have restricted query shapes/product coverage; see [supported sources](datasets/SUPPORTED_DATASETS.md). FIRMS requires a NASA MAP_KEY. STAC assets are generally references, not downloaded data; provider STAC presets reuse the common STAC behavior. Station candidates are not acquired observations or coverage claims. |
| Raster operations | Optional Rasterio/PyProj/Shapely support for explicitly requested raster point samples, polygon zonal summaries, and connected-component polygonization of caller-declared categorical codes. | No automatic classification, spectral-index derivation, general reprojection/resampling, mosaicking, or scientifically validated uncertainty propagation. |
| Earth Understanding | Explicit candidate extraction and evidence-backed Earth Object materialization; OSM features, FIRMS detections, NOAA station metadata, and caller-mapped categorical raster components can enter the same canonical object layer. Object revisions, source attributes, relationships, provenance, and extraction batches are inspectable. | Explicit source records are not validated detections or ground truth. No general segmentation, unconstrained entity resolution, inferred lifecycle, or object-level scientific conclusions. |
| Investigation | Deterministic planning, clarification/candidate plans, mission and investigation lifecycle, evidence design, versioned workflow compilation, DAG execution, cancellation, compatible checkpoint resume, replayable live execution-event streaming, reports, and persisted investigation comparisons retrievable by full content digest. | Natural-language parsing is bounded and ontology-driven; it is not an LLM scientist. A ready plan does not guarantee acquisition success or a scientific answer. Comparison alignment is exact-label and method-bounded; descriptive arithmetic is not a scientific conclusion. |
| Reasoning and methods | Evidence coverage diagnostics, hypotheses and lifecycle history, operator/rule registries, method manifests, sufficiency checks, explicit uncertainty inventories, certification ledger, benchmark runner, cited knowledge records, and configuration-only workflow templates. | No bundled domain method is certified to produce scientific conclusions. Reference metadata and passing exact-output replay do not establish scientific validity. No general causal inference or calibrated probability engine is active. |
| Governance | Append-only investigation audit events, method certification transitions, plugin manifest compatibility/signature-verifier interfaces, reference benchmark execution, and versioned reproducibility exports with the capability snapshots used by planning and acquisition. SQLite audit and benchmark inputs can be supplied locally. | No benchmark truth data, external reviewer identity, signed institutional certification, package sandbox, or cryptographic protection against a storage administrator is bundled. Capability snapshots preserve the safe selection view, not raw provider data or acquired source data. |
| Earth Memory | Deterministic artifact indexing and search, source links, Earth Object and observation lineage, capability snapshot artifacts, same-CRS envelope and exact GeoJSON-intersection filters, revision-bound cursors, and optional SQLite schema migrations. | Default memory is process-local. Spatial filters never reproject or repair geometry; exact geometry search requires the optional geospatial dependencies and valid indexed geometry. Semantic embedding search and learning are absent. |
| Continuous observation | Mission-linked recurring EarthQuery schedules, optional rolling windows resolved at persisted run start, durable local leases/events when configured, explicit run-due operation or opt-in local polling, recovery, bounded dispatch, overlap and retry policy, operational trigger rules, local notifications, history pages, and run comparisons. Revising a schedule interval resets its next due time using the new cadence. | Rolling windows cannot be combined with fixed query times; each effective interval is retained in the run and its investigation query. Trigger thresholds are user-authored operational predicates, not validated change detection. No external notifications, exactly-once upstream acquisition, distributed scheduling, or guaranteed provider freshness. |
| Agent interface | Model-neutral streaming reasoning protocol with finite per-round deadlines, explicit typed Earth tool registry and read-only `GET /api/v1/agent/tools` descriptors, conversational tool/observation loop, SQLite or in-memory session state, SSE lifecycle events, cooperative cancellation, session-scoped bounded execution-journal history, and delegation to the existing planner, runtime, evidence, and Earth Memory services. Explicit presentation requests can emit `earth.command` SSE events for `fly_to` and session-linked `show_investigation`. | A compatible cancellation-aware provider adapter must be registered in the reasoner registry. Turn-level execution consent is not authentication. Agent turn SSE replay, user/tenant isolation, and distributed session/event storage are not implemented. Other Earth command types need corresponding Engine-owned data and ownership contracts. |

### Agent Earth command event

The Agent tool registry exposes `earth.command` for presentation-only actions. The provider must
request the tool explicitly; assistant prose and ordinary scientific tool results never produce map
actions. The Engine validates the command and emits the existing Agent event envelope:

```json
{
  "kind": "earth.command",
  "session_id": "agent-session-id",
  "turn_id": "turn-id",
  "sequence": 7,
  "timestamp": "2026-11-02T00:00:00Z",
  "payload": {
    "command": {
      "type": "show_investigation",
      "investigation_id": "investigation-id"
    }
  }
}
```

Currently accepted commands are `fly_to` with a WGS 84 longitude/latitude or bounding box, and
`show_investigation` with an investigation ID already linked to the Agent session. The latter is
checked both by the Engine before emission and by the Platform before it fetches report or map data.
Layer visibility, arbitrary overlays, and evidence highlighting are not exposed through this tool.

### Agent EarthContext input

`POST /api/v1/agent/sessions/{id}/turns` accepts an optional typed `earth_context` alongside the
user message. The bounded contract contains primary and optional secondary viewport dimensions and
WGS 84 camera state, layer visibility state, temporal range/instant/playback, selected entity properties,
user drawings, metadata-only imagery references, active overlay GeoJSON and omissions, evidence
highlights, Engine investigation references, bookmarks, camera history, split-view state, and
measurements. Overlay geometries are validated as WGS 84; the complete serialized EarthContext is
capped at 512 KiB. The Engine validates this payload before starting the turn and presents it to the
reasoning model as untrusted context, not verified evidence, instructions, or scientific conclusions.
It is per-turn scope and is not stored as authoritative Agent transcript state. Image bytes remain
in the separate attachment field.

### Agent image attachments

The same turn endpoint accepts up to eight typed image attachments. Each carries the Platform asset
ID, supported MIME type, byte size, optional dimensions, SHA-256 digest, and strict base64 image
bytes. Per-image size is capped at 20 MiB and aggregate size at 40 MiB. The Engine validates
encoding, MIME signature, declared byte size, and digest before starting a turn. It persists only
attachment references in the user transcript message and passes bytes transiently to the selected
Agent model adapter. Adapters must explicitly set `supports_vision = True`; otherwise the Engine
rejects the request with HTTP 422 before opening the SSE stream. The Platform remains the canonical
image store and must resend bytes for each turn that needs image context. No provider-specific SDK
or request format is included in the Engine core.
| Interfaces | FastAPI/OpenAPI; grouped synchronous Python SDK resources for platform, Earth, agent sessions, missions, investigations, monitoring, objects, memory, and science; CLI commands for planning, observation, investigation, agent sessions/turns, objects (including GeoJSON export), reasoning inspection, memory, science catalogs, monitoring, and runtime; browser workspace exposes mission/investigation state, selected platform records, and an interactive SVG locator view of supported Earth Object geometries. | The client returns raw server JSON and does not negotiate schema versions or retry ambiguous writes. The locator is not a basemap or full GIS; it draws only valid geometries explicitly declared in WGS 84, uses an equirectangular view, and performs no reprojection, geometry repair, or measurement. Authentication, multi-user collaboration, and organization dashboards are absent. |

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

The Earth Memory path is the fallback for local lifecycle, execution, audit,
monitoring, and agent-session SQLite adapters. Set
`storage.agent_sessions_path` to use a separate session database. Separate
paths can be configured when independent files are wanted. See
[setup](development/SETUP.md) for complete examples. Do not commit credentials
or real `.env` files.

## Verification and delivery status

The repository has deterministic unit and integration tests, optional
real-model acceptance tests, connector fixtures, and one GitHub Actions
workflow. CI installs the development and geospatial extras and runs a
selected deterministic regression set on Python 3.12; it is not a deployment
pipeline and does not run provider-backed live acceptance. Raster-specific
tests require the `raster` extra. Hugging Face model acceptance requires model
weights and network access or a populated local cache.

The local regression suite last ran on 2026-11-04 with 559 passed and 2
skipped. The run emitted 5 warnings, including unregistered markers in the
separate `SAT_QUERY` test tree and third-party deprecations.

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
scientific method library. Phase 5 has a model-neutral single-agent interface
around the existing runtime, but no multi-agent execution or collaboration.
Phase 6 has deterministic local Earth Memory but not planetary-scale semantic
retrieval or learning. Phase 7 has local recurring investigations and
operator-authored triggers, not validated autonomous change detection. Phase 8
has local API/CLI/workspace interfaces but lacks production multi-user and
deployment services. Phase 9 has extension contracts and trusted local
registration, not a governed public ecosystem or marketplace.

For system design see [architecture](foundation/SYSTEM_ARCHITECTURE.md) and
[components](architecture/COMPONENTS.md). For exact route behavior see the
[API reference](api/API_REFERENCE.md); for data scope see [supported sources](datasets/SUPPORTED_DATASETS.md).

## Current phase estimates

The goal-relative reassessment dated 2026-11-04 estimates Engine completion at
48% across the ten equally weighted vision phases. These estimates are not
release readiness or test coverage; each phase's missing capabilities and
primary blocker classification are listed in the [master roadmap reassessment](foundation/ROADMAP.md#current-phase-reassessment-2026-11-04).
