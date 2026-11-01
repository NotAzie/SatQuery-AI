# Earth Intelligence Platform

> ChatGPT with direct access to the Earth.

The Platform is the application users experience: natural-language conversation, image
understanding and a live 3D globe that reacts to every question. It sits **entirely on top of
SatQuery Engine**, which is finished, frozen, and treated like a database engine: the Platform calls
it and never reimplements, patches or duplicates it.

```
User ─▶ Platform UI/API ─▶ Platform AgentRuntime ─▶ SatQuery Engine Agent API
                                                     ├─▶ registered reasoning model
                                                     └─▶ Engine tools and scientific runtime
```

The Platform delegates turns to the Engine's existing Agent Interface. The Engine-registered model
handles language reasoning and invokes Engine tools; all scientific execution and evidence remain
Engine-owned. The Platform persists UI events and visualizes results without recalculating science.
This separation is the project's central rule (see
[ADR 0002](docs/adr/0002-llm-thinks-engine-executes.md)).

## Status

The Phase 2 text-chat vertical slice is implemented against SatQuery Engine's existing Agent API.
The Platform links sessions to Engine Agent sessions, streams and persists Engine events, and
restores the Engine-owned transcript in the floating chat UI. The Earth Workspace foundation and
Platform-owned Vision ingestion/preparation are implemented; Engine-backed investigation overlays
and multimodal chat remain blocked by missing Engine event/request contracts. The Platform does not
run a model/tool loop or duplicate scientific capabilities.

| Area | State |
|---|---|
| Backend app factory, config layering, DI container, health/readiness | working |
| Engine Agent API integration | HTTP adapter for sessions, turns, cancellation, and SSE; mock-transport contract tests |
| Agent runtime | Platform session/event bridge to Engine-owned model and tool loop |
| Reasoning model and tool execution | Owned by SatQuery Engine; configure a registered Engine `model_id` |
| Vision intake, storage, metadata, neutral preparation | implemented; chat delivery blocked by the Engine's text-only Agent request |
| LLM provider adapters, backend plugin host | interfaces; Engine owns the model execution and the backend host is not wired |
| Platform sessions | SQLite metadata/event log; Engine Agent transcript remains authoritative for chat |
| Event delivery | Durable event log + single-process live fan-out + resumable SSE and chat-turn streams |
| Wire contracts (events, Earth commands, messages) | defined, exported, TypeScript generated |
| Frontend shell, routing, state, Cesium viewer, camera, capture | working foundation |
| Earth command dispatcher | Typed event dispatcher implemented; Engine command-event source not yet available |
| Frontend session UI | working sidebar backed by session REST routes |
| Frontend chat UI | Engine transcript, streamed assistant text, tool/progress status, execution-consent checkbox |
| Frontend camera history, bookmarks, selection, drawings, measurements, timeline, split view | implemented as presentation state |
| Engine-backed investigation overlays and layer catalogue | blocked on Engine event/data contracts |

Read [implementation status](docs/implementation-status.md) for phase completion and gaps, and the
[roadmap](docs/roadmap.md) for Phase 3 scope. Phase 2 integration and deployment requirements are
tracked in [Phase 2 Agent Runtime](docs/phase-2-agent-runtime.md). The Engine must be reachable and
have a compatible reasoning model registered before live chat can run.

## Repository layout

```
earth-platform/
├── backend/            FastAPI app: one package, layered modules (see docs/modules.md)
│   ├── src/earth_platform/{shared,settings,engine,llm,vision,earth,sessions,agent,plugins,streaming,api}
│   └── tests/{unit,integration,contract,architecture}
├── frontend/           React + TypeScript + Vite + Tailwind + CesiumJS
│   └── src/{app,earth,features,components,hooks,services,state,plugins,shared,styles}
├── contracts/          Generated JSON Schema: single source of truth for wire types
├── config/             Layered YAML: base, providers, environments, profiles
├── plugins/            First-party / example plugin packages
├── scripts/            Tooling (contract export)
├── tests/e2e/          Cross-stack tests
└── docs/               Architecture, modules, dependency graph, protocols, ADRs
```

Why not top-level `agent/`, `llm/`, `providers/`…? Those are modules of one backend and ship
together; separate top-level packages would add packaging and versioning cost with no isolation
benefit. Isolation is enforced instead by an import-linter contract that fails CI on an upward
import. "Providers" is the LLM provider abstraction and lives in `llm/`; React context providers live
in `frontend/src/app/providers.tsx`.

## Quick start

See the repository-level [Quick Start](../README.md#quick-start-5-10-minutes) and
[installation guide](../INSTALL.md) for Windows, Linux, macOS, Docker, and Colab. The Platform
requires Python 3.12+ and Node 22; frontend dependencies are locked in `frontend/package-lock.json`.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e "backend[dev]"
cd frontend && npm ci
```

On Windows, invoke `.venv\Scripts\python.exe` instead of `.venv/bin/python`. Start the Engine on
port 9000, configure `EARTH_ENGINE__BASE_URL`, then run the backend from this directory and the
frontend from `frontend/`; exact commands are in [INSTALL.md](../INSTALL.md). `/readyz` reports
`degraded` when Engine is unconfigured or unavailable. Without `VITE_CESIUM_ION_TOKEN`, the globe
starts without default Cesium imagery.

Common tasks: `make check` (lint, types, layering, tests), `make contracts` (regenerate wire types
after changing a backend model). These Make targets are optional conveniences; the Python/npm
commands are documented in [DEVELOPMENT.md](../DEVELOPMENT.md).

## Documentation

- [Architecture overview](docs/architecture.md)
- [Module overview](docs/modules.md) and per-folder `README.md` files (purpose, boundaries, dependencies, public interface)
- [Dependency graph](docs/dependency-graph.md)
- [Event protocol](docs/event-protocol.md)
- [Plugins](docs/plugins.md)
- [Configuration](docs/configuration.md)
- [Phase 2 Agent Runtime](docs/phase-2-agent-runtime.md)
- [Implementation status](docs/implementation-status.md)
- [Roadmap](docs/roadmap.md)
- [Getting started](docs/getting-started.md)
- [Architecture decision records](docs/adr)

## License

Not yet chosen. Add a `LICENSE` file before the first public release.
