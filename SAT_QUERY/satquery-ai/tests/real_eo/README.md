# Real EO Acceptance Test

This is an explicit, isolated acceptance harness for freshly fetched Sentinel-2 L2A imagery. It does not modify or replace the existing Stage 2 acceptance tests.

## Run

From `satquery-ai`:

```powershell
..\..\.venv\Scripts\python.exe tests/real_eo/run_real_eo_test.py
```

The runner fetches a new catalog item and writes all test-specific data/results under this directory. It never falls back to `data/fetched_images`.

Environment variables:

- `SATQUERY_TEST_AOI`: `min_lon,min_lat,max_lon,max_lat`; default is a public Chennai AOI.
- `SATQUERY_TEST_START`: ISO date; default is 30 days before today.
- `SATQUERY_TEST_END`: ISO date; default is today.
- `SATQUERY_TEST_MAX_CLOUD`: maximum `eo:cloud_cover`; default `35`.
- `SATQUERY_TEST_COLLECTION`: default `sentinel-2-l2a`.
- `SATQUERY_TEST_STAC_URL`: default Microsoft Planetary Computer STAC API.
- `SATQUERY_DEVICE`: `cpu` by default for this harness.

This is deliberately opt-in: it downloads a fresh EO product and may lazily
download model checkpoints. It always exercises `IDEA-Research/grounding-dino-tiny`
and `facebook/sam2.1-hiera-tiny`; it does not use mocks or the legacy JPEG.
If required, install the isolated extras first:

```powershell
pip install -r tests/real_eo/requirements.txt
```

## Outputs

- `data/raw/`: signed source metadata only
- `data/processed/`: freshly fetched georeferenced four-band GeoTIFF
- `results/report.json`: machine-readable report
- `results/report.md`: human-readable report
- `results/evidence/`: rendered detector/segmentation overlays

No old JPEG is accepted as a fallback. If STAC credentials, asset authorization, network access, or model dependencies are unavailable, the report records `BLOCKED` and the runner exits nonzero.
