# Earth Perception verification map

This page replaces the earlier image-model optimization acceptance plan. It
maps current Earth Perception behavior to repository tests. It is not a Phase 1
sign-off and passing these tests is not scientific validation.

## Deterministic tests

Run from `satquery-ai/`:

```powershell
python -m pytest -c pyproject.toml ../tests/test_capability_matrix.py ../tests/test_perception.py ../tests/test_perception_modalities.py ../tests/test_perception_platform.py
python -m pytest -c pyproject.toml ../tests/test_stac_connector.py ../tests/test_open_meteo.py ../tests/test_earth_sources.py ../tests/test_nasa_firms.py ../tests/test_noaa_coops.py ../tests/test_usgs_3dep.py
python -m pytest -c pyproject.toml ../tests/test_stac_raster_sampling.py
```

The raster test requires `python -m pip install -e ".[raster]"`. Tests use
controlled fixtures and do not establish upstream service availability.

| Capability | Representative tests | Verification boundary |
|---|---|---|
| Capability declarations, modality routing, plan limitations | `test_capability_matrix.py`, `test_perception_modalities.py` | Verifies declared metadata and deterministic selection, not provider coverage. |
| Canonical acquisition, normalization, fusion, provenance | `test_perception.py`, `test_perception_platform.py`, `test_earth_sources.py` | Verifies fixture normalization and evidence retention, not scientific correctness of source products. |
| Source adapters | `test_stac_connector.py`, `test_open_meteo.py`, `test_nasa_firms.py`, `test_noaa_coops.py`, `test_usgs_3dep.py` | Verifies adapter contracts from deterministic responses; no live acceptance is implied. |
| Raster point sampling and summaries | `test_stac_raster_sampling.py` | Verifies supported local fixture operations and explicit constraints; no classification/index derivation. |
| Perception in the platform workflow | `test_platform_application.py`, `test_engine_and_api.py`, `test_phase1_acceptance.py` | Verifies integration surfaces. The phase1-named test module contains older image acceptance contracts and should not be mistaken for a perception certification. |

## Full project verification

Use [TESTING_GUIDE.md](TESTING_GUIDE.md) for installation, full suite, CI
scope, and optional model acceptance. The workflow in
`.github/workflows/platform-tests.yml` selects tests and is not equivalent to
the complete local test suite.

## Evidence needed for scientific evaluation

This plan does not define accuracy metrics or provide a labelled reference
dataset. Evaluating a product or method requires domain-appropriate reference
observations, documented label provenance, matching rules, sampling design,
license-compatible data, and declared acceptance criteria. Do not turn
software regression results into a scientific accuracy claim.
