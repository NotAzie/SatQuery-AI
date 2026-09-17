# Tiled EO Real-Inference Experiment

Isolated experiment only. It does not replace the Stage 2 pipeline or modify Phase 0.

Default run uses the existing Esri World Imagery export provider at zoom 19 with a 2x2 grid and 20% geographic overlap. Each tile is freshly requested; no old JPEG is resized or reused.

```powershell
cd C:\Users\mazin\HACKATHON\SAT_QUERY\satquery-ai
$env:SATQUERY_DEVICE = "cpu"
$env:SATQUERY_TILE_ROWS = "2"
$env:SATQUERY_TILE_COLS = "2"
$env:SATQUERY_TILE_OVERLAP = "0.20"
$env:SATQUERY_TILE_ZOOM = "19"
$env:SATQUERY_TILE_WIDTH = "1024"
$env:SATQUERY_TILE_HEIGHT = "1024"
..\..\.venv\Scripts\python.exe tests/real_eo_tiled/run_tiled_test.py
```

Outputs are ignored by Git under `tiles/`, `images/`, `outputs/`, and `reports/`.
The provider's native mosaic GSD varies by location; the report compares actual requested bounds and returned affine resolutions and does not equate zoom with guaranteed native resolution.
