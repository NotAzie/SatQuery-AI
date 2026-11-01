# SatQuery AI Audit Report

Audit date: 2026-09-16

Audited root: `C:\Users\mazin\HACKATHON\SAT_QUERY`

Actual Python package root: `satquery-ai/`

## Executive verdict

SatQuery is a real, fairly complete prototype rather than a fake demo shell. It has a working orchestration model, real BLIP/CLIP inference paths, structured responses, a FastAPI surface, a browser console, an optional remote-sensing VLM path, and broad algorithmic tests.

It is not currently a reliable live SIH demo without preparation. The default models are large and lazy-loaded, CPU inference is slow, model availability is not equivalent to model readiness, and the full test suite is not green in the current environment. Several claims in the README are stronger than what has been demonstrated on real imagery. Grounding and classification are implemented, but their quality is bounded by zero-shot CLIP and expensive sliding windows rather than a remote-sensing detector.

The most important immediate facts:

- The core package is `satquery-ai/satquery`, not the outer `SAT_QUERY` directory.
- The project collects 156 tests.
- With the project virtual environment, the current full run was `154 passed, 2 failed`.
- The two failures are in `tests/test_engine_and_api.py`; previously downloaded real models made tests that expect no vision backend fail.
- Bare global `pytest` is also broken in the current shell because it resolves to a global installation missing `pygments.lexers._mapping`. Use `.venv\\Scripts\\python.exe -m pytest`.
- The recent CLIP structured-output fix is covered by a focused regression and the grounding/scene algorithm tests pass.
- A full real-image grounding CLI run loaded CLIP successfully but was too slow on CPU to complete during the audit. That is a demo risk, not proof that the corrected path is broken.

## 1. Current status

### What is working

The core request path is materially implemented:

1. Images are ingested from uploads or server-side paths.
2. Pillow/NumPy normalise images to RGB, resize oversized inputs, hash them, and attach modality evidence.
3. The router chooses a capability using deterministic rules and optionally an LLM planner for ambiguous queries.
4. The orchestrator constructs a shared vision suite, executes one primary tool, permits nested tool calls, caches results, and assembles a trace.
5. Tools return structured summaries, labels, regions, confidence values, warnings, and data payloads.
6. FastAPI exposes health, capabilities, config, warmup, multipart queries, JSON path queries, OpenAPI, and the HTML console.

The algorithmic test doubles are meaningful: they derive embeddings and captions from pixels, so tests exercise actual grounding, scene, change, and counting algorithms rather than returning canned answers.

### What is only partially working

- Practical BLIP/CLIP inference is real, but lazy model downloads and first-query latency are not controlled by the application.
- Grounding returns semantic regions, not object detections. A response region may contain several objects.
- Counting is an estimate assembled from semantic regions, area heuristics, and VQA. It is explicitly not verified instance counting.
- Change detection fuses radiometric difference and CLIP patch drift, but does not register images. Misalignment can dominate the result.
- Modality detection is a pixel heuristic with a CLIP corroboration, not a reliable sensor classifier.
- Strong RS-VLM and GeoChat paths are implemented as optional adapters, but their external checkpoint/source compatibility was not verified in this audit.
- Real-image end-to-end latency and answer quality were not established. The real grounding command loaded CLIP but did not finish in a practical CPU window.

### What is currently broken or risky

- The full test suite is not green after real model downloads. `test_engine_refuses_when_no_vision_backend_exists` and `test_capabilities_reflect_backend_availability` fail because the practical backend becomes available from the local model cache. This is test isolation failure and also exposes capability-state assumptions.
- `Tool.max_images` is declared on tools but `Tool.validate()` only checks `min_images`. Caption, scene, modality, and counting can receive multiple images and silently use the first; change detection can receive more than two and silently ignore later images.
- `SatQueryEngine.capabilities()` always marks modality analysis available, even when no vision backend exists. `answer()` can then refuse the same operation during backend construction.
- The API reads each upload fully with `await upload.read()` before application-level size validation. `SATQUERY_MAX_UPLOAD_MB` does not protect memory from an oversized multipart body.
- The outer `SAT_QUERY` directory contains duplicate modules such as `api.py`, `change.py`, `grounding.py`, `orchestrator.py`, `registry.py`, and `router.py`. They are not the installed `satquery` package and use relative imports that are invalid when run as top-level modules. This is confusing and creates a risk that someone runs or edits the wrong code.

## 2. Completed work by capability

Status meanings: Done means implemented and tested at the algorithm/application level; Partial means real but limited or runtime-dependent; Broken means a verified failure or misleading contract; Missing means not present.

| Area | Status | Evidence and honest assessment |
|---|---|---|
| Routing | Done / Partial | `satquery/router.py` has deterministic intent rules, target extraction, forced tools, and optional planner LLM fallback. It is strong for English keyword-shaped queries, but not a general language understanding layer. Ambiguous or unusual phrasing depends on an optional external LLM. |
| Orchestration | Done | `satquery/orchestrator.py` ingests, selects backends, routes, executes nested tools, caches, composes answers, and builds traces. The main request path is coherent. Image cardinality validation is incomplete because per-tool maximums are not enforced. |
| Captioning | Partial | `satquery/tools/caption.py` fuses BLIP prompt variants, quadrant captions, scene classification, modality, colour, and texture. It is real inference, but expensive and vulnerable to any nested scene/CLIP failure. Quality is generic unless a compatible strong RS-VLM is configured. |
| VQA | Partial | `satquery/tools/vqa.py` and `backends/hf_practical.py` use BLIP VQA and a CLIP cross-check for presence questions. It is a general VQA model, not a remote-sensing-specialised one, and numeric answers are not reliable object counts. |
| Scene / land-use classification | Partial | `satquery/tools/scene.py` uses a 47-label taxonomy, prompt ensembles, and 2x2 quadrant voting. The algorithm and test double pass. Real quality is zero-shot CLIP quality on overhead imagery; no calibrated validation set is present. |
| Grounding | Partial | `satquery/tools/grounding.py` performs multi-scale sliding-window CLIP scoring, contrast-set softmax, response-map accumulation, and connected components. It returns useful semantic regions in tests. It is not object detection, is CPU-expensive, and real-image completion time was not demonstrated in this audit. |
| Counting | Partial | `satquery/tools/counting.py` reports region count, area estimate, and VQA numeric answer with disagreement. This is honest but cannot meet a judge's expectation of verified ship/building instance detection. |
| Change detection | Partial | `satquery/tools/change.py` implements radiometric differencing, Otsu thresholding, semantic patch drift, fusion, and scene transition. It explicitly does not perform co-registration; arbitrary epochs can generate false change. |
| Optical / SAR handling | Partial | `satquery/imaging.py` and the modality tool compute chromaticity, texture/speckle, and CLIP evidence. Tests cover synthetic optical/SAR patterns. It is a heuristic and can be wrong on unusual optical, grayscale, multispectral, or compressed inputs. |
| API | Done / Partial | `satquery/api.py` exposes health, capabilities, config, warmup, multipart and JSON query routes, error handlers, and OpenAPI. Multipart files are fully buffered before validation; path access needs careful deployment configuration. |
| UI | Done / Partial | `satquery/ui.py` provides a usable demo console and the API serves it at `/`. Browser behavior and real model latency were not verified here. The UI can expose capability state that does not exactly match later backend readiness. |
| Image fetcher plugin | Done / Partial | `plugins/image_fetcher` is correctly outside core SatQuery. It supports coordinates, fallback geocoding through Nominatim/Photon, candidate output, Esri imagery, configurable zoom/output size, and tests. It depends on external services and has no offline/cache fallback; address coverage is still provider-dependent. |
| Configuration | Done / Partial | `satquery/config.py` has typed environment parsing, validation, dotenv fallback, redaction, device/dtype selection, model IDs, sandbox root, and limits. Packaging is inconsistent: `pyproject.toml` makes Torch/Transformers optional while `requirements.txt` treats them as required for practical usage. |
| Error handling | Done / Partial | `satquery/errors.py` gives structured codes, remediation, context, and API serialization. Unexpected tool faults are wrapped. Some readiness checks are optimistic and some runtime model/provider failures remain unavoidable. |
| Tests | Partial / Broken | 156 tests are collected across config, API/orchestrator, CLIP output extraction, plugin, imaging, router, and tools. Focused tests pass, but the complete suite currently has 2 failures caused by model-cache/environment coupling. README still claims 148 tests. |

No major capability in the requested product description is entirely missing. The gap is reliability and validated quality, not absence of code.

## 3. Biggest weak points

### Speed

This is the largest live-demo weakness.

- Default CLIP is `openai/clip-vit-large-patch14` and default caption/VQA checkpoints are large enough to create substantial CPU cost.
- Grounding sweeps up to `SATQUERY_GROUNDING_MAX_WINDOWS=320` windows across multiple scales. Each window requires a CLIP image forward pass, followed by text embeddings and response-map work.
- Captioning can run multiple BLIP prompts, four quadrant captions, scene classification, modality analysis, and nested work in one request.
- Models are lazy-loaded. The first query pays model download/load cost unless warmup is run on the exact demo machine.
- The recent real-image CLI run loaded CLIP but did not finish grounding in a practical audit window on CPU.

The application has a latency dial, but the default is not demo-safe on CPU.

### Answer quality and remote-sensing specificity

- Practical BLIP and CLIP are general-purpose checkpoints, not strong remote-sensing models.
- The taxonomy and prompt wording are domain-aware, but prompt wording cannot turn natural-image CLIP into a validated land-use classifier.
- No real labelled evaluation set, accuracy report, precision/recall, IoU score, or count error analysis exists.
- Confidence values are softmax masses/decoder-derived scores. They are documented as not calibrated, but a judge can still read them as confidence.
- VQA can hallucinate a number or object; counting correctly labels this risk but does not solve it.

### Grounding accuracy

- Sliding-window CLIP is semantic retrieval, not a detector. Window scale, stride, contrast set, percentile threshold, and downsampling directly control results.
- Small buildings, roads, ships, and dense urban structure can be merged or missed.
- A percentile threshold always selects candidate cells, so the extra spread/floor gate is important but still heuristic.
- Images above `SATQUERY_MAX_IMAGE_PX` are downsampled before grounding, which can destroy small-object evidence.

### Change detection

- `align_pair()` resamples to a common size but does not geometrically register the scenes.
- Seasonal differences, shadows, sensor angle, cloud cover, and crop timing can be reported as change.
- The code warns about this, but the core result remains vulnerable when inputs are not already aligned.

### Geocoding and image fetch quality

- The optional plugin is more capable than a one-off script, but Nominatim and Photon coverage varies by country and landmark.
- Esri imagery availability, date, cloud cover, licensing/usage constraints, and actual local resolution are external and not controlled by the plugin.
- The fetched JPEG is suitable as an input, but it is not guaranteed to be authoritative or sufficiently detailed for small-object analysis.
- There is no local tile cache or provider retry/backoff strategy beyond the bounded geocoder fallback behavior.

### Model and resource choices

- `clip-vit-large-patch14` is a poor default for a CPU-first student demo if response time matters.
- There is no automatic model-size profile such as demo/fast/quality.
- There is no memory budget, queue, concurrency limit, cancellation, or progress reporting for long inference.
- Image decompression limits are deliberately raised for aerial imagery, and the API buffers uploads before checking configured size; this increases denial-of-service and memory risk in a deployed service.

### Stability and packaging

- Readiness means imports/dependency availability, not successful model load or a completed inference smoke test.
- Test behavior changes when real Hugging Face weights are cached in the same environment.
- `requirements.txt`, `requirements-dev.txt`, and `pyproject.toml` describe overlapping but inconsistent installation paths.
- The outer duplicate Python modules are a serious source-tree hazard.
- The README's test count is stale: it says 148 while 156 are currently collected.
- The current shell's global `pytest` is broken; only the project virtual environment is reliable.

## 4. SIH demo risk

The things most likely to look bad in front of judges:

1. **The first query appears frozen.** Model downloads and large model loading happen on demand. Without a completed warmup on the demo machine, the UI may appear unresponsive.
2. **Grounding takes too long on CPU.** A normal `where are the buildings` request can trigger hundreds of CLIP windows. The audit could load CLIP but not finish the real-image sweep in a practical time.
3. **The answer is semantically plausible but spatially wrong.** Zero-shot CLIP windows can select roads, roofs, or texture patterns as buildings.
4. **Counting is challenged.** A judge asks how many buildings/ships are present and receives a lower bound plus VQA disagreement rather than a verified count.
5. **Change detection overclaims visually.** Two images that are not co-registered can produce large false change regions.
6. **A configured backend reports ready but fails on first use.** This is particularly relevant to optional strong/GeoChat paths and model cache/network problems.
7. **The plugin depends on live internet services.** Geocoding or imagery can fail during a presentation, and there is no offline fallback.
8. **Environment/setup confusion.** The actual package is nested in `satquery-ai`, the outer directory has duplicate modules, the global pytest is broken, and README setup/test counts are not fully synchronized.
9. **The UI may advertise a capability that cannot execute.** Modality is always marked available by `capabilities()` even when no vision backend is installed.
10. **Memory pressure is plausible.** Large BLIP/CLIP checkpoints, 2048-ish images, multiple crops, and batched windows are a poor combination for a modest laptop.

The demo should use curated, pre-downloaded images, pre-warm all models, reduce grounding windows, and avoid presenting counts as ground truth.

## 5. Priority roadmap

### 1. Must-fix now

1. Make the full suite deterministic: isolate or mock model availability in `test_engine_and_api.py`, clear model-dependent state between tests, and make the expected backend state explicit.
2. Enforce both `min_images` and `max_images` in `Tool.validate()`; reject extra images instead of silently ignoring them.
3. Fix `capabilities()` so every tool reflects the backend it actually needs. Modality should not be available without the required practical/CLIP path if it invokes that path.
4. Add an explicit demo profile: smaller CLIP/BLIP checkpoints, lower default grounding windows, and documented CPU/GPU settings.
5. Run `warmup` on the exact presentation machine and fail early with a clear readiness result if any model cannot load.
6. Remove or clearly quarantine the duplicate outer Python modules. Keep one authoritative package root.
7. Update README test counts and setup commands. Standardise on `.venv\\Scripts\\python.exe -m pytest` for Windows validation.
8. Add a real-image smoke test or manual acceptance script that asserts the CLI returns a structured result and regions within a bounded time on the target hardware.
9. Stream or cap multipart uploads before fully buffering them, especially if the API will be exposed beyond localhost.

### 2. Should improve next

1. Add model-size profiles and a per-request timeout/progress state for grounding.
2. Use a remote-sensing-pretrained CLIP or detector for the highest-value targets such as buildings, ships, roads, and aircraft.
3. Add geospatial registration or at least feature-based alignment before change detection.
4. Add a small labelled validation corpus from the intended SIH scenarios and report grounding IoU, scene accuracy, change precision, and counting error.
5. Add cached/offline imagery fixtures for the optional fetcher and a provider status message.
6. Improve target normalization and multilingual/compound query handling without making the router dependent on a live LLM.
7. Add structured model-load diagnostics to health/warmup: checkpoint cache state, disk space, approximate memory, and elapsed load time.
8. Make UI states explicit: loading, model not warmed, capability unavailable, timeout, partial result, and result confidence caveat.
9. Add a deployment security pass for path sandboxing, upload limits, CORS, request concurrency, and log redaction.

### 3. Can wait

1. More elaborate GeoChat/RS-VLM adapters and checkpoint-specific chat templates.
2. Better visual polish for the console.
3. More taxonomy labels beyond the scenarios that will actually be demonstrated.
4. Multi-provider satellite imagery selection and advanced GIS tiling.
5. Long-term cache persistence and distributed serving.

## 6. Scorecard

Scores reflect the current codebase, not the best possible configured environment.

| Dimension | Score | Reason |
|---|---:|---|
| Product completeness | 7/10 | The major user-facing paths exist: CLI, API, UI, routing, tools, trace, and plugin. Reliability and packaging still prevent an 8+. |
| Real vision quality | 5/10 | Real BLIP/CLIP forward passes exist and the algorithms are honest, but general-purpose checkpoints and no evaluation set limit confidence. |
| Speed / practicality | 3/10 | Lazy large-model downloads and 320-window grounding are not CPU-demo friendly. GPU performance was not verified. |
| Demo readiness | 4/10 | Curated images and warmup can make it presentable, but the current default path has long latency and environment/test instability. |
| Code quality | 7/10 | Clear modules, typed settings, structured errors, traceable orchestration, and meaningful tests. Duplicate source roots, max-image validation, and stale docs reduce the score. |
| Overall SIH readiness | 5/10 | Strong prototype foundation, not yet dependable under live judge-driven arbitrary images and questions. |

## Bottom line

The project has enough real implementation to demonstrate a credible prototype. It should not be presented as a reliable remote-sensing analyst or verified detector yet. The strongest demo story is: curated image, warmed models, deterministic routing, honest semantic regions, visible trace, and explicit caveats. The weakest story is: arbitrary judge image, cold CPU process, exact object count, or unregistered before/after imagery.

The highest-return work is operational: make the tests deterministic, make capability/readiness truthful, reduce inference cost, remove source-tree ambiguity, and validate against a small real dataset. Those changes matter more for the next demo than adding another model adapter.