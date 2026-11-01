# SatQuery — Earth Intelligence Platform

This repository contains two cooperating applications:

- **SatQuery Engine** (`engine/`) is the scientific and execution service. Its API owns
  investigations, evidence, data connectors, reasoning execution, and the Engine Agent API.
- **Earth Intelligence Platform** (`APP/`) is the user-facing workspace. It provides chat UX,
  sessions, image intake, streaming presentation, and Cesium visualization. It delegates turns
  to the Engine and does not reproduce Engine science or execution.

The Engine can run on its own. For live Platform chat, the Engine must be reachable and have a
compatible reasoning model registered. The checked-in default configuration does not supply
provider credentials or a model adapter.

## Quick Start (5–10 minutes)

The development Docker Compose stack starts the Engine, Platform API, and Vite frontend:

```bash
docker compose up --build
```

Open <http://localhost:5173>. Platform liveness is at <http://localhost:8000/healthz>;
readiness is at <http://localhost:8000/readyz>. With the default configuration, readiness is
degraded: the Engine process is reachable, but no reasoning model/provider is registered.
Cesium's default imagery requires an optional scoped Cesium ion token; without one, the globe still
opens without the default imagery layer. Chat requires an Engine model adapter and registered
model ID; starting the stack does not invent or configure one.

Stop with `Ctrl+C`; `docker compose down` stops and removes the containers. The named
`platform-data` volume holds Platform SQLite session data and uploaded Vision assets. The Engine
uses its configured storage defaults; see [BOOTSTRAP.md](BOOTSTRAP.md) and
[INSTALL.md](INSTALL.md) for runtime and persistence boundaries.

## Local development

See [INSTALL.md](INSTALL.md) for Windows, Linux, macOS, and Colab prerequisites and setup.
[DEVELOPMENT.md](DEVELOPMENT.md) covers tests, contracts, builds, and source layout. The
[boot sequence](BOOTSTRAP.md) explains process startup, SQLite, event delivery, SSE, Cesium, and
the Engine boundary.

## CI

- [Earth Intelligence Platform workflow](.github/workflows/platform-ci.yml): Platform backend,
  frontend, contract, and architecture checks.
- [Platform regressions workflow](.github/workflows/platform-tests.yml): deterministic Engine
  tests, including optional geospatial and raster extras.

Python dependency manifests specify compatible version ranges rather than a cross-platform lock
file. The frontend is locked by `APP/frontend/package-lock.json` and must be installed with
`npm ci`. Consequently, a fresh Python install is functionally reproducible but not guaranteed to
resolve byte-for-byte identical Python package versions over time; see the dependency audit in
[INSTALL.md](INSTALL.md).
