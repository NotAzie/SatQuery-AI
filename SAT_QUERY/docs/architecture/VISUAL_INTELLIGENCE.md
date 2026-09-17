# Stage 2 Visual Intelligence

Stage 2 adds a model-agnostic evidence layer above the Stage 1 EO data/raster engine.

## Detection

`Detection` stores label, confidence, pixel box, source, model/version, tile identity, optional geographic footprint, timestamp, and metadata. `Detector` is the provider contract. A lazy `GroundingDinoDetector` adapter targets the official Hugging Face Transformers Grounding DINO API, but no checkpoint is loaded by default. The application refuses detection requests when no provider is configured.

## Segmentation

`Segmentation` stores a boolean mask, label, confidence, source, model/version, optional geographic footprint, timestamp, and metadata. `Segmenter` is the provider contract. `Sam2Segmenter` is a lazy box-prompt adapter for SAM2. It is optional because SAM2 is heavy and the upstream project recommends GPU/WSL for Windows use. No generic mask is invented when the provider is absent.

## Large-scene infrastructure

`generate_tiles` creates overlapping image tiles. `non_max_suppression` and `merge_detections` remove duplicate boxes across overlapping windows. Providers can attach tile IDs and global pixel coordinates to evidence.

## Geolocation

`pixel_box_to_geo` uses the Stage 1 affine transform and CRS to create a polygon footprint. It returns `None` for non-georeferenced RGB images. No geographic coordinates are claimed without valid EO metadata.

## Measurement

`count_detections`, `measure_detections`, and `measure_mask` compute counts, pixel areas, geospatial areas, hectares, image fractions, and provenance. They delegate physical area to the Stage 1 raster engine. A model confidence score is never treated as a measurement, and missing georeferencing leaves physical area unavailable.

## Open-source decisions

Grounding DINO is the selected open-vocabulary detector because it has an Apache-2.0 license, a Transformers integration, CPU support, and a direct text-to-box API. It is not assumed to be EO-accurate without domain validation. SAM2 is the selected promptable segmenter because it supports box/point prompts and Apache-2.0 checkpoints, but its runtime requirements make it optional and cloud/GPU-oriented.
