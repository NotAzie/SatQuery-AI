# SatQuery AI

SatQuery is being built as an Earth Intelligence Operating System: a platform
for observing and investigating Earth through evidence from independent
sensing modalities. The application composes the provider-neutral platform
runtime for execution, investigations, and perception while keeping the
existing satellite and aerial image analysis as one available capability.

Problem statement: **SIH26167**  
Canonical Python package: `satquery-ai/satquery`  
Optional image fetcher: `satquery-ai/connectors/image_fetcher`

## Canonical Project Path

The only authoritative source tree is:

```text
SAT_QUERY\satquery-ai\
```

Run Python, pytest, CLI, and server commands from that directory. The outer `SAT_QUERY` folder is a workspace container, not another Python package.

## Install

For a fresh checkout:

```powershell
git clone <your-repo> satquery-ai
cd satquery-ai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
python -m pip install -r requirements-dev.txt
```

Torch must match the machine. For a CPU installation, use the PyTorch CPU index when creating a new environment:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Copy `.env.example` to `.env` in the canonical directory and adjust model/cache settings as needed.

## Doctor, Warmup, and Readiness

`doctor` checks dependencies and configuration, and reports live platform status
when the API is running. Model warmup targets the running server so the warmed
models remain available to subsequent requests:

```powershell
cd satquery-ai
python -m satquery doctor
python -m satquery serve
# In a second terminal:
python -m satquery warmup
```

`warmup` loads the practical CLIP, captioner, and VQA models and reports `ready: true` only after successful loading. Health and capabilities distinguish installed dependencies from actually warmed models.

For a demo, warm up once and keep the API process alive so loaded models and caches are reused.

## CLI Usage

The primary interface is mission and observation oriented. The deterministic
Scientific Investigation Planner extracts recognized Earth ontology terms,
explicit geography, and reproducible time expressions from natural language.
It returns clarification requests or multiple candidate plans instead of
silently guessing unresolved scope.

Start the platform in one terminal (`python -m satquery serve`). The CLI uses
the same running runtime as the browser; point `SATQUERY_API_URL` at a different
server when needed.

```powershell
cd satquery-ai

python -m satquery investigate "Review air temperature near this site" --query-file earth-query.json
python -m satquery intelligence design "Measure air temperature globally last week"
python -m satquery plan earth-query.json --explain
python -m satquery observe earth-query.json
python -m satquery capabilities
python -m satquery datasets
python -m satquery datasets --query "coastal water level"
python -m satquery connectors
python -m satquery mission list
python -m satquery investigation show <investigation-id>
python -m satquery investigation execute <investigation-id>
python -m satquery investigation report <investigation-id>
python -m satquery investigation compare <investigation-id-1> <investigation-id-2>
python -m satquery runtime
python -m satquery doctor
```

`investigate` produces and stores an `InvestigationPlan` with its mission and
investigation records and adds an `InvestigationDesign` that traces evidence
requirements to observation steps. It does not acquire data. Review the plan
and design, then execute a ready investigation explicitly; missing scope and
ambiguous terms must be resolved first. `--query-file` supplies authoritative
structured criteria. After execution, `investigation show` and `investigation
execute` include an evidence coverage audit. Coverage is not a scientific
conclusion or a confidence estimate.

`investigation report` renders the recorded mission, plan, observations,
Earth Objects, evidence coverage, reasoning, provenance, and limitations as
Markdown. `investigation compare` aligns resolved canonical measurements
across selected investigations for inspection. It does not perform unit
conversion, trend analysis, or scientific inference; exact label alignment
alone does not prove that measurements are scientifically comparable.

The older image analysis command remains supported as a perception capability:

```powershell
cd satquery-ai

python -m satquery ask "describe this scene" -i path\to\scene.jpg --trace
python -m satquery ask "what type of scene is this" -i path\to\scene.jpg --trace
python -m satquery ask "where are the buildings" -i path\to\scene.jpg --trace
python -m satquery ask "Is there water in this image?" -i path\to\scene.jpg --trace
python -m satquery ask "what changed" -i before.jpg -i after.jpg --trace
```

The browser workspace at `/` now exposes mission creation, capability matrix
and runtime inspection, structured observation execution, observation and
provenance views, and local mission history. Image analysis remains accessible
in the same interface as one perception capability. The demo console also has a **Fetch real satellite imagery from a location**
mode. Enter a place/address or coordinates, optionally set zoom, and submit a
question without selecting an image. The optional fetcher obtains the image and
the normal SatQuery engine analyzes it in the same request.

The response includes the routed intent, selected tools, model/backend, latency, trace steps, and semantic regions or scene labels.

## API and UI

Start the local API and demo console:

```powershell
cd satquery-ai
python -m satquery serve
```

Open `http://127.0.0.1:8000/` for the console or `http://127.0.0.1:8000/docs` for OpenAPI.

Main endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Demo console |
| `GET` | `/api/v1/health` | Dependencies, backend readiness, device, and setup actions |
| `GET` | `/api/v1/capabilities` | Capabilities currently available after readiness checks |
| `GET` | `/api/v1/config` | Effective redacted configuration |
| `POST` | `/api/v1/warmup` | Load configured models |
| `POST` | `/api/v1/query` | Multipart image upload and natural-language query |
| `POST` | `/api/v1/query/json` | Query server-side image paths |
| `POST` | `/api/v1/query/location` | Optional place/coordinates fetch, then normal image analysis |

The Earth Intelligence API adds modality planning, dataset discovery,
observations, mission/investigation lifecycle, and runtime inspection. See the
[API reference](../docs/api/API_REFERENCE.md) and
[development setup](../docs/development/SETUP.md) for connector manifests and
EarthQuery examples. Image query responses include the platform mission,
investigation, and execution IDs for inspection.

## Core Tools

- **Captioning**: BLIP prompt ensemble plus land-use classification, quadrant captions, modality, colour, texture, and evidence-led composition. The current Phase 2 path leads with overhead land-use evidence rather than treating a generic BLIP sentence as ground truth.
- **VQA**: BLIP-VQA with overhead satellite/radar framing. Yes/no presence questions receive an independent CLIP whole-image/quadrant cross-check.
- **Scene / land use**: CLIP zero-shot classification over a 47-label remote-sensing taxonomy, prompt ensemble, whole-scene scoring, and quadrant agreement/stability evidence.
- **Grounding**: Multi-scale CLIP window scoring against contrasts, now using overhead-native target phrase ensembles for common targets such as buildings, roads, water, and vegetation. It returns ranked semantic regions.

Counting, change detection, and modality analysis remain available, but they are not the focus of the current Phase 2 quality work.

## Quality and Fast Profiles

Quality is the default and is never silently replaced:

```text
SATQUERY_PROFILE=quality
CLIP: openai/clip-vit-large-patch14
Grounding: four scales, up to 320 windows
```

The explicit fast profile is available for CPU demos:

```powershell
$env:SATQUERY_PROFILE = "fast"
..\.venv\Scripts\python.exe -m satquery ask "where are the buildings" -i scene.jpg --trace
```

Fast mode uses CLIP-Base and a small grounding sweep. It is a deliberate latency/recall tradeoff, not the quality baseline. The quality profile remains the default in `Settings` and `.env.example`.

Useful settings include:

- `SATQUERY_DEVICE` — `auto`, `cpu`, `cuda`, or `mps`.
- `SATQUERY_CLIP_MODEL`, `SATQUERY_CAPTION_MODEL`, `SATQUERY_VQA_MODEL` — explicit model overrides.
- `SATQUERY_GROUNDING_MAX_WINDOWS` — grounding latency/recall control.
- `SATQUERY_BATCH_SIZE` — inference batch size.
- `SATQUERY_HF_CACHE` and `SATQUERY_HF_LOCAL_ONLY` — model cache controls.
- `SATQUERY_IMAGE_ROOT` — sandbox for path-based queries.

## Existing Reliability Baseline

The existing application reliability acceptance suite covers:

- Warmup genuinely loads CLIP, captioner, and VQA models.
- Health and capabilities report readiness rather than only import availability.
- Tool minimum and maximum image counts are enforced.
- Loaded model objects and grounding image embeddings are reused in persistent processes.
- The canonical source is `satquery-ai/satquery`; historical outer modules are quarantined under `../archive/legacy/legacy_outer_modules`.
- Deterministic tests do not depend on Hugging Face cache state.
- Historical Phase 1 acceptance artifacts are preserved under `../archive/reports/phase1/`; future runs write to `test_runs/phase1/`.

Run the existing reliability verification suite:

```powershell
cd satquery-ai
..\.venv\Scripts\python.exe -m pytest -c pyproject.toml ..\tests\test_phase1_acceptance.py -q
..\.venv\Scripts\python.exe scripts\run_phase1.py
```

For real-model acceptance and an archived report:

```powershell
..\.venv\Scripts\python.exe scripts\run_phase1.py --real --profile fast --timeout 45
```

## Existing Model-Quality Regressions

The existing model-quality regressions cover the four core tools:

```powershell
cd satquery-ai
..\.venv\Scripts\python.exe -m pytest -c pyproject.toml ..\tests\test_phase2_quality.py -q
..\.venv\Scripts\python.exe -m pytest -q
```

Real-image checks use existing files under `data/fetched_images/`. The practical validation path warms one persistent engine, then runs:

- `describe this scene`
- `what type of scene is this`
- `where are the buildings`
- `Is there water in this image?`

These checks verify usefulness and stability, not calibrated remote-sensing accuracy.

## Platform Foundation

The local, in-process Phase 0 contracts and infrastructure are documented in
[`../docs/architecture/PHASE0_FOUNDATION.md`](../docs/architecture/PHASE0_FOUNDATION.md).
They provide connector, registry, investigation, execution, configuration,
observability, cache, model, and tool interfaces without replacing the
existing query path. Distributed execution, durable storage, and reasoning or
agent runtimes are not implemented.

## Earth Perception

The standards-based catalog connector supports configurable STAC API catalogs
for collection discovery and spatial-temporal item search. It returns
normalized observation contracts with source STAC items and asset references;
it does not download or transform catalog assets. See the [STAC connector
guide](../docs/datasets/STAC_CONNECTOR.md) for supported behavior and
limitations. The existing Esri World Imagery point fetcher is also adapted to
the canonical observation contract; it does not report an image footprint or
observation date.
Weather forecast, historical weather, downscaled climate, and modeled river
discharge point adapters are provided through the configurable Open-Meteo
connector. These are modeled provider products, not direct measurements.
The USGS 3DEP EPQS connector returns interpolated point elevations and leaves
local uncertainty and observation time unknown unless the provider supplies
them. It does not provide raster DEM downloads or terrain analysis.
Spatial and temporal utility contracts, supported endpoint behavior, and
remaining source coverage are documented in the
[Earth Perception architecture](../docs/architecture/Earth_Perception.md).

## Optional Image Fetcher

The fetcher is deliberately outside the core product path:

```powershell
cd satquery-ai
..\.venv\Scripts\python.exe -m connectors.image_fetcher --place "VIT Chennai, Vandalur" --zoom 18
..\.venv\Scripts\python.exe -m connectors.image_fetcher --lat 12.842946 --lon 80.155410 --zoom 19
```

It saves an image path under `data/fetched_images/`. It uses Nominatim/Photon and Esri World Imagery, so it requires internet access. Normal SatQuery usage does not import or require this plugin.

## Project Structure

```text
satquery-ai/
  satquery/                 canonical core package
    __main__.py             CLI entry point
    config.py               typed environment settings
    registry.py             lazy model loading, warmup, readiness
    orchestrator.py         ingestion, routing, execution, traces
    router.py               deterministic and optional LLM planning
    imaging.py              image loading and pixel primitives
    backends/               CLIP, BLIP, optional VLM, planner adapters
    tools/                  caption, VQA, scene, grounding, counting, change, modality
    api.py                  FastAPI and demo-console routes
    ui.py                   HTML demo console
  connectors/image_fetcher/ optional satellite snapshot utility
  connectors/stac/         configurable STAC API catalog connector
  connectors/open_meteo/   weather, climate, and river-discharge adapters
  connectors/usgs_3dep/    USGS 3DEP single-point elevation observations
  satquery/platform/perception.py canonical query and observation pipeline
  ../tests/                 deterministic and acceptance tests
  ../docs/                  project documentation
  ../configs/catalogs/      example Earth Search collection configuration
  scripts/run_phase1.py    Phase 1 acceptance runner
  test_runs/phase1/         fresh output for future acceptance runs
  ../archive/reports/phase1/ historical acceptance reports
  ../archive/legacy/legacy_outer_modules/ quarantined historical duplicate modules
  pyproject.toml            package/build/test configuration
  requirements.txt          runtime dependencies
  requirements-dev.txt      pytest dependency
```

## Repository Audit: Clones and Duplicates

There is one canonical Python package root: `satquery-ai/satquery`.

The following historical duplicate modules were found at the outer workspace level and moved to `../archive/legacy/legacy_outer_modules/`:

```text
api.py
change.py
grounding.py
orchestrator.py
registry.py
router.py
```

They are historical reference only and are not imported by the active application.

Other similarly named files are not duplicate source roots:

- `satquery-ai/satquery_ai.egg-info/` is generated packaging metadata.
- `satquery-ai/connectors/` contains the optional image-fetching connector.
- `data/`, `scripts/`, `tests/`, and `test_runs/` are support directories; project documentation is in `../docs/`.
- The workspace-level `.venv` and `.env` remain outside the application package; the workspace environment template is in `../configs/.env.example`.
- The archived [`AUDIT_REPORT.md`](../archive/reports/AUDIT_REPORT.md) is a historical repository audit, not executable project code.

No conflicting `satquery` package entry point was found. The canonical CLI is `satquery-ai/satquery/__main__.py`, exposed through the `satquery` console script and `python -m satquery`.

## Known Limitations

- Practical models are general BLIP/CLIP checkpoints, not a trained remote-sensing detector.
- Grounding returns semantic regions, not verified object instances or segmentation masks.
- Counting is a lower-bound/estimate workflow and should not be presented as exact detection.
- Change detection resamples but does not geometrically register epochs.
- Modality analysis is a pixel heuristic with CLIP corroboration.
- Quality captioning is the slowest core path because it combines BLIP prompts, quadrant evidence, and scene analysis.
- Real results depend on checkpoint cache, hardware, image resolution, and external model availability.
- Confidence values are model scores and softmax masses, not calibrated probabilities.

## Canonical Commands

All commands below assume the canonical directory:

```powershell
cd satquery-ai
..\.venv\Scripts\python.exe -m satquery doctor
..\.venv\Scripts\python.exe -m satquery warmup
..\.venv\Scripts\python.exe -m satquery serve
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe scripts\run_phase1.py
```
