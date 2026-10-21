# Testing and verification

The automated tests are in the repository-level `tests/` directory. Run from
`satquery-ai/`, where the package's pytest configuration sets import paths and
the test directory.

## Install and run

```powershell
python -m pip install -e ".[dev,geospatial]"
python -m pytest -c pyproject.toml
```

Raster tests additionally require `python -m pip install -e ".[raster]"`.
Hugging Face acceptance tests marked `real_acceptance` are excluded from the
default suite; they require compatible Torch/Transformers, configured models,
weights available locally or network access, and test image assets. Do not run
provider-backed tests against live services unless you intend to make network
requests.

For a fast focused check, choose the affected module, for example:

```powershell
python -m pytest -c pyproject.toml ../tests/test_platform_execution.py
python -m pytest -c pyproject.toml ../tests/test_perception.py ../tests/test_stac_connector.py
python -m pytest -c pyproject.toml ../tests/test_monitoring.py ../tests/test_execution_journal.py
```

The repository config defines the `real_acceptance` marker. The default test
command does not promise that every test uses no external assets; inspect
markers and fixtures when adding a test. Connector tests should use deterministic
HTTP fixtures/mocks and assert source metadata, errors, units, and provenance.

## CI scope

`.github/workflows/platform-tests.yml` runs the platform and perception
regressions plus the Python client, CLI, Earth Object, and monitoring tests on
Ubuntu with Python 3.12 and the development/geospatial extras. It is not a
full-suite gate, live provider integration, real-model acceptance, deployment
test, or scientific validation run. Run the complete local suite when practical
and report its exact command and outcome.
Ruff is not a project dependency and is not run by the checked-in workflow.

## Scientific verification boundary

Passing software tests establish behavior of the tested implementation and
fixtures. They do not validate a scientific method, dataset accuracy, physical
interpretation, or generalization. Scientific certification needs versioned
reference investigations and suitable truth data; those are not bundled as a
general benchmark corpus. See [benchmark status](BENCHMARKS.md).

## Useful test areas

- Contracts, configuration, registries, connector bootstrap: `test_platform_contracts.py`, `test_config.py`, `test_platform_bootstrap.py`.
- Planning and capability declarations: `test_capability_matrix.py`, `test_investigation_planner.py`, `test_investigation_intelligence.py`.
- Perception and adapters: `test_perception*.py`, `test_earth_sources.py`, `test_open_meteo.py`, `test_stac_connector.py`, `test_nasa_firms.py`, `test_noaa_coops.py`, `test_usgs_3dep.py`.
- Raster processing: `test_stac_raster_sampling.py`, with raster extras installed.
- Earth Objects and memory: `test_earth_objects.py`, `test_phase2_quality.py`, `test_scientific_memory_and_readiness.py`.
- Workflow persistence, history, monitoring, reports: `test_execution_journal.py`, `test_persistent_platform_history.py`, `test_monitoring.py`, `test_investigation_reports.py`.
- API/CLI/workspace composition: `test_engine_and_api.py`, `test_platform_application.py`, `test_cli_memory.py`.
- Image adapter contract: `test_hf_practical.py` uses a structured stub model, requires the optional `vision` extra, and skips cleanly when that stack is unavailable. It does not load pretrained weights; real-image/model checks use the separate `real_acceptance` marker.
