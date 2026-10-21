# Earth Perception implementation boundary

This file replaces the former dated completion verdict. It is a current
summary of implemented behavior, not a phase sign-off. For source-family
coverage and limitations see [supported datasets](../datasets/SUPPORTED_DATASETS.md)
and the detailed [Earth Perception guide](Earth_Perception.md).

## Working paths

- Modality-first capability selection and deterministic dataset/connector
  discovery from configured declarations.
- Canonical EarthQuery, observation, measurement, asset, quality, and
  provenance contracts; ontology-aware normalization preserves original
  metadata and avoids ambiguous alias resolution.
- Configured adapters for STAC, NASA Earthdata CMR, NASA POWER, NASA FIRMS,
  Open-Meteo, OpenStreetMap, USGS 3DEP, USGS Water, and NOAA CO-OPS.
- Source-aware observation fusion, conflict diagnostics, caching, async
  streaming, connector health diagnostics, and explicit live discovery paths.
- Optional raster point sampling, polygon zonal summaries, and caller-mapped
  categorical component polygonization with provenance.
- Mission/investigation integration, dataset/capability inspection, API, CLI,
  workspace, deterministic tests, and Earth Memory lineage.

## Limits that remain

Connector coverage is product- and request-specific. Provider declarations
are not live availability or guaranteed coverage. Many Earth domains have
only generic STAC discovery or narrow station/point support. No comprehensive
Earth catalog, automatic asset download, broad raster cube, cross-CRS
resampling/mosaicking, spectral index library, or general classification
pipeline is bundled. Earth Object extraction uses explicit candidate records
and caller-supplied categorical mappings; it is not general scene
understanding. Unknown units, coverage, uncertainty, quality, and temporal
support remain unknown rather than guessed.

The implementation is therefore useful for configured real-source
investigations but should not be represented as globally comprehensive or as
a validated remote-sensing science engine. No completion percentage is
maintained here. The exact current boundary is centralized in
[implementation status](../IMPLEMENTATION_STATUS.md).

## Verification evidence

The repository contains deterministic fixture tests for perception planning,
normalization, connectors, raster sampling, provenance, and runtime
integration. The current CI workflow runs a selected subset, not the complete
suite and not live provider or scientific-validation tests. See
[testing guide](../testing/TESTING_GUIDE.md).
