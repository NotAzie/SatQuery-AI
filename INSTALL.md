# Installation and Reproducibility

This guide is based on the checked-in Python manifests, npm lockfile, app settings, and CI
workflows. The repository has two Python applications; install each into its own virtual
environment.

## Required software

| Requirement | Required for | Version/evidence |
|---|---|---|
| Git | Clone and update the repository | Any version supporting HTTPS clone |
| Python | Engine and Platform backend | Use Python 3.12 for both. Platform requires `>=3.12`; Engine requires `>=3.10` and CI uses 3.12 |
| pip and `venv` | Python installation and isolation | Included with standard CPython distributions used by the setup commands |
| Node.js and npm | Platform frontend | Node 22; npm ships with Node. CI uses Node 22 and `npm ci` |
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

`package-lock.json` fixes the npm dependency graph. Always use `npm ci` for a clean install; do
not use `npm install` as the reproducible CI/setup command.

## External services, binaries, and optional assets

- **SatQuery Engine API:** optional for Platform shell development; required for live Engine-backed
  chat. Configure the Platform's `EARTH_ENGINE__KIND=http` and `EARTH_ENGINE__BASE_URL`. The Engine
  Agent API must have a compatible model registered and the Platform must use its model ID.
- **Model provider and credentials:** not configured by default. A provider adapter/model must be
  available to the Engine; API keys belong in the environment, never in committed YAML. The
  Platform does not call model providers directly.
- **Cesium ion:** `VITE_CESIUM_ION_TOKEN` is optional and enables the configured default Cesium
  imagery/terrain. Without it, Cesium opens with no default imagery; it does not prevent app
  startup. Treat the token as browser-visible and scope it appropriately.
- **Upstream Earth data:** optional connectors require network access, and some require provider
  credentials. They do not need to be installed to boot the service.
- **Ollama:** not required by the current Platform runtime. An Ollama profile exists in config,
  but the Platform container does not register concrete model-provider adapters and delegates
  conversation execution to SatQuery Engine.
- **GPU/CUDA/MPS:** not required. The optional Engine vision extra can use hardware-specific
  PyTorch builds. CUDA inference requires a compatible NVIDIA driver; GPU/CUDA tooling is not
  needed for the default API, raster tests, or Platform.

## Windows (PowerShell)

Install Python 3.12 and Node 22 from their official installers, then clone the repository.
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
Push-Location .\frontend
npm ci
Pop-Location
```

For the Engine's basic API/CLI only, the runtime install can be `pip install -e .`; include
`[geospatial,raster]` only when those optional operations are required. To run Engine tests, use
`[dev,geospatial,raster]` as CI does. Do not install `.[vision]` unless using the legacy local
image-model capability.

## Linux and macOS (POSIX shell)

Install Python 3.12, Node 22, and npm using the platform's package manager or official installers.
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
cd frontend
npm ci
cd ../..
```

## Start the services locally

The Engine and Platform backend both default to port 8000, so run the Engine on 9000. In terminal
1 (from `engine/satquery-ai`):

```powershell
.\.venv\Scripts\python.exe -m satquery serve --port 9000
```

```sh
.venv/bin/python -m satquery serve --port 9000
```

In terminal 2 (from repository root), set the Engine connection and start the Platform API. The
`EARTH_AGENT__MODEL_ID` value must be an ID already registered with the Engine.

PowerShell:

```powershell
$env:EARTH_ENGINE__KIND = "http"
$env:EARTH_ENGINE__BASE_URL = "http://127.0.0.1:9000"
$env:EARTH_AGENT__MODEL_ID = "<registered-engine-model-id>"
cd APP
.\.venv\Scripts\python.exe -m uvicorn earth_platform.main:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000
```

POSIX shell:

```sh
export EARTH_ENGINE__KIND=http
export EARTH_ENGINE__BASE_URL=http://127.0.0.1:9000
export EARTH_AGENT__MODEL_ID='<registered-engine-model-id>'
cd APP
.venv/bin/python -m uvicorn earth_platform.main:create_app --factory --reload --app-dir backend/src --host 127.0.0.1 --port 8000
```

In terminal 3, run `npm run dev` from `APP/frontend`, then open <http://localhost:5173>. For a
Platform-only shell, omit Engine settings; `/readyz` will report degraded and Engine-backed chat
will be unavailable. Start a test-free frontend build with `npm run build`.

## Docker development stack

Install Docker Engine/Desktop and Docker Compose v2. From repository root:

```bash
docker compose up --build
```

This runs the Engine, Platform API, and Vite development server; it is **not a production
deployment**. It binds web ports to loopback, has no authentication/TLS, uses an in-memory Engine
event/model runtime by default, and has no provider credentials or registered reasoning model.
The Engine's health endpoint succeeds, but Platform `/readyz` remains `degraded` until the Engine
reports ready. Configure a real Engine model adapter/model ID separately before expecting chat
responses. The
`platform-data` named volume persists the Platform SQLite database and image files. The stack
installs Engine raster/geospatial extras but intentionally omits optional Torch/Transformers
weights and GPU support.

Set `VITE_CESIUM_ION_TOKEN` in the shell or a root `.env` before `docker compose up` only if you
need default Cesium ion imagery. Stop the stack with `Ctrl+C`; remove its containers with
`docker compose down`. `docker compose down -v` also deletes persisted Platform data.

## GitHub Actions

The root workflows are:

- `.github/workflows/platform-ci.yml`: Python 3.12 and Node 22; Platform backend lint, import
  layering, strict types, tests, contract export; frontend `npm ci`, lint, type-check, tests, build,
  and generated TypeScript contract check.
- `.github/workflows/platform-tests.yml`: Python 3.12; Engine deterministic tests installed with
  `.[dev,geospatial,raster]`. Rasterio is installed here through the optional `raster` extra.

No GPU, real model weights, API credentials, or live upstream data access is used by these CI
jobs.

## Troubleshooting

| Symptom | Check |
|---|---|
| `python3.12`/`py -3.12` not found | Install CPython 3.12; on Windows use the Python Launcher or the explicit interpreter path |
| Vite reports an unsupported Node version | Verify `node --version` is 22.x and rerun `npm ci` |
| Cesium globe has no default imagery | Expected without `VITE_CESIUM_ION_TOKEN`; configure a scoped token if desired |
| Platform `/readyz` is degraded | Check Engine URL, Engine health, and that Engine is running; app liveness can still be healthy |
| Chat rejects model ID | Register a compatible reasoning model in the Engine and set `EARTH_AGENT__MODEL_ID` to that exact ID |
| Rasterio import/build failure | Use a supported Python/platform wheel and the Engine `raster` extra; native source builds may need upstream GDAL toolchain instructions |
| Docker says port is in use | Stop the conflicting service or edit the host-side port mapping in `docker-compose.yml` |
| PowerShell activation is blocked | Do not activate; invoke `.\.venv\Scripts\python.exe` directly |
| Fresh installs resolve different Python versions | Python manifests currently use lower bounds and there is no Python lockfile; only npm dependency resolution is locked |
