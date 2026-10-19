# SatQuery development setup

The runnable Python application lives in `satquery-ai/`. The parent
`SAT_QUERY/` folder holds documentation, platform configuration, and tests.
The package requires Python 3.10 or newer; Python 3.11 or 3.12 is recommended.

## Install on Windows

Run these commands in PowerShell from the repository root:

```powershell
cd C:\Users\mazin\SatQuery-AI\SAT_QUERY\satquery-ai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
python -m pip install -r requirements-dev.txt
```

If PowerShell blocks virtual environment activation, use the environment's
Python directly, for example `\.venv\Scripts\python.exe -m satquery doctor`.
Install a PyTorch build appropriate for the machine when the default wheel is
not suitable. For CPU-only systems, install the CPU wheel before installing
the remaining requirements:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Copy `satquery-ai/.env.example` to `satquery-ai/.env` if you want to change
model, device, cache, or image-root settings. Defaults are provided.

## Start SatQuery

Check local dependencies and model configuration:

```powershell
python -m satquery doctor
```

The first model warmup downloads the configured CLIP, captioning, and VQA
weights. Skip it to download lazily on the first image request:

```powershell
python -m satquery warmup
python -m satquery serve
```

Open <http://127.0.0.1:8000/> for the console or
<http://127.0.0.1:8000/docs> for the HTTP API. To try the command line with
an image:

```powershell
python -m satquery ask "Describe this scene" -i C:\path\to\scene.jpg --trace
```

The image capability now runs inside the platform execution engine. Its
response includes mission, investigation, and execution IDs so developers can
inspect the lifecycle through the platform API.

## Keep mission and investigation history across restarts

The default local profile uses process-memory storage to avoid creating files
without an explicit choice. To retain missions, investigations, Earth Memory
artifacts, and execution outputs on one machine, create a platform config file
such as `satquery-platform.json` in the repository root:

```json
{
  "storage": {
      "earth_memory_path": ".satquery/platform.sqlite"
  }
}
```

Start the server with that configuration:

```powershell
python -m satquery serve --platform-config ..\satquery-platform.json
```

The path is resolved from the server's current working directory. The same
SQLite database stores Earth Memory, mission/investigation lifecycle state, and
the execution journal. Use `storage.lifecycle_path` to separate lifecycle
records and `storage.execution_path` to separate execution records. The API and
browser mission explorer can inspect records after server restarts. Successful task checkpoints
are restored only when the exact workflow fingerprint and registered output
codec versions match. Resume an interrupted investigation with
`python -m satquery investigation resume <investigation-id>`; the CLI/API report
when prior task side effects were not declared safe to replay. This is durable
single-host local storage, not a multi-process or distributed database.

## Run Earth Perception

Earth data adapters are loaded only when explicitly listed in a connector
manifest. This avoids opening network connections or silently enabling data
sources at application startup. The repository includes a starter manifest:

```powershell
$env:SATQUERY_CONNECTORS_CONFIG = "..\configs\connectors.example.json"
python -m satquery platform inspect
python -m satquery platform capabilities
```

For disaster-modality active-fire observations, obtain a NASA FIRMS MAP_KEY and
provide it through the environment. Add this entry to the configured connector
manifest, omitting the credential from JSON:

```powershell
$env:SATQUERY_NASA_FIRMS_MAP_KEY = "<your-map-key>"
```

```json
{
  "implementation": "nasa_firms",
  "configuration": {"source": "VIIRS_NOAA21_NRT"}
}
```

FIRMS requests require a 2D geographic bounding box and a time interval no
longer than five calendar days. Its detections are thermal anomalies; they do
not by themselves establish fire cause or impact.

Discovery is an explicit network operation. For example, discover STAC
collections, then inspect their declared dataset metadata:

```powershell
python -m satquery platform discover earth-search
```

Create an `earth-query.json` file with a canonical query, for example:

```json
{
  "point": [80.15, 12.84],
  "requested_variables": ["air_temperature_2m"],
  "requested_dataset_ids": ["weather-forecast"]
}
```

Plan locally before making a live request:

```powershell
python -m satquery earth plan earth-query.json
python -m satquery earth observe earth-query.json
```

The example manifest also enables the USGS Water Data daily discharge adapter.
Its query must select a daily `statistic_id` explicitly and provide either a
monitoring location or a CRS84 bounding box. For example, `00003` selects the
daily mean in the USGS catalog; SatQuery does not assume that statistic when
the user leaves it unspecified:

```json
{
  "bbox": [-105.2, 39.4, -104.8, 39.9],
  "crs": "OGC:CRS84",
  "temporal_start": "2024-01-01T00:00:00Z",
  "temporal_end": "2024-01-31T00:00:00Z",
  "requested_variables": ["river_discharge"],
  "requested_dataset_ids": ["usgs-daily-values-river-discharge"],
  "filters": {"statistic_id": "00003"}
}
```

Results preserve the provider's units, approval status, qualifier, timeseries
identity, and source feature. The connector limits each request to 366 days
and a configured maximum record count. Daily station observations do not
represent spatially continuous river discharge.

The API exposes the same operations under `/api/v1/platform/earth/plan` and
`/api/v1/platform/earth/observe`. The Earth capability matrix is available at
`/api/v1/platform/earth/capabilities` and in the CLI. It distinguishes
registered, declared-but-not-loaded, unavailable, and unregistered modalities.
Unknown metadata stays unknown: asset references are not a guarantee that
assets can be opened, and missing forecast, quality, uncertainty, or confidence
metadata is not inferred. The API also exposes registered modalities,
connectors, datasets, missions, and investigations. The example manifest
registers adapters; it does not guarantee upstream availability, data access,
or asset downloads.

## Run deterministic tests

From `satquery-ai/`:

```powershell
python -m pytest -c pyproject.toml ..\tests\test_platform_application.py ..\tests\test_platform_*.py ..\tests\test_perception*.py ..\tests\test_stac_connector.py ..\tests\test_open_meteo.py ..\tests\test_earth_sources.py ..\tests\test_usgs_3dep.py -m "not real_acceptance"
```

The model-download and real-source acceptance checks are separate from this
deterministic suite.

## Sample declared STAC raster bands

Raster assets remain metadata references by default. Install the optional
reader before requesting pixel values:

```powershell
python -m pip install -e ".[raster]"
```

Discover the configured STAC connector's collections first. A collection is
advertised as point-sample capable only when its metadata declares raster
bands. Then use a structured EarthQuery with an exact point, the requested
band names, and `asset_sampling: "point"`:

```json
{
  "point": [12.4, 41.9],
  "crs": "OGC:CRS84",
  "requested_dataset_ids": ["sentinel-2-l2a"],
  "requested_variables": ["red", "near_infrared"],
  "asset_sampling": "point"
}
```

This reads the pixel containing the point from compatible HTTPS assets. The
result is a separate point-supported observation linked to the STAC scene.
SatQuery applies only declared band scale/offset values, preserves the source
asset metadata, and leaves uncertainty absent unless the source supplies it.
No vegetation index, area average, reprojection choice, or uncertainty is
invented. Unsupported or ambiguous band mappings fail explicitly. HTTP and
local-file assets are not opened by the remote connector.

Polygon analysis can be requested with `raster_analysis: "zonal_descriptive"`,
Polygon/MultiPolygon `geometry`, requested variables, and explicit
`raster_pixel_selection` (`"pixel_center"` or `"all_touched"`). By default,
statistics weight each selected cell equally. An explicit
`"raster_weighting": "geodesic_cell_area"` additionally computes ellipsoidal
area-weighted numeric summaries and categorical area fractions for unrotated
geographic grids. It requires both the `raster` and `geospatial` extras and
rejects projected or rotated grids rather than treating map coordinates as
ground area. Both summaries use full selected cells; boundary cells are not
fractionally clipped. These are descriptive statistics and do not estimate
measurement uncertainty. Numeric/categorical semantics must be
resolvable from the ontology, explicit band `measurement_kind`, or query
`raster_semantics` (for example, `{"red": "numeric"}` for a declared red band).

## Persist Earth Memory locally

Earth Memory is in-process by default. To retain its immutable artifact index
across restarts, configure a local SQLite file before starting the platform:

```powershell
$env:SATQUERY_PLATFORM__STORAGE__EARTH_MEMORY_PATH = "..\data\earth-memory.sqlite"
python -m satquery serve
```

The parent directory is created when the repository opens. The SQLite adapter
uses transactions, WAL mode, schema versioning, content checks, and deterministic
literal search; it does not provide multi-host replication, encryption, or
semantic search. Treat the database as research data: it can contain complete
investigation and observation payloads, so choose its location and filesystem
access controls accordingly. Leaving the setting unset keeps the in-memory
repository used by tests and ephemeral local sessions.
