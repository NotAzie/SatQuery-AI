# SatQuery AI

SatQuery AI is an interactive vision-language assistant for satellite and aerial imagery. A user supplies an image and a natural-language question; deterministic routing selects a specialist capability, real vision models analyze the pixels, and the response includes the answer, regions or labels, warnings, and an execution trace.

Problem statement: **SIH26167**  
Canonical Python package: `satquery-ai/satquery`  
Optional image fetcher: `satquery-ai/plugins/image_fetcher`

## Canonical Project Path

The only authoritative source tree is:

```text
C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai\
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

For this workspace, the existing virtual environment is one level above the canonical package:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m pip install -e .
..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Torch must match the machine. For a CPU installation, use the PyTorch CPU index when creating a new environment:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Copy `.env.example` to `.env` in the canonical directory and adjust model/cache settings as needed.

## Doctor, Warmup, and Readiness

`doctor` checks dependencies and configuration. It does not replace model warmup:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m satquery doctor
..\.venv\Scripts\python.exe -m satquery warmup
```

`warmup` loads the practical CLIP, captioner, and VQA models and reports `ready: true` only after successful loading. Health and capabilities distinguish installed dependencies from actually warmed models.

For a demo, warm up once and keep the API process alive so loaded models and caches are reused.

## CLI Usage

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai

..\.venv\Scripts\python.exe -m satquery ask "describe this scene" -i path\to\scene.jpg --trace
..\.venv\Scripts\python.exe -m satquery ask "what type of scene is this" -i path\to\scene.jpg --trace
..\.venv\Scripts\python.exe -m satquery ask "where are the buildings" -i path\to\scene.jpg --trace
..\.venv\Scripts\python.exe -m satquery ask "Is there water in this image?" -i path\to\scene.jpg --trace
..\.venv\Scripts\python.exe -m satquery ask "what changed" -i before.jpg -i after.jpg --trace
```

The demo console also has a **Fetch real satellite imagery from a location**
mode. Enter a place/address or coordinates, optionally set zoom, and submit a
question without selecting an image. The optional fetcher obtains the image and
the normal SatQuery engine analyzes it in the same request.

The response includes the routed intent, selected tools, model/backend, latency, trace steps, and semantic regions or scene labels.

## API and UI

Start the local API and demo console:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m satquery serve
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

## Phase 1 Reliability

Phase 1 established the operational baseline:

- Warmup genuinely loads CLIP, captioner, and VQA models.
- Health and capabilities report readiness rather than only import availability.
- Tool minimum and maximum image counts are enforced.
- Loaded model objects and grounding image embeddings are reused in persistent processes.
- The canonical source is `satquery-ai/satquery`; historical outer modules are quarantined under `legacy_outer_modules`.
- Deterministic tests do not depend on Hugging Face cache state.
- Phase 1 acceptance artifacts are saved under `test_runs/phase1/`.

Run the Phase 1 verification suite:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m pytest tests/test_phase1_acceptance.py -q
..\.venv\Scripts\python.exe scripts\run_phase1.py
```

For real-model acceptance and an archived report:

```powershell
..\.venv\Scripts\python.exe scripts\run_phase1.py --real --profile fast --timeout 45
```

## Phase 2 Verification

Phase 2 quality regressions cover the four core tools:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m pytest tests/test_phase2_quality.py -q
..\.venv\Scripts\python.exe -m pytest -q
```

Real-image checks use existing files under `data/fetched_images/`. The practical validation path warms one persistent engine, then runs:

- `describe this scene`
- `what type of scene is this`
- `where are the buildings`
- `Is there water in this image?`

These checks verify usefulness and stability, not calibrated remote-sensing accuracy.

## Optional Image Fetcher

The fetcher is deliberately outside the core product path:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m plugins.image_fetcher --place "VIT Chennai, Vandalur" --zoom 18
..\.venv\Scripts\python.exe -m plugins.image_fetcher --lat 12.842946 --lon 80.155410 --zoom 19
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
  plugins/image_fetcher/    optional satellite snapshot utility
  tests/                    deterministic and acceptance tests
  docs/                     Phase 1 test plan
  scripts/run_phase1.py    archived Phase 1 test runner
  test_runs/phase1/         generated test reports, not source code
  legacy_outer_modules/     quarantined historical duplicate modules
  pyproject.toml            package/build/test configuration
  requirements.txt          runtime dependencies
  requirements-dev.txt      pytest dependency
```

## Repository Audit: Clones and Duplicates

There is one canonical Python package root: `satquery-ai/satquery`.

The following historical duplicate modules were found at the outer workspace level and moved to `legacy_outer_modules/`:

```text
api.py
change.py
grounding.py
orchestrator.py
registry.py
router.py
```

They are not runnable entry points and should not be edited or imported. The quarantine also has no README now, so it cannot be mistaken for a second project guide.

Other similarly named files are not duplicate source roots:

- `satquery-ai/satquery_ai.egg-info/` is generated packaging metadata.
- `satquery-ai/plugins/` is an optional plugin namespace, not a second core package.
- `data/`, `docs/`, `scripts/`, `tests/`, and `test_runs/` are support directories.
- The outer `.venv`, `.env`, and `.env.example` are workspace-level environment files; run commands from `satquery-ai` so configuration and imports resolve predictably.
- The outer `AUDIT_REPORT.md` is a repository audit artifact, not executable project code.

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
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\.venv\Scripts\python.exe -m satquery doctor
..\.venv\Scripts\python.exe -m satquery warmup
..\.venv\Scripts\python.exe -m satquery serve
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe scripts\run_phase1.py
```
