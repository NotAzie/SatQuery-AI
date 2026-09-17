# Stage 2 Real Inference Acceptance

Run date: 2026-09-17

Command:

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
$env:SATQUERY_DEVICE = "cpu"
..\..\.venv\Scripts\python.exe scripts\stage2_real_acceptance.py
```

## Input

- File: `data/fetched_images/12-84295-80-15541-z18-20260916T091406Z.jpg`
- Source: existing Esri World Imagery snapshot in the Phase 0 fixture set
- Size: 2048 x 2048 RGB JPEG
- CRS/transform: unavailable in JPEG; no geographic coordinates or physical area were claimed

## Detector

- Model: `IDEA-Research/grounding-dino-tiny`
- API: Hugging Face Transformers `AutoModelForZeroShotObjectDetection`
- Prompt labels: building, water, road, vehicle
- Device: CPU
- Model loading and inference: completed
- Inference time: 43.038 seconds
- Output: 18 valid boxes after coordinate normalization
- Classes: water 1, building 14, road 3
- Outputs include model ID, source, confidence, pixel box, timestamp, and measurement provenance

The output is genuine open-vocabulary detector output. It is not treated as EO-validated accuracy; Grounding DINO's official zero-shot benchmarks are general/open-world benchmarks, not a SatQuery EO validation set.

## Segmenter

- Model: `facebook/sam2.1-hiera-tiny`
- API: Hugging Face Transformers `Sam2Model`/`Sam2Processor`
- Prompt: first three detector boxes
- Device: CPU
- Inference time: 22.410 seconds
- Output: 3 boolean masks
- Mask confidences: approximately 0.714, 0.712, 0.713
- Pixel counts: 130,052; 21,045; 9,582

Masks were postprocessed to the original 2048 x 2048 image dimensions and measured deterministically.

## Evidence output

- Rendered overlay: `artifacts/outputs/stage2-12-84295-80-15541-z18-20260916T091406Z.jpg`
- Structured report: `artifacts/outputs/stage2-real-acceptance.json`

These files are runtime artifacts and are intentionally ignored from Git. The acceptance script is versioned at `satquery-ai/scripts/stage2_real_acceptance.py`.

The same configured providers were also exercised through `SatQueryEngine`:

- `detect buildings`: `OBJECT_DETECTION`, Grounding DINO, 21 real detections.
- `segment buildings`: `SEGMENTATION`, Grounding DINO box prompts followed by SAM2, 3 real masks.

## Resource behavior

- Grounding DINO checkpoint download: approximately 689 MB model file
- SAM2 Tiny checkpoint download: approximately 156 MB model file
- CPU inference completed on the development laptop
- GPU is recommended for interactive use; CPU latency is not UI-friendly
- Hugging Face cache on Windows operates without symlinks in this environment, increasing cache disk usage

## Measurement limitation

The input is a fetched RGB JPEG, not a georeferenced GeoTIFF/COG. Pixel counts, pixel boxes, image fractions, and confidence are available. Physical area, hectares, km2, and geographic footprints are unavailable and were not invented. Geo-referenced measurement is covered separately by deterministic synthetic GeoTIFF tests.
