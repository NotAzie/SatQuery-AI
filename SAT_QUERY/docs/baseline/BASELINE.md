# SatQuery AI Phase 0 Baseline

Baseline date: 2026-09-16
Baseline branch: `v1.0.0`
Baseline artifact commit: `0777e7d6515376d8b67a6aa8f814f9ee9f45ece3`
Baseline tag: `v0.1-baseline` (final tag commit includes the metadata update after this artifact commit)
Canonical package: `satquery-ai/`

## 1. Executive summary

SatQuery AI is an image-analysis prototype for satellite and aerial imagery. It accepts an RGB image and a natural-language question, routes the question to a specialist capability, runs BLIP/CLIP-based analysis plus deterministic pixel processing, and returns a structured answer with labels, semantic regions, confidence, warnings, and an execution trace.

The current system is operational for RGB image experiments and local demos. It is not a geospatial intelligence platform yet. It does not preserve CRS, geotransform, GSD, acquisition date, sensor metadata, NoData, original band structure, or native multispectral/SAR measurements. Its optical/SAR result is a pixel heuristic with optional CLIP corroboration. Its grounding result is semantic region localization, not object detection. Its change detector now performs bounded image-space alignment and correspondence refusal, but it is not a geospatial registration system.

The baseline is intentionally honest: the checked-in real imagery has no ground-truth labels, boxes, masks, or temporal annotations. The real-model benchmark therefore reports runtime and structured predictions, while task accuracy remains `not_evaluable`.

## 2. Current architecture

```text
User
  |
  v
FastAPI / CLI / browser console
  |
  v
SatQueryEngine
  |
  +--> image upload or server path
  |      |
  |      +--> Pillow decode and validation
  |      +--> RGB normalization and resize
  |      +--> SHA-256 and image metadata
  |      +--> modality heuristic
  |
  +--> QueryRouter
  |      +--> deterministic rules
  |      +--> optional planning LLM for ambiguous wording
  |
  +--> specialist tool
  |      +--> caption
  |      +--> VQA / presence
  |      +--> scene classification
  |      +--> grounding
  |      +--> counting
  |      +--> change detection
  |      +--> modality analysis
  |
  +--> shared VisionSuite and ModelRegistry
  |      +--> CLIP embeddings
  |      +--> BLIP captioning
  |      +--> BLIP VQA
  |      +--> optional RSVLM / GeoChat
  |
  +--> nested tool calls and LRU result cache
  |
  +--> structured ToolResult, warnings, trace, and QueryResponse
```

### Data flow

Images enter through multipart upload, server-side path access, or the optional location fetcher. `satquery.imaging` decodes and normalizes them. The configured image root can sandbox path queries. Oversized images are resized to the configured longest edge. The original dimensions and resize event are retained in the response.

### Control flow

`SatQueryEngine.answer()` performs ingestion, backend selection, routing, primary tool execution, nested tool calls, and final answer composition. Each tool validates its required image count. Tools share a process-local cache keyed by image digest, tool, and arguments.

### Model flow

`ModelRegistry` loads models lazily and retains them for the process lifetime. `warmup()` explicitly loads practical CLIP, BLIP captioning, and BLIP VQA. `health()` and `capabilities()` distinguish dependency availability from loaded readiness.

### Error flow

Expected errors are subclasses of `SatQueryError` and carry a code, detail, remediation list, and context. FastAPI serializes them as structured JSON. Invalid inputs, missing images, unavailable models, unsafe change pairs, and invalid routing values are refused rather than answered from text alone.

### API flow

`GET /` serves the browser console. Health, capabilities, config, and warmup are under `/api/v1`. Queries are available through multipart upload, JSON path requests, and optional location fetching. Each FastAPI application binds one engine instance so warmup and readiness refer to the same process-local registry.

### CLI flow

`python -m satquery doctor` reports dependencies and readiness. `warmup` loads models. `ask` runs a query against one or more paths. `serve` starts Uvicorn and the API/UI. A CLI process and a separately started server process do not share in-memory models.

## 3. Supported inputs and actual limits

| Input feature | Baseline status |
|---|---|
| JPEG, PNG, BMP, WebP, GIF, PPM, PGM | Implemented through Pillow |
| TIFF extension and Pillow-decodable TIFF | Partially implemented |
| RGB images | Implemented |
| Grayscale/single-band files | Converted to RGB; original band semantics are not preserved |
| High-bit-depth single-band images | Percentile-stretched into 8-bit RGB |
| Maximum image size | Longest edge defaults to 1536 pixels |
| Upload size | Application setting defaults to 40 MB; multipart data is read before application validation |
| Server-side paths | Implemented; sandbox available through `SATQUERY_IMAGE_ROOT` |
| CRS/geotransform/GSD | Not preserved or used |
| Acquisition date/sensor metadata | Not read from image metadata |
| Native multispectral bands | Unavailable; data is normalized to RGB |
| Native SAR | Unavailable as a native raster modality; grayscale/SAR-like RGB containers receive a heuristic classification |
| DEM/elevation | Not supported |
| NoData handling | Not implemented as geospatial NoData semantics |

## 4. Current models and provenance

| Function | Model/checkpoint | Baseline status |
|---|---|---|
| Captioning | `Salesforce/blip-image-captioning-large` | Real lazy-loaded BLIP inference; general-image checkpoint |
| VQA | `Salesforce/blip-vqa-base` | Real lazy-loaded BLIP inference; general-image checkpoint |
| Scene, grounding, presence corroboration | `openai/clip-vit-large-patch14` | Quality default; zero-shot general-image CLIP |
| Scene, grounding, presence corroboration | `openai/clip-vit-base-patch32` | Explicit fast profile |
| Optional strong caption/VQA | Configured RSVLM/GeoChat adapters | Optional and not active in the baseline environment |
| Optional query planner | OpenAI-compatible planner, default `gpt-4o-mini` | Not active; no API key configured |

Model revisions are not pinned in the current project. The baseline records model IDs but cannot claim exact checkpoint reproducibility beyond the local cache and Hugging Face repository state at run time. Model-card licenses and limitations are recorded in [OPEN_SOURCE_STACK.md](../opensource/OPEN_SOURCE_STACK.md).

Environment captured on the baseline machine:

- OS: Windows 11, build `10.0.26200`
- Python: `3.14.5`
- CPU: Intel64 Family 6 Model 186; no usable GPU reported by the host or Torch
- RAM: approximately 16 GB
- Torch: `2.14.0`
- Transformers: `5.17.0`
- FastAPI: `0.141.1`
- Pydantic: `2.13.5`
- NumPy: `2.5.3`
- Pillow: `12.3.0`
- HTTPX: `0.28.1`
- Pytest: `9.1.1`
- Accelerate: `1.15.0`
- SentencePiece: `0.2.2`

## 5. Capability matrix

| Capability | Status | Actual method | Output | Main limitation |
|---|---|---|---|---|
| Captioning | PARTIALLY IMPLEMENTED | BLIP prompt ensemble plus scene, modality, colour, texture, and quadrant evidence | Text summary and labels | General BLIP; no calibrated factual scoring |
| VQA | PARTIALLY IMPLEMENTED | BLIP VQA; CLIP whole-image/quadrant check for presence questions | Text answer, original question, evidence state | General VQA; open answers and counts can be wrong |
| Scene classification | APPROXIMATION | Zero-shot CLIP over a 47-label remote-sensing vocabulary with whole-image and quadrant fusion | Ranked labels, groups, mixture, stability | No supervised EO validation; labels are prompt-dependent |
| Grounding | APPROXIMATION | Multi-scale CLIP window scoring and connected components | Semantic regions and normalized boxes | Not object detection, segmentation, or instance localization |
| Counting | APPROXIMATION | Grounding regions, area heuristics, and VQA answer comparison | Estimate and disagreement | No verified instance count |
| Modality identification | APPROXIMATION | Channel spread, local variation, intensity skew, optional CLIP probe | Optical, SAR, or UNKNOWN with evidence | Does not identify sensor, bands, polarization, or product metadata |
| Change detection | PARTIALLY IMPLEMENTED | Radiometric difference, CLIP patch drift, bounded translation alignment, correspondence gate | Fused regions, transition labels, warnings | Not geospatial registration; no temporal ground truth |
| Segmentation | UNAVAILABLE | None | No masks | No segmentation backend |
| Area measurement | UNAVAILABLE/UNSAFE TO CLAIM | Pixel fractions only in some tool outputs | Relative image coverage | No GSD or CRS, so no physical area |
| Distance measurement | UNAVAILABLE | None | None | No geospatial coordinate system |
| Spectral analysis | UNAVAILABLE | RGB statistics only | Colour/texture descriptors | No native bands or calibrated reflectance |
| Temporal analysis | PARTIALLY IMPLEMENTED | Two-image image-space comparison | Change regions and warnings | Registration and acquisition semantics are limited |
| Planning | PARTIALLY IMPLEMENTED | Rule router and optional LLM tool selection | Query plan and rationale | No true multi-step agent planner |
| Verification | PARTIALLY IMPLEMENTED | Cross-checks and evidence warnings | Confidence, warnings, trace | Confidence is not calibrated probability |
| Provenance | PARTIALLY IMPLEMENTED | Model IDs, image hashes, trace | Structured response metadata | Model revisions and image provider metadata are incomplete |
| GeoJSON/GeoTIFF/maps/charts | UNAVAILABLE | JSON boxes only | Structured JSON and UI overlays | No geospatial export |

## 6. Test results

Command:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\..\.venv\Scripts\python.exe -m pytest -q
```

Result on 2026-09-16:

- Passed: `174`
- Failed: `0`
- Skipped: `2`
- Errors: `0`
- Warnings: dependency deprecations from Starlette/httpx and Pillow test construction

The two skipped tests are the opt-in real-model acceptance tests when the real marker is not enabled. The deterministic suite uses pixel-derived backend doubles for algorithmic coverage and does not claim real-model accuracy.

## 7. Real-model benchmark results

Benchmark command:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
..\..\.venv\Scripts\python.exe ..\benchmarks\baseline\run_benchmark.py --profile fast
```

Run ID: `20260916T145750Z`

- Fixture evaluated: `12-84295-80-15541-z18-20260916T091406Z.jpg`
- Queries: `6`
- Successful: `6`
- Failed: `0`
- Warmup/model load: `34.608 s`
- Warm query latency: minimum `765.398 ms`, median `3100.616 ms`, maximum `80690.679 ms`
- Accuracy metrics: `not_evaluable_without_ground_truth`
- Machine-readable records: [20260916T145750Z.jsonl](../../benchmarks/baseline/results/20260916T145750Z.jsonl)
- Machine-readable summary: [20260916T145750Z.summary.json](../../benchmarks/baseline/results/20260916T145750Z.summary.json)

The maximum query latency is dominated by captioning and its supporting work on CPU. The result is a runtime baseline, not a quality claim.

The real fixture set contains seven files and six unique SHA-256 contents. It includes place/coordinate-named optical JPEG snapshots, two identical Taj Mahal outputs, and no SAR or temporal pair with ground truth. The complete inventory and hashes are in [manifest.json](../../benchmarks/baseline/manifest.json).

## 8. Failure taxonomy

The baseline uses these categories for benchmark failures:

- `INVALID_INPUT`: unreadable, missing, unsupported, or malformed imagery
- `MODEL_UNAVAILABLE`: missing dependency, checkpoint, or model load failure
- `LOW_CONFIDENCE`: successful response whose evidence is too weak or ambiguous
- `NO_DETECTION`: a semantic target did not clear the grounding support gate
- `FALSE_DETECTION`: reserved for labeled evaluation analysis; not measurable in this fixture set
- `QUERY_MISMATCH`: invalid or under-specified query/tool request
- `UNSUPPORTED_CAPABILITY`: no registered capability for the requested operation
- `TEMPORAL_MISMATCH`: unsuitable image pair for change analysis
- `IMAGE_ALIGNMENT_FAILURE`: insufficient correspondence or unsafe aspect ratio
- `MODEL_DISAGREEMENT`: independent model/evidence paths conflict
- `INTERNAL_ERROR`: unexpected runtime/tool error

The current benchmark runner records structured exception categories and warnings. It does not convert a visually plausible answer into a success metric.

## 9. Known limitations and architectural gaps

### Model limitations

The practical checkpoints are trained for general image captioning, VQA, and image-text similarity. They are not validated remote-sensing models.

### Data limitations

The pipeline expects an RGB image. It does not preserve multispectral bands or native SAR data.

### Representation limitations

Pillow/NumPy arrays replace geospatial raster semantics. CRS, geotransform, GSD, dates, and sensor metadata are absent from the core image object.

### Algorithm limitations

Grounding is CLIP semantic localization. Change detection uses image-space alignment and correspondence checks, not geospatial registration. Counting is an estimate.

### Scientific limitations

Pixel fractions are not physical area. Confidence values are model-derived or heuristic scores rather than calibrated probabilities. The checked-in real imagery lacks task labels and annotations.

### Infrastructure limitations

Large models are lazy-loaded and CPU latency is high. The optional fetcher depends on live external services. Multipart uploads are buffered before application-level size validation.

### Agent limitations

The router chooses a capability and can invoke nested sibling tools, but there is no general agent planner, iterative verification loop, or clarification dialogue.

## 10. Reproduction instructions

1. Checkout the immutable tag `v0.1-baseline`.
2. From `satquery-ai`, use `..\..\.venv\Scripts\python.exe` in this workspace or create a fresh Python `>=3.10` environment.
3. Install runtime and development dependencies from `requirements.txt`, `pyproject.toml`, and `requirements-dev.txt`.
4. Run the deterministic suite command above.
5. Run the benchmark command above. It downloads models if they are not already cached.
6. Inspect JSONL results under `benchmarks/baseline/results/`.

The benchmark configuration is recorded in [configs/baseline.yaml](../../configs/baseline.yaml). The fixture checksums are recorded in [manifest.json](../../benchmarks/baseline/manifest.json). The current benchmark is reproducible as a smoke/runtime run; scientific accuracy reproduction requires adding licensed labeled data and pinning model revisions.

## 11. Future replacement candidates

These are recorded for later phases only and are not implemented by Phase 0:

- TorchGeo for geospatial dataset, CRS, resolution, and multispectral handling.
- torchgeo-bench for repeatable foundation-model and downstream task evaluation.
- Remote-sensing pretrained encoders for scene and grounding quality.
- A real object detector/segmenter for instance localization and counting.
- Geospatial registration and raster tooling for temporal change analysis.
- Licensed labeled EO datasets for accuracy, IoU, change F1, and modality evaluation.

## 12. Baseline completion status

- [x] Current code inspected and preserved as the reference system
- [x] Existing automated suite executed
- [x] Real-model smoke benchmark executed where local models and fixtures were available
- [x] Architecture and data/control/model/error flows documented
- [x] Capability matrix documented
- [x] Baseline configuration created
- [x] Fixed query set created
- [x] Fixture manifest and hashes recorded
- [x] Ground-truth absence explicitly recorded
- [x] Runtime metrics saved as JSONL and summary JSON
- [x] Open-source inventory created
- [x] Reproduction commands documented
- [ ] Scientific task metrics: blocked by absence of licensed ground truth
- [ ] Model revision pinning: blocked by current configuration not recording revisions
