# `earth_platform/engine`

**Purpose.** The single seam to SatQuery Engine. The Engine is frozen; this module adapts to it and never reimplements it.

**Belongs here**
- `EngineClient` Protocol and the thin Platform-side models crossing the boundary
- HTTP adapter for the Engine's published Agent session/turn/cancel/tool-descriptor API, typed per-turn
  viewport/workspace EarthContext and bounded image attachments, and session-scoped investigation
  report and Earth Object GeoJSON reads, plus mission, monitoring schedule/run/comparison, trigger,
notification, revision-checked schedule update, registered dataset, image-analysis capability API,
and versioned Earth capability snapshot
- `UnavailableEngineClient`, the explicit not-configured null object

**Never here**
- Science, geometry, indexing or evidence computation
- Caching or reinterpretation of Engine results
- Engine types leaking out of this module: adapters map them to `engine.models`

**Depends on.** `settings`, `shared`.

**Public interface.** `EngineClient` (health, Agent session operations, streamed turns with typed
`EngineEarthContext` containing the bounded visible workspace snapshot and `EngineAgentImage`
attachments, cancellation, investigation reports, Earth Object GeoJSON, typed mission and
monitoring operations, registered dataset/image-analysis capability discovery, and the
versioned Earth modality snapshot and Agent tool descriptors), `build_engine_client`, and Engine boundary
models. Agent tool schemas come only from the Engine's registered Agent tool allowlist.
