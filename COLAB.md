# Google Colab

The reproducible end-to-end workflow is [SatQuery-Colab.ipynb](SatQuery-Colab.ipynb), which
starts the Engine, Platform API, and frontend in a Colab VM and runs a real Open-Meteo provider
smoke test. The Agent-model smoke test runs when its optional credentials and model are configured.
Open it in Colab from the repository's default branch:

`https://colab.research.google.com/github/NotAzie/SatQuery-AI/blob/main/SatQuery-Colab.ipynb`

This is a temporary development/demo environment, not a public or production deployment. Python
3.12 and Node.js 24.14+ (24.x or 26.x) are required. The notebook installs Engine `.[geospatial,raster]`, Platform
`backend`, and the two locked Node dependency trees. It intentionally does not
install the optional PyTorch/Transformers vision extra or local model weights. A GPU is not needed
for Platform use or hosted OpenAI Agent inference.

## Required credentials and configuration

| Secret/setting | Required? | Purpose |
|---|---|---|
| Colab Secret `OPENAI_API_KEY` | Optional; required for Engine Agent conversation | Used by the Engine's OpenAI Chat Completions Agent adapter. Keep it in Colab Secrets; the notebook does not print it. Provider usage may incur cost and is subject to OpenAI account/model terms. |
| Notebook `AGENT_MODEL` | Optional; required with the Agent key for Agent conversation | Set to an OpenAI Chat Completions model enabled for your account with tool/function calling. The repository does not pin or guarantee an available model. |
| Colab Secret `VITE_CESIUM_ION_TOKEN` | Optional | Enables Cesium ion imagery/terrain; the integrated frontend passes it to God's Eye as `CESIUM_ION_TOKEN` and it is browser-visible. Scope it accordingly. God's Eye has keyless Esri imagery without it. |
| Colab Secret `GOOGLE_MAPS_API_KEY` | Optional | Enables Google's photorealistic 3D Tiles and God's Eye place search; used client-side and browser-visible. Restrict its APIs and referrers. |
| Colab Secret `GEV_OPENAI_API_KEY` plus notebook `GEV_VOICE_ENABLED=True` | Optional, explicit opt-in | Enables God's Eye Realtime voice and HUD summaries through its local provider proxy. The secret is scoped only to the frontend process and is not bundled into browser code; provider usage may incur separate charges. |
| Notebook `AGENT_SUPPORTS_VISION` | Optional; default false | Set true only when the chosen Agent model accepts image input. It asserts capability; Engine does not discover it. |
| Drive mount toggle | Optional; default false | Mounts Drive to restore/copy snapshots after Engine/API processes have stopped. Never use SQLite databases directly on mounted Drive. |
| Earth-data provider credentials | Optional | The default connector manifest uses public interfaces without credentials for this smoke workflow. FIRMS and protected Earthdata/STAC resources require their provider credential when used. |

OpenAI model/API charges depend on the account and selected model; check the provider's current
pricing and terms before use. Cesium ion usage is governed by its account/token limits and terms.
The Open-Meteo smoke workflow needs no provider key. There is no local or free Agent-model adapter
enabled by this notebook; the optional local BLIP/CLIP pipeline is a separate image-analysis
capability and is not a conversational Agent substitute.

The Engine registers Agent model ID `openai/<AGENT_MODEL>` only when
`SATQUERY_AGENT_OPENAI_MODEL` and an API key are present. The Platform must use the exact same ID
via `EARTH_AGENT__MODEL_ID`. These are set by the notebook. The Engine adapter uses
`SATQUERY_AGENT_OPENAI_API_KEY` or `OPENAI_API_KEY`, optional
`SATQUERY_AGENT_OPENAI_BASE_URL`, `SATQUERY_AGENT_OPENAI_TIMEOUT`, and
`SATQUERY_AGENT_OPENAI_SUPPORTS_VISION`. The Platform does not call model providers itself.
The notebook requests an Engine-owned `platform.capabilities` tool call as part of its Agent
smoke test; the model must support tool/function calling, and the check fails if no tool execution
is observed.

The Engine also has an independent legacy query-planning LLM configured with `SATQUERY_ROUTER`,
`SATQUERY_LLM_API_KEY`/`OPENAI_API_KEY`, `SATQUERY_LLM_BASE_URL`, `SATQUERY_LLM_MODEL`, and
`SATQUERY_LLM_TIMEOUT`. These variables are **not** needed by the hosted Agent adapter; default
hybrid planning falls back to deterministic rules. The optional local image pipeline separately
uses `SATQUERY_PROFILE`, `SATQUERY_DEVICE`, `SATQUERY_DTYPE`, `SATQUERY_BATCH_SIZE`,
`SATQUERY_CAPTION_MODEL`, `SATQUERY_VQA_MODEL`, `SATQUERY_CLIP_MODEL`, `SATQUERY_HF_TOKEN`,
`SATQUERY_HF_CACHE`, and `SATQUERY_HF_LOCAL_ONLY`. These do not configure hosted Agent vision.

The notebook sets the service wiring variables itself: `SATQUERY_CONNECTORS_CONFIG`,
`SATQUERY_PLATFORM_CONFIG`, `SATQUERY_ROUTER=rules` (deterministic legacy query planning),
`EARTH_ENGINE__KIND`, `EARTH_ENGINE__BASE_URL`,
`EARTH_AGENT__MODEL_ID` when Agent chat is configured, `VITE_API_PROXY_TARGET`, and an empty
`VITE_API_BASE_URL` so the frontend consistently uses the local Vite proxy. For the Agent it maps the Colab `OPENAI_API_KEY` Secret to
`SATQUERY_AGENT_OPENAI_API_KEY` and sets `SATQUERY_AGENT_OPENAI_MODEL`,
`SATQUERY_AGENT_OPENAI_SUPPORTS_VISION`. It intentionally does not export the key as global
`OPENAI_API_KEY`, keeping the separate legacy planner unconfigured. The adapter's
`SATQUERY_AGENT_OPENAI_BASE_URL` and `SATQUERY_AGENT_OPENAI_TIMEOUT` are optional; defaults are
the OpenAI API and 120 seconds. See the [Engine environment example](engine/satquery-ai/.env.example)
for the remaining local-model and analysis tuning settings; they are not required for this Colab
hosted-Agent workflow.

The only credentials this notebook needs for its Engine workflow are `OPENAI_API_KEY` for hosted
Agent turns and, optionally, `VITE_CESIUM_ION_TOKEN` for Cesium ion imagery. The integrated
frontend can additionally use `GOOGLE_MAPS_API_KEY`; optional God's Eye Realtime voice/HUD uses
`GEV_OPENAI_API_KEY` only when explicitly enabled. In Colab, place these values in Colab Secrets
before startup rather than entering them into God's Eye's Provider Settings form, which persists
form entries to the runtime's `.env`. Other connector credentials are
feature-specific: `SATQUERY_NASA_FIRMS_MAP_KEY` is required for NASA FIRMS, which is not enabled
in the example manifest. NASA Earthdata CMR and STAC connectors accept optional bearer tokens via
their connector credential interface when a configured protected catalog requires them; the
repository does not define a universal environment-variable name or Colab secret for those
per-connector credentials. The example Open-Meteo forecast used by the smoke test is public and
requires no API key. The services still require outbound network access and provider availability.

## Dependency and capability map

| Component | Runtime dependency | External service / persistence | Colab behavior |
|---|---|---|---|
| Engine API | Python 3.12 environment synced from `engine/satquery-ai/uv.lock`, with `geospatial` and `raster` extras | No separate database server; SQLite files use the configured local path. Connector calls need outbound Internet. | CPU-compatible API and connector execution; no GPU required. |
| Platform API | Python 3.12 environment synced from `APP/backend/uv.lock` | Engine HTTP API at loopback port 9000; Platform SQLite and image files under `APP/var`. | Starts on loopback port 8000 and proxies through Vite. |
| Frontend and Earth runtime | Node.js 24.14+ (24.x or 26.x), npm, both `APP/frontend` and `APP/earth-view` lockfiles | God's Eye View is the primary Earth UI and shares its Cesium viewer with SatQuery; Vite proxies `/api/v1` to Platform. | Both dependency sets use `npm ci`; Vite port 5173 is exposed with Colab's port proxy. |
| Hosted Agent | Optional OpenAI API key and a model available to the account that supports Chat Completions tool calls | OpenAI API; usage billed under provider account terms. | Remote inference; Colab CPU/GPU does not accelerate it. If no model/key is set, Agent smoke test is skipped and Agent chat is unavailable. |
| Engine query planning | Deterministic Engine rules; notebook explicitly sets `SATQUERY_ROUTER=rules` | None for the notebook workflow. Legacy LLM routing can separately use `SATQUERY_LLM_*`, but is not enabled. | Avoids hidden planner calls and keeps planning deterministic. |
| Earth data | Checked-in connector adapters and `engine/configs/connectors.example.json` | Provider APIs/data catalogues listed in the capability table; network, provider uptime, coverage, quotas, and credentials vary. | Open-Meteo smoke request is public and keyless; the notebook verifies actual data rather than only connector registration. |
| Local vision models | Engine `vision` extra (`torch`, `transformers`) plus model weights/cache; selected device and adequate RAM/VRAM/storage | Hugging Face model registry for uncached public weights; gated models require appropriate access/token. | Not installed/downloaded by default. `nvidia-smi` GPU name and memory, CPU, RAM, and free disk are reported, but the notebook does not infer a safe model from GPU presence or install multi-gigabyte CUDA dependencies. |
| Platform storage | Python SQLite and local filesystem | Optional Google Drive snapshot copying after services stop. | Local files are ephemeral; no PostgreSQL, Redis, object-store, queue, email service, or external worker is required by this setup. |
| Authentication / operations | Not included in this repository's Colab path | No identity provider, public HTTPS endpoint, durable worker scheduler, or multi-user boundary is configured. | Suitable only for a trusted, temporary, single-user development/demo runtime. Do not expose it as a production service. |

Python versions and lockfiles are checked in, but the Colab VM itself is not pinned by Google;
the notebook logs the selected Git commit and live CPU/RAM/GPU/storage facts. PyPI/Node package
availability, NodeSource bootstrap availability when a supported Node 24 release is missing, Colab proxy behavior,
model account access, and upstream data availability remain outside the repository's control.
For exact source reproducibility, run the notebook against a reviewed commit rather than assuming
the default branch remains unchanged.

## Capability matrix

| Capability | Colab status |
|---|---|
| Platform UI, Projects, sessions, search, relationships, templates, collections, and SQLite persistence | Works locally in the runtime; data is ephemeral unless a stopped-run snapshot is copied to Drive. |
| Engine API and supported deterministic investigation workflows | Works when the connector manifest is loaded and upstream provider/network returns usable data. Notebook executes a live Open-Meteo forecast investigation and fails on HTTP/provider errors or empty observations. |
| Open-Meteo, OSM/Overpass, USGS, STAC Earth Search, NASA Earthdata CMR, NASA POWER, NOAA CO-OPS | Implemented and listed in `engine/configs/connectors.example.json`; require network and service/data availability. Registration alone does not prove acquisition. |
| NASA FIRMS | Implemented, but not in the example manifest. Add `nasa_firms` to a manifest and provide `SATQUERY_NASA_FIRMS_MAP_KEY`. |
| OpenAI Agent chat/tool use | Works only with Colab Secret key, an account-enabled tool-calling Chat Completions model, and successful live provider calls. When configured, the notebook checks a real completed SSE turn and Engine capability-tool execution. |
| Agent image chat | Conditional: choose an image-capable model and explicitly enable the vision declaration; not exercised by default smoke tests. |
| Other hosted Agent providers (Anthropic, Gemini, OpenRouter) or Ollama | Not wired to an Engine Agent adapter in this repository. Platform provider YAML entries alone do not enable them. |
| Legacy local BLIP/CLIP image API | Not installed by the notebook. Requires PyTorch/Transformers, Hugging Face model downloads/cache, and potentially substantial disk/RAM/VRAM. |
| Raster sampling/zonal statistics/component extraction | Requires installed raster/geospatial extras, compatible declared raster assets, and provider access. |
| God's Eye Earth environment | Works with keyless Esri World Imagery; Cesium ion and Google Maps credentials enable additional imagery/terrain options. |
| External alert delivery, auth, multi-user isolation, distributed workers, production deployment | Not supplied. Colab does not make these available. |

See [supported datasets](engine/docs/datasets/SUPPORTED_DATASETS.md), [Engine setup](engine/docs/development/SETUP.md),
[Agent architecture](engine/docs/architecture/AGENT_SYSTEM.md), and the [operational dependency audit](INSTALL.md)
for provider-specific details, limits, and cost/licensing boundaries.

## First-time setup checklist

1. Open [SatQuery-Colab.ipynb](SatQuery-Colab.ipynb) in Google Colab and select a Python 3.12
   runtime; GPU is optional.
2. For hosted Agent chat, add `OPENAI_API_KEY` to Colab Secrets, grant notebook access, and set
   `AGENT_MODEL` to a Chat Completions model enabled for that account. This is optional for the
   Platform and Engine-backed data workflow. Optionally add `VITE_CESIUM_ION_TOKEN` and
   `GOOGLE_MAPS_API_KEY` for additional Earth imagery. God's Eye Realtime voice/HUD requires the
   separate `GEV_OPENAI_API_KEY` Secret and explicit `GEV_VOICE_ENABLED=True`; enable vision only
   when the chosen Agent model supports it.
3. Run the notebook cells in order. It inspects CPU/RAM/GPU/storage, installs the Engine and
   Platform Python dependencies from their frozen `uv.lock` files, installs frontend dependencies
   with `npm ci` in both `APP/earth-view` and `APP/frontend`, configures the public connector manifest and local SQLite paths, then starts all
   three services. It records the checked-out Git revision for reproducibility.
4. Confirm Engine health, Platform readiness, and frontend startup. Open the Vite UI through the
   Colab port proxy.
5. Run the live smoke-test cells. When configured, the Agent check must return a non-empty
   completed SSE response and execute `platform.capabilities`; the Engine check must report
   `succeeded` and at least one real Open-Meteo observation. Provider outages, rejected models,
   missing tool-call support, network restrictions, and API errors fail visibly.
6. When finished, terminate all services. If persistence is needed, enable Drive snapshots and
   save after shutdown. The local `/content` database is otherwise temporary.

## Persistence and Colab limitations

The notebook stores Platform SQLite and uploaded images under `APP/var`, and Engine records in a
local SQLite file under `/content/satquery-data`. Engine SQLite configuration is supplied using
`SATQUERY_PLATFORM_CONFIG`. This is durable only for the lifetime of the Colab VM. When Drive
snapshots are enabled, databases and images are copied **after processes stop** and restored into
local `/content` before startup; do not run SQLite on Drive/FUSE.

Colab can reclaim or disconnect the VM, ports are exposed through a temporary Colab proxy, and the
embedded browser may restrict camera/clipboard capture. There is no app authentication, TLS
deployment, stable public endpoint, or long-running-worker guarantee. Keep the notebook private if
it accesses sensitive inputs, and review provider terms before sending data to hosted inference.
