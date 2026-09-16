# SatQuery AI

**An interactive vision-language assistant for multimodal remote sensing image analysis through text queries.**

Smart India Hackathon — problem statement **SIH26167**
Built by **Az**

---

Point SatQuery at a satellite or aerial image, ask a question in plain language, and get an answer derived from the pixels — along with a trace showing which capability produced it.

```
  User query + image(s)
          │
          ▼
  Task understanding  ──────►  deterministic rules, LLM only when ambiguous
          │
          ▼
  Tool selection
          │
          ▼
  Specialist vision tool(s)  ─►  real forward passes on the actual image
          │
          ▼
  Answer + execution trace
```

## What it does

| Capability | What it actually computes |
|---|---|
| **Captioning** | Prompt-ensembled BLIP captions fused with scene classification, quadrant captions, modality, colour statistics, and texture measures |
| **VQA** | BLIP-VQA answer, cross-checked on yes/no questions against an independent CLIP presence probe |
| **Scene / land-use** | CLIP zero-shot over a 47-label remote-sensing taxonomy with six-template prompt ensembling and 2×2 quadrant voting |
| **Grounding** | Multi-scale sliding-window CLIP scoring against a contrast set → spatial response map → connected components → ranked boxes |
| **Counting** | Grounded region count, an area-based instance estimate, and a VQA numeric answer, with the disagreement reported |
| **Change detection** | Illumination-robust radiometric differencing fused with CLIP semantic patch drift across two epochs, plus a named land-use transition |
| **Optical / SAR** | Modality inferred from chromaticity, speckle coefficient of variation, and histogram skew, corroborated by a CLIP probe |

## Install and run

```bash
git clone <your-repo> satquery-ai && cd satquery-ai
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate

pip install -r requirements.txt
# torch is listed there, but install the build matching your hardware:
#   CPU   pip install torch --index-url https://download.pytorch.org/whl/cpu
#   CUDA  pip install torch --index-url https://download.pytorch.org/whl/cu121

cp .env.example .env
python -m satquery doctor        # what is installed, what is missing, what to do
python -m satquery warmup        # optional: download and load models now
python -m satquery serve         # http://127.0.0.1:8000
```

`doctor` is the first thing to run on a new machine. It reports every dependency and backend, and prints the exact command for anything missing.

### Ask from the command line

```bash
python -m satquery ask "where are the buildings" -i scenes/tile_01.png --trace
python -m satquery ask "how many ships are in the harbour" -i port.png
python -m satquery ask "what changed" -i 2019.png -i 2024.png
python -m satquery ask "describe this scene" -i radar.tif -m sar --json
```

### Ask over HTTP

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -F "query=where are the buildings" \
  -F "files=@scenes/tile_01.png"
```

### Ask from Python

```python
from satquery import SatQueryEngine

engine = SatQueryEngine()
response = engine.answer("what land use is this?", image_paths=["tile.png"])

print(response.answer)
print(response.intent, response.tools_used, f"{response.latency_ms:.0f} ms")
for step in response.trace:
    print(f"{step.step:<28} {step.latency_ms:>8.1f} ms  {step.status.value}")
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Demo console |
| `GET` | `/api/v1/health` | Readiness, device, backends, dependencies, setup actions |
| `GET` | `/api/v1/capabilities` | What can run right now, and why anything cannot |
| `GET` | `/api/v1/config` | Effective configuration, secrets redacted |
| `POST` | `/api/v1/warmup` | Load models now rather than on first query |
| `POST` | `/api/v1/query` | Multipart: `query`, `files`, `modality_hint`, `force_tool` |
| `POST` | `/api/v1/query/json` | JSON body with server-side `image_paths` |
| `GET` | `/docs` | OpenAPI |

Every response carries the answer, the intent, the tools used, the backend, per-step latency, the regions with normalised and pixel boxes, and the full execution trace.

## Configuration

Everything is environment-driven; see `.env.example` for the annotated list. The settings that matter most:

- `SATQUERY_DEVICE` — `auto` picks CUDA → MPS → CPU.
- `SATQUERY_CLIP_MODEL` / `SATQUERY_CAPTION_MODEL` / `SATQUERY_VQA_MODEL` — swap in smaller checkpoints on constrained hardware.
- `SATQUERY_RSVLM_PATH` — enables the strong remote-sensing VLM path.
- `SATQUERY_RSVLM_KIND=geochat` — enables the optional adapter for an external GeoChat checkout.
- `SATQUERY_GEOCHAT_SOURCE_PATH` — path to that installed GeoChat source tree; it is not vendored.
- `SATQUERY_ROUTER` — `rules` for zero-variance deterministic routing, `hybrid` to consult an LLM only on ambiguous queries.
- `SATQUERY_GROUNDING_MAX_WINDOWS` — the main latency dial.
- `SATQUERY_IMAGE_ROOT` — sandbox for path-based access.

## The two backend paths

**Practical (default).** BLIP for captioning and VQA, CLIP for classification, grounding, presence, and semantic change. Fully implemented, downloads on first use, runs on CPU.

**Strong (optional).** Any remote-sensing VLM checkpoint set via `SATQUERY_RSVLM_PATH`. When present it takes over captioning and VQA, and CLIP continues to serve grounding and classification. The loader reads the checkpoint config and selects between vision2seq, causal-LM, and BLIP-2 style classes, then formats prompts using the checkpoint's own chat template where it ships one. For GeoChat checkpoints, set `SATQUERY_RSVLM_KIND=geochat` and point `SATQUERY_GEOCHAT_SOURCE_PATH` at an external GeoChat checkout. If the strong backend fails at runtime, captioning and VQA warn and retry with the practical backend.

Fallback is automatic and silent: strong if configured, practical otherwise. If neither is available, SatQuery raises a configuration error with setup instructions rather than answering from the language prior.

## What this is not

Being precise about this matters more than the feature list:

- **Grounding returns semantic regions, not object instances.** Two ships moored side by side are one region. Counts are reported as a lower bound with the caveat attached, and the area-based estimate and the VQA answer are shown alongside so disagreement is visible.
- **Change detection differences, it does not register.** Epochs are resampled to a common raster, not co-registered. If the inputs are not already aligned, misalignment dominates the result — and the tool says so in its warnings.
- **The modality call is a pixel heuristic**, reported with its evidence and overridable with `modality_hint`.
- **Confidence values are decoder likelihoods and softmax masses**, labelled as such, not calibrated probabilities.
- **The planning LLM never sees the image and never writes the answer.** It only selects a capability.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

148 tests covering configuration, image ingestion and sandboxing, the pixel primitives, routing and target extraction, every tool, the orchestrator, and the HTTP surface.

The tests do not require torch. They substitute backend doubles that compute embeddings and captions from **real pixel statistics**, so the production algorithms run against real image content — a blue patch in the top-left has to come back as a water region in the top-left. Only the learned weights are replaced.

## Layout

```
satquery/
  config.py         env-driven settings, .env parsing, validation
  errors.py         error hierarchy; every failure carries remediation steps
  schemas.py        pydantic request/response/trace models
  imaging.py        loading, validation, windows, Otsu, components, modality
  registry.py       lazy thread-safe model loading, device/dtype resolution
  taxonomy.py       land-use labels, target phrasings, contrast sets
  router.py         deterministic rules + optional LLM planning
  orchestrator.py   execution, nested tool calls, trace assembly
  api.py            FastAPI surface
  ui.py             demo console
  backends/         base interfaces, BLIP+CLIP, RS-VLM, planner LLM
  tools/            caption, vqa, scene, grounding, counting, change, modality
```

Nothing imports torch or transformers at module scope, which is what lets `doctor` report a missing dependency instead of failing to start.
