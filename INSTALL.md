# Integrated Local Startup and Installation

This guide is based on the checked-in Python manifests and lockfiles, npm lockfile, app settings,
and CI workflows. The repository has two Python applications; install each into its own virtual
environment. The documented Python setup commands use pip and do not consume the checked-in
`uv.lock` files, so they resolve the compatible versions specified by the manifests. This is the
single authoritative startup procedure for running the Engine, Platform API, and frontend together
from a clean clone.

For Google Colab, use the [adaptive deployment notebook](SatQuery-Colab.ipynb) and
[Colab-specific capability and setup notes](COLAB.md). That notebook uses the checked-in Python
lockfiles; local setup commands below remain pip-based.

## Required software

| Requirement | Required for | Version/evidence |
|---|---|---|
| Git | Clone and update the repository | Any version supporting HTTPS clone |
| Python | Engine and Platform backend | Use Python 3.12 for both. Platform requires `>=3.12`; Engine requires `>=3.10` and CI uses 3.12 |
| pip and `venv` | Python installation and isolation | Included with standard CPython distributions used by the setup commands |
| Node.js and npm | Platform frontend and integrated God's Eye runtime | Node.js `>=24.14 <25` or `>=26 <27`; npm ships with Node |
| Web browser | Platform UI | Modern browser with WebGL support for Cesium |

`make` is an optional convenience for the Platform commands on systems with GNU Make. The
PowerShell and shell instructions below do not require it. Docker Engine/Desktop with the Compose
v2 plugin is optional and is only needed for the development stack in `docker-compose.yml`.

No separate SQLite server, SQLite command-line tool, GDAL installation, compiler, or system
library is required for the default Python install when compatible PyPI wheels are available.
`aiosqlite` uses Python's SQLite module. Pillow and common geospatial packages publish platform
wheels. If a wheel is unavailable for a particular OS/Python/CPU combination, pip may attempt a
source build; that is outside the repository's tested setup and may require the package's own
native build toolchain and libraries.

The frontend lockfile also installs Vite's platform-specific `esbuild` executable. Uvicorn's
`standard` extra installs optional server/watch accelerators when wheels are available. Neither
requires a separately downloaded binary in the supported Python 3.12/Node 22 setup.

## Dependencies and why they exist

### Earth Intelligence Platform backend (`APP/backend/pyproject.toml`)

| Package | Required/optional | Purpose |
|---|---|---|
| `fastapi` | Runtime-required | HTTP API and OpenAPI |
| `uvicorn[standard]` | Runtime-required | ASGI server; optional speed/watch extras are installed when supported |
| `pydantic` | Runtime-required | Typed runtime and wire models |
| `pydantic-settings[yaml]` | Runtime-required | Environment/settings loading and YAML configuration |
| `aiosqlite` | Runtime-required | Async SQLite session/event persistence |
| `httpx` | Runtime-required | HTTP and streaming client for SatQuery Engine |
| `Pillow` | Runtime-required | Image validation, decoding, and thumbnails |
| `python-multipart` | Runtime-required | Multipart image upload parsing |
| `pytest`, `pytest-asyncio` | Development/test only (`dev`) | Backend test runner and async tests |
| `ruff` | Development only (`dev`) | Python lint and format checks |
| `mypy` | Development only (`dev`) | Strict Python type checking |
| `import-linter` | Development/CI only (`dev`) | Enforces backend import-layer boundaries |
| `types-PyYAML` | Development/type-check only (`dev`) | YAML typing for mypy |

The build backend is `hatchling` (declared in `[build-system]`); pip installs it during package
builds. There is no Platform provider SDK dependency: the current Platform forwards text turns to
the Engine Agent API.

### SatQuery Engine (`engine/satquery-ai/pyproject.toml`)

| Package | Required/optional | Purpose |
|---|---|---|
| `fastapi` | Runtime-required | Engine HTTP API |
| `uvicorn[standard]` | Runtime-required | Engine ASGI server |
| `pydantic` | Runtime-required | Engine configuration and API contracts |
| `python-multipart` | Runtime-required | Image upload endpoint |
| `numpy` | Runtime-required | Array and numerical operations |
| `Pillow` | Runtime-required | Image decoding and preprocessing |
| `httpx` | Runtime-required | External HTTP data-provider clients |
| `pytest` | Development/test only (`dev`) | Engine test runner |
| `pyproj`, `shapely` | Optional (`geospatial`) | CRS transformations and geometry operations |
| `rasterio` plus `pyproj`, `shapely` | Optional (`raster`) | Explicit raster sampling, summaries, and categorical raster operations |
| `torch`, `transformers` | Optional (`vision`) | Legacy image-perception model path; not needed to boot the Engine or run the Platform |
| `accelerate`, `sentencepiece` | Optional (`large`) | Additional model-loading/tokenizer support for selected large vision checkpoints |

The Engine build backend is `setuptools` with `wheel`. The checked-in
`engine/satquery-ai/requirements.txt` also installs `torch` and `transformers`; use the project
extras instead for a minimal install. `requirements-dev.txt` includes that requirements file and
therefore also pulls the vision stack.

The Engine CI workflow installs `.[dev,geospatial,raster]`. In particular, Rasterio is an
**optional** runtime extra; the workflow installs it because its selected raster regression tests
exercise that capability. The workflow does not install `vision` or model weights.

### Platform frontend (`APP/frontend/package.json` and `package-lock.json`)

Runtime packages:

| Package | Purpose |
|---|---|
| `cesium` | Earth globe and rendering |
| `react`, `react-dom` | UI and browser rendering |
| `react-router-dom` | Frontend routing |
| `zustand` | Client state stores |

Development/build/test packages:

| Package(s) | Purpose |
|---|---|
| `vite`, `@vitejs/plugin-react` | Frontend dev server and production bundler |
| `vite-plugin-cesium` | Cesium static assets and worker handling in Vite |
| `typescript`, `@types/node`, `@types/react`, `@types/react-dom` | TypeScript compiler and type definitions |
| `tailwindcss`, `@tailwindcss/vite` | CSS utility framework and Vite integration |
| `eslint`, `@eslint/js`, `typescript-eslint`, `eslint-plugin-react-hooks`, `globals` | Frontend linting |
| `vitest` | Frontend unit tests |
| `json-schema-to-typescript` | Generates frontend types from shared JSON Schema |

`APP/frontend/package-lock.json` and `APP/earth-view/package-lock.json` fix separate dependency
graphs. Both are required by the integrated Vite app; use `npm ci` in each directory before
starting/building. Vite deduplicates Cesium to one browser runtime across the two source trees.
Always use `npm ci` for clean installs; do not use `npm install` as the reproducible setup command.

### God's Eye Earth runtime (`APP/earth-view`)

God's Eye View is the Platform's primary Earth interface, not a second service. Its complete
browser source, templates, styles, assets, and local provider middleware remain in this directory.
The React workspace attaches its typed `EarthController` to the runtime's single Cesium viewer.
For integrated local use, all settings are read from the repository-root `.env`; the standalone
God's Eye `.env.example` remains the reference for its full provider options.

## External services, binaries, and optional assets

- **SatQuery Engine API:** required for the integrated startup below. The Engine API and typed
  discovery endpoints work without a reasoning model. The Engine optionally registers its
  OpenAI Chat Completions Agent adapter when configured; without a model and API key, chat remains
  unavailable. See the model provider settings below and [Google Colab setup](COLAB.md).
- **Model provider and credentials:** optional; the Engine includes an OpenAI Chat Completions
  Agent adapter. In the shared root `.env`, set `SATQUERY_AGENT_OPENAI_MODEL` and either
  `SATQUERY_AGENT_OPENAI_API_KEY` or the already-used `OPENAI_API_KEY`; set
  `EARTH_AGENT__MODEL_ID` to the exact `openai/<model>` ID. For example:
  `SATQUERY_AGENT_OPENAI_MODEL=gpt-4o-mini` and `EARTH_AGENT__MODEL_ID=openai/gpt-4o-mini`.
  The Platform does not call model providers directly; other Agent providers need their own Engine
  adapter.
- **Cesium ion:** `CESIUM_ION_TOKEN` (or legacy `VITE_CESIUM_ION_TOKEN`) is optional and enables
  the configured default Cesium imagery/terrain. Without it, Cesium opens with no default imagery;
  it does not prevent app startup. Treat the token as browser-visible and scope it appropriately.
- **Upstream Earth data:** optional connectors require network access, and some require provider
  credentials. They do not need to be installed to boot the service.
- **Ollama:** not required by the current Platform runtime. An Ollama profile exists in config,
  but the Platform container does not register concrete model-provider adapters and delegates
  conversation execution to SatQuery Engine.
- **GPU/CUDA/MPS:** not required. The optional Engine vision extra can use hardware-specific
  PyTorch builds. CUDA inference requires a compatible NVIDIA driver; GPU/CUDA tooling is not
  needed for the default API, raster tests, or Platform.

## Windows (PowerShell)

Install Python 3.12 and a supported Node.js release (`>=24.14 <25` or `>=26 <27`) from their
official installers, then clone the repository.
No administrator shell or execution-policy change is required when invoking venv Python directly.

```powershell
cd .\engine\satquery-ai
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,geospatial,raster]"

cd ..\..\APP
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
Push-Location .\earth-view
npm ci
Pop-Location
Push-Location .\frontend
npm ci
Pop-Location
```

For the Engine's basic API/CLI only, the runtime install can be `pip install -e .`; include
`[geospatial,raster]` only when those optional operations are required. To run Engine tests, use
`[dev,geospatial,raster]` as CI does. Do not install `.[vision]` unless using the legacy local
image-model capability.

## Linux and macOS (POSIX shell)

Install Python 3.12 and Node.js `>=24.14 <25` or `>=26 <27` using the platform's package manager
or official installers.
The project itself does not require `apt`, Homebrew, or other system-package installations when
compatible wheels are available.

```sh
cd engine/satquery-ai
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,geospatial,raster]'

cd ../../APP
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e 'backend[dev]'
cd earth-view
npm ci
cd ../frontend
npm ci
cd ../..
```

## Start the complete product locally

Use one shared local configuration file: `C:\Users\mazin\SatQuery-AI\.env` (the repository-root
`.env`, beside this guide). It is ignored by Git. On a clean checkout, copy `.env.example` to `.env`.
For this checkout, the previous `engine\.env` settings have been copied to the root file, and the
original `engine\.env` has been kept. Never overwrite an existing root `.env` while migrating.

PowerShell: `Copy-Item .env.example .env`

POSIX shell: `cp .env.example .env`

The optional Provider Settings panel also saves to this same root `.env`; it does not open during
normal startup. A saved key remains there across restarts. Restart the affected service after
changing its settings: Vite reloads itself after a panel save, but Engine and Platform settings
take effect when those processes start. Never put secrets in `VITE_` variables. Google Maps and
Cesium ion keys are intentionally exposed to the browser and must be restricted at their providers.
The OpenAI key in Provider Settings enables God's Eye voice features; to enable SatQuery Engine
chat too, set the commented model and matching `EARTH_AGENT__MODEL_ID` entries in this same file,
then restart Engine and Platform. Chat is unavailable until a valid provider key is supplied.

Start the services in three terminals (PowerShell or POSIX) and leave each running. Engine and
Platform both default to port 8000, so this guide runs Engine on 9000 and Platform on 8000.

### Terminal 1 — SatQuery Engine

From `engine/satquery-ai` (Engine reads the repository-root `.env`):

```powershell
.\.venv\Scripts\python.exe -m satquery serve --port 9000
```

```sh
.venv/bin/python -m satquery serve --port 9000
```

### Terminal 2 — Platform API

From the repository root, the Platform reads `EARTH_ENGINE__KIND` and
`EARTH_ENGINE__BASE_URL` from `.env`:

PowerShell:

```powershell
cd APP
.\.venv\Scripts\python.exe -m uvicorn earth_platform.main:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000
```

POSIX shell:

```sh
cd APP
.venv/bin/python -m uvicorn earth_platform.main:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000
```

### Terminal 3 — Frontend

Install both locked npm dependency sets from the repository root:

```powershell
Push-Location APP\earth-view
npm ci
Pop-Location
Push-Location APP\frontend
npm ci
Pop-Location
```

There is no root `package.json`, so run npm from `APP/frontend` (not the repository root):

```powershell
npm run dev -- --host 127.0.0.1
```

```sh
npm run dev -- --host 127.0.0.1
```

Open <http://127.0.0.1:5173>.

### Verify the integrated connection

From any terminal, these endpoints verify Engine health, Platform liveness/readiness, and the
typed Engine discovery request forwarded through the Platform:

```powershell
curl.exe -i http://127.0.0.1:9000/api/v1/health
curl.exe -i http://127.0.0.1:8000/healthz
curl.exe -i http://127.0.0.1:8000/readyz
curl.exe -i http://127.0.0.1:8000/api/v1/intelligence/engine-discovery
```

`/readyz` may return HTTP 200 with `"status":"degraded"` when the Engine's optional legacy image
models have not been warmed. This does not mean the Engine API is unreachable; the discovery
request above is the integration check. Cesium imagery is also optional without
`VITE_CESIUM_ION_TOKEN`.

The default Engine application registers no model unless the optional OpenAI adapter is configured
as described above. Without provider configuration, the integrated workspace starts and Engine
discovery works, but AI chat cannot complete a turn. Image chat additionally requires an
image-capable model and explicit adapter vision configuration. See [Google Colab setup](COLAB.md)
for a notebook that configures hosted chat and runs live conversation and Engine-backed
investigation smoke tests.

For Platform-shell-only UI work, the Engine can be omitted and `EARTH_ENGINE__KIND` and
`EARTH_ENGINE__BASE_URL` left unset; the Platform starts with Engine-dependent features degraded.
This is not the integrated setup.

## Docker development stack

Install Docker Engine/Desktop and Docker Compose v2. From repository root:

```bash
docker compose up --build
```

This runs the Engine, Platform API, and Vite development server; it is **not a production
deployment**. It binds web ports to loopback, has no authentication/TLS, uses an in-memory Engine
event/model runtime by default, and has no provider credentials or registered reasoning model.
The Engine health endpoint checks Engine readiness, not Agent model registration; Platform
`/readyz` can therefore be degraded while Engine API discovery remains available. The checked-in
Engine also does not register an Agent reasoning adapter, so the stack does not provide chat
responses by itself. The `platform-data` named volume persists the Platform SQLite database and
image files. The stack
installs Engine raster/geospatial extras but intentionally omits optional Torch/Transformers
weights and GPU support.

Set `VITE_CESIUM_ION_TOKEN` in the shell or a root `.env` before `docker compose up` only if you
need default Cesium ion imagery. Stop the stack with `Ctrl+C`; remove its containers with
`docker compose down`. `docker compose down -v` also deletes persisted Platform data.

## GitHub Actions

The root workflows are:

- `.github/workflows/platform-ci.yml`: Python 3.12 and Node 24.14; Platform backend lint, import
  layering, strict types, tests, contract export; God's Eye runtime tests, boundaries, and
  standalone build; frontend `npm ci`, lint, type-check, tests, integrated build, and generated
  TypeScript contract check.
- `.github/workflows/platform-tests.yml`: Python 3.12; Engine deterministic tests installed with
  `.[dev,geospatial,raster]`. Rasterio is installed here through the optional `raster` extra.

No GPU, real model weights, API credentials, or live upstream data access is used by these CI
jobs.

## Troubleshooting

| Symptom | Check |
|---|---|
| `python3.12`/`py -3.12` not found | Install CPython 3.12; on Windows use the Python Launcher or the explicit interpreter path |
| Vite reports an unsupported Node version | Verify Node.js is `>=24.14 <25` or `>=26 <27`; rerun `npm ci` in both `APP/earth-view` and `APP/frontend` |
| Cesium globe has no default imagery | Expected without `VITE_CESIUM_ION_TOKEN`; configure a scoped token if desired |
| Platform `/readyz` is degraded | Call `/api/v1/intelligence/engine-discovery` to test Engine API connectivity; Engine readiness can remain degraded until its optional image backend is warmed |
| Chat rejects model ID | The default Engine has no Agent reasoning adapter; provide a compatible adapter, then set `EARTH_AGENT__MODEL_ID` to its exact registered ID |
| Rasterio import/build failure | Use a supported Python/platform wheel and the Engine `raster` extra; native source builds may need upstream GDAL toolchain instructions |
| Docker says port is in use | Stop the conflicting service or edit the host-side port mapping in `docker-compose.yml` |
| PowerShell activation is blocked | Do not activate; invoke `.\.venv\Scripts\python.exe` directly |
| Fresh pip installs resolve different Python versions | The Engine and Platform each have a `uv.lock`, but the documented pip setup commands use compatible manifest ranges rather than those locks; npm installs use the frontend lockfile |
