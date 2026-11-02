# Bootstrap and Runtime Sequence

This document describes what starts, in what order, and which state each process owns. The
Platform and SatQuery Engine remain separate services even when run from this repository.
For clean-clone installation and exact integrated startup commands, use the repository's
[authoritative startup guide](INSTALL.md).

## Which process starts first?

For live Engine-backed Platform chat:

1. **SatQuery Engine** starts first. Its FastAPI application initializes its runtime and
   configuration. It exposes the Agent API and owns model selection, tool execution, scientific
   computation, investigations, and evidence.
2. **Platform API** starts next. `create_app()` loads Platform settings; its lifespan configures
   logging, builds the dependency-injection container, opens SQLite, creates the session tables,
   constructs the in-memory Event Bus, and connects to the configured Engine HTTP API.
3. **Platform frontend dev server** starts after the API is reachable. Vite serves React and
   proxies `/api`, `/healthz`, and `/readyz` to the Platform API. The frontend is not a separate
   scientific or execution service.
4. **Browser UI** loads the React application. Cesium's `EarthController` creates the globe in the
   browser. Cesium ion imagery is optional; the UI still starts without an ion token.
5. **Agent execution** starts only after a user submits a chat turn. The Platform sends the text
   turn to the Engine Agent API; the Engine's registered model/Agent runtime performs reasoning
   and tool execution. The Platform does not launch a local model process or agent loop.

The Engine is optional for opening the Platform shell. If it is absent or unconfigured, Platform
liveness remains available and `/readyz` reports `degraded`. Readiness also mirrors the Engine's
own readiness report, which can be degraded when the optional legacy image models have not been
warmed even though Engine API discovery remains reachable. Verify the integration with
`GET /api/v1/intelligence/engine-discovery`. For local development, Engine and Platform both
default to port 8000, so start Engine on 9000 and set
`EARTH_ENGINE__BASE_URL=http://127.0.0.1:9000`. The checked-in Engine does not register an Agent
reasoning adapter by default, so live chat requires an externally supplied Engine adapter.

## Request, tools, evidence, and streaming

```text
Browser chat
  -> Platform API chat route
  -> EngineClient HTTP adapter
  -> Engine Agent API / registered model / Engine tools
  -> Engine evidence and streamed Agent events
  -> Platform persists and publishes the event stream
  -> Browser renders conversation and event state
  -> typed Engine-owned Earth events may update EarthContext and Cesium
```

The Platform's backend consumes Engine SSE events, records them in the SQLite event log, and
publishes them through the in-process Event Bus. The frontend connects to the Platform stream
endpoint and renders those events. The Event Bus is an in-memory, single-process fan-out; it is not
Redis, a separate service, or a multi-worker broker. The durable event log supports Platform
session replay, but does not make the Engine's in-memory Agent sessions durable.

Cesium only renders platform state and supported Engine-provided Earth commands/data. A chat
message or a model sentence is not converted into a scientific result or Earth action by the
Platform.

## Storage initialization and ownership

### Platform

- The default session DSN is `./var/platform.sqlite3`.
- During Platform lifespan startup, `SQLiteSessionStore.open()` creates parent directories and
  executes idempotent `CREATE TABLE IF NOT EXISTS` statements for sessions, conversations, tasks,
  and events. There is no separate database server or manual migration command in this setup.
- Uploaded Vision originals and generated thumbnails are stored under the configured
  `vision.store_path` (default `./var/images`) after upload. The image directory is not populated
  during a clean boot.
- Earth workspace state and UI session references use the Platform session store.
- The default Event Bus is memory-backed and belongs to the Platform API process.

### Engine

- The Engine starts its own application/runtime independently and owns scientific/execution
  stores. Its defaults and optional persistence paths are Engine settings; the Platform does not
  initialize or migrate Engine databases.
- The local Engine configuration may use in-memory state. A container restart does not preserve
  that state unless an Engine persistence configuration and volume are supplied.
- The Engine connector example manifest is not automatically enabled. External connectors and
  data access are opt-in.

## Configuration and secrets

The Platform config loader merges YAML defaults/environment/profile layers and then environment
overrides. `EARTH_ENGINE__KIND=http` selects the HTTP adapter,
`EARTH_ENGINE__BASE_URL` points to Engine, and `EARTH_AGENT__MODEL_ID` names a model already
registered by Engine. A reachable Engine alone does not provide a registered model or provider
credentials.

`VITE_CESIUM_ION_TOKEN` is injected into the frontend build/dev process and is visible in the
browser; it is not a secret. Provider credentials and Engine API keys, when configured, belong in
process environment or a secret manager. Do not put credentials in the frontend.

## Docker Compose boot order

The development Compose stack has three services:

1. `satquery-engine` starts and passes its HTTP health check.
2. `platform-api` waits for Engine health, opens the Platform SQLite store, and starts.
3. `frontend` waits for Platform API health; Vite proxies browser calls to the API service.

The `platform-data` named volume persists Platform SQLite and Vision files. The Compose file is
for local development only: it is not hardened for production, provides no authentication or TLS,
does not configure an Engine model, and does not make the in-memory Engine/Event Bus state
distributed or durable. The Compose Engine health check tests HTTP reachability, not model
registration; with default settings the Engine container is healthy while Platform `/readyz` is
degraded.

## Plugin initialization

The Platform backend defines plugin interfaces and registries but the current application
composition root does not create a concrete plugin host or discover backend plugins at startup.
The frontend registers built-in panels in its React provider layer. Do not describe backend
third-party plugin auto-loading as a boot step until a host is wired into the container.

## Shutdown

Uvicorn's lifespan shutdown closes the Platform Engine HTTP client, Event Bus, and SQLite store.
The frontend dev server and Engine are separate processes and stop independently. In Docker,
`Ctrl+C` stops the Compose stack; `docker compose down` removes containers while leaving the named
Platform data volume intact.
