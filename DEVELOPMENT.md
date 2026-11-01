# Development Guide

## Project layout

```text
.
├── APP/                         Earth Intelligence Platform
│   ├── backend/src/earth_platform/  FastAPI, Engine adapter, SQLite, SSE, Vision, Intelligence
│   ├── frontend/src/                React, TypeScript, Cesium, UI state
│   ├── contracts/                   Shared generated JSON Schema
│   ├── config/                      Layered YAML configuration
│   ├── scripts/export_contracts.py  Pydantic-to-JSON-Schema exporter
│   └── docs/                        Platform architecture, status, and roadmap
├── engine/
│   ├── satquery-ai/                 SatQuery Engine Python package
│   ├── tests/                       Engine unit/integration/regression tests
│   ├── configs/                     Example connector/catalog configuration
│   └── docs/                        Engine documentation
├── docker/                          Development Dockerfiles
├── docker-compose.yml               Development-only three-service stack
└── .github/workflows/               Root GitHub Actions workflows
```

The Platform is not a second Engine. Its backend's `EngineClient` communicates with the Engine
Agent HTTP API. Scientific/data execution and evidence are Engine-owned.

The Phase 6 `intelligence/` layer assembles Platform-owned Earth/conversation context, retrieves
existing workspace records, reports registered capabilities, and plans requests before chat turns.
It does not call providers or execute Engine tools. See
[Platform architecture](APP/docs/architecture.md), [roadmap](APP/docs/roadmap.md), and
[implementation status](APP/docs/implementation-status.md) for the exact text-only and discovery
boundaries.

## Development setup

Follow [INSTALL.md](INSTALL.md) for clean installs and OS-specific commands. The Platform
`APP/Makefile` targets are:

| Target | Action |
|---|---|
| `make install` | Create `APP/.venv`, install `backend[dev]`, and run `npm ci` |
| `make backend` / `make frontend` | Run local dev servers |
| `make lint` | Ruff and ESLint |
| `make lint-imports` | Backend import boundary checks |
| `make types` | Strict mypy and TypeScript |
| `make test-backend` / `make test-frontend` | Focused project test suites |
| `make test` | Both test suites |
| `make contracts` | Regenerate backend JSON Schema and frontend TypeScript contracts |
| `make check` | Lint, layering, types, and tests |

Make requires GNU Make and is optional. Commands in [INSTALL.md](INSTALL.md) work without it.
On Windows, the Makefile uses the Python Launcher and `.venv/Scripts`; if GNU Make is not
installed, run equivalent venv Python commands directly.

## Verification commands

Platform backend, from `APP/` after installing `backend[dev]`:

```powershell
.\.venv\Scripts\python.exe -m ruff check --config backend/pyproject.toml backend scripts
Push-Location backend
..\.venv\Scripts\lint-imports.exe
..\.venv\Scripts\python.exe -m mypy src
..\.venv\Scripts\python.exe -m pytest
Pop-Location
```

On POSIX, the corresponding commands are:

```sh
.venv/bin/python -m ruff check --config backend/pyproject.toml backend scripts
(cd backend && ../.venv/bin/lint-imports)
(cd backend && ../.venv/bin/python -m mypy src)
(cd backend && ../.venv/bin/python -m pytest)
```

Frontend, from `APP/frontend/`:

```sh
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Engine deterministic tests, from `engine/satquery-ai/`, use the same test selection as CI:

```sh
python -m pip install -e '.[dev,geospatial,raster]'
python -m pytest -c pyproject.toml -m "not real_acceptance" \
  ../tests/test_platform_*.py \
  ../tests/test_perception*.py \
  ../tests/test_capability_matrix.py \
  ../tests/test_client.py \
  ../tests/test_cli_connectors.py \
  ../tests/test_cli_investigate.py \
  ../tests/test_cli_memory.py \
  ../tests/test_earth_objects.py \
  ../tests/test_nasa_firms.py \
  ../tests/test_noaa_coops.py \
  ../tests/test_monitoring.py \
  ../tests/test_persistent_platform_history.py \
  ../tests/test_scientific_memory_and_readiness.py \
  ../tests/test_stac_connector.py \
  ../tests/test_open_meteo.py \
  ../tests/test_earth_sources.py \
  ../tests/test_usgs_3dep.py
```

`real_acceptance` is excluded by CI because it requires live model/provider setup. CI does not
download Torch/Transformers model weights or call live external data sources.

## Contracts and generated files

Backend Pydantic models are the source for shared Platform wire contracts:

1. From `APP/`, run `python scripts/export_contracts.py` to update `contracts/schema.json`.
2. From `APP/frontend/`, run `npm run gen:contracts` to update
   `src/shared/generated/contracts.ts`.
3. Review both generated diffs and commit them with the source model change.

Do not hand-edit generated contract outputs. `make contracts` runs both stages. The Platform
GitHub workflow checks the JSON Schema and TypeScript output for drift.

## Generated/runtime artifacts

| Artifact | Produced by | Purpose/handling |
|---|---|---|
| `APP/contracts/schema.json` | `APP/scripts/export_contracts.py` | Generated shared schema; tracked |
| `APP/frontend/src/shared/generated/contracts.ts` | `npm run gen:contracts` | Generated frontend types; tracked |
| `APP/frontend/node_modules/` | `npm ci` | Local npm dependencies; ignored |
| `APP/frontend/dist/` | `npm run build` | Vite production build and Cesium static worker/assets; ignored |
| `APP/frontend/*.tsbuildinfo` | `tsc -b` | Incremental compiler cache; ignored |
| `.venv/` | `python -m venv` | Python environment; ignored |
| `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, import-linter cache | Python tooling | Disposable caches; ignored |
| `APP/var/platform.sqlite3` | Backend startup | SQLite session, conversation, task, and event tables created with `CREATE TABLE IF NOT EXISTS` |
| `APP/var/images/` | Vision image upload | Session-scoped original image bytes and generated PNG thumbnails |
| Engine SQLite/cache/model data | Engine settings and optional model use | Defaults may be in-memory; local persistent paths and Hugging Face model caches are operator-controlled |
| `test_runs/` | Explicit Engine tests/tools | Test and acceptance outputs; not required to boot |

## Configuration and initialization

The Platform loads `APP/config/base.yaml`, provider YAML files, the selected
`config/environments/<EARTH_ENV>.yaml`, optional profiles from `EARTH_PROFILES`, `.env`, then
environment overrides. See [APP configuration](APP/docs/configuration.md). Secrets must be
environment variables, not committed YAML.

Platform startup opens the configured SQLite session store and creates its tables. No manual
migration, database server, config generation, Cesium asset generation, or plugin installation
step is required. The current backend exposes plugin/registry interfaces but does not instantiate
a plugin host during startup; no external plugin auto-registration occurs. Core frontend panels
are registered by the app's React provider setup.

The Engine's connector manifest is opt-in. The example is `engine/configs/connectors.example.json`;
it must be explicitly configured with `SATQUERY_CONNECTORS_CONFIG`. Local Engine state defaults to
in-memory unless configured otherwise. See
[Engine setup](engine/docs/development/SETUP.md).

## Phase 6 intelligence configuration and APIs

The optional `intelligence` settings use typed defaults and can be overridden with the existing
`EARTH_` nested environment convention:

```text
EARTH_INTELLIGENCE__HISTORY_MESSAGE_LIMIT=20
EARTH_INTELLIGENCE__CONTEXT_TOKEN_BUDGET=6000
EARTH_INTELLIGENCE__RETRIEVAL_LIMIT=12
EARTH_INTELLIGENCE__EARTH_SNAPSHOT_LIMIT=20
```

The token figure is a provider-neutral estimate (UTF-8 bytes divided by four), not a provider
tokenizer and not a limit on the Engine's retained transcript. Workspace memory is rebuilt from
persisted Platform records for each search; it uses lexical, geographic, and temporal ranking, not
embeddings. Until the Engine publishes discovery and multimodal contracts, capability responses
mark Engine tools/datasets and provider image support unknown, and image attachments are not sent.
Cross-session retrieval assumes a single trusted workspace; do not expose it in a multi-user
deployment until Platform authentication can partition memory by owner.

Useful local endpoints after startup:

```text
GET  http://127.0.0.1:8000/api/v1/intelligence/capabilities
GET  http://127.0.0.1:8000/api/v1/intelligence/sessions/{session_id}/memory?query=...
POST http://127.0.0.1:8000/api/v1/chat/sessions/{session_id}/plan
```

The plan endpoint returns a normalized plan and does not start an Engine turn. Chat turns invoke
the same planner automatically before delegating text to the Engine Agent API.

## Smoke checks

With the services running:

```text
Engine health:       http://127.0.0.1:9000/api/v1/health
Platform liveness:   http://127.0.0.1:8000/healthz
Platform readiness:  http://127.0.0.1:8000/readyz
Platform OpenAPI:    http://127.0.0.1:8000/docs
Frontend:            http://localhost:5173
```

Liveness proves the Platform process responds. Readiness also reports Engine connectivity;
`degraded` is expected when the Engine is unconfigured or unavailable. Running all tests does not
prove that a live provider/model or upstream connector is available.
