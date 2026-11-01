# `earth_platform/engine`

**Purpose.** The single seam to SatQuery Engine. The Engine is frozen; this module adapts to it and never reimplements it.

**Belongs here**
- `EngineClient` Protocol and the thin Platform-side models crossing the boundary
- HTTP adapter for the Engine's published Agent session/turn/cancel API
- `UnavailableEngineClient`, the explicit not-configured null object

**Never here**
- Science, geometry, indexing or evidence computation
- Caching or reinterpretation of Engine results
- Engine types leaking out of this module: adapters map them to `engine.models`

**Depends on.** `settings`, `shared`.

**Public interface.** `EngineClient` (health, Agent session operations, streamed turns, and
cancellation), `build_engine_client`, and opaque `EngineAgentEvent` / `EngineAgentSession` models.
