# SatQuery development setup

The runnable Python application lives in `satquery-ai/`. The parent
`SAT_QUERY/` folder holds documentation, platform configuration, and tests.
The package requires Python 3.10 or newer; Python 3.11 or 3.12 is recommended.

## Install on Windows

Run these commands in PowerShell from the repository root:

```powershell
cd .\satquery-ai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,geospatial]"
```

This installs the platform and development/geospatial dependencies without
the optional image models. Install `python -m pip install -e ".[raster]"` for
documented raster processing. Install `python -m pip install -e ".[vision]"`
for image models; `.[large]` provides additional optional model-loading
packages. The legacy `requirements.txt` includes the vision stack and is not
the minimal platform installation.

If PowerShell blocks virtual environment activation, use the environment's
Python directly, for example `..\.venv\Scripts\python.exe -m satquery doctor`
from the repository root, or `\.venv\Scripts\python.exe -m satquery doctor`
from `satquery-ai/`.
If you install the optional `vision` extra, select a PyTorch build appropriate
for the machine. For a CPU-only install, install the CPU wheel before the
`vision` extra:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e ".[vision]"
```

From `satquery-ai/`, copy `.env.example` to `.env` if you want to change model,
device, cache, or image-root settings. Defaults are provided.

## Install on Linux or macOS

From the repository root, create an environment and install the package in
editable mode:

```sh
cd satquery-ai
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,geospatial]"
```

For the documented raster operations, install the optional `raster` extra as
well. For the legacy image models, install the optional `vision` extra and
ensure the selected PyTorch wheel matches the host. Platform API/CLI Earth
investigations do not require the `vision` extra. Run
`python -m satquery doctor` to inspect local setup, then
`python -m satquery serve` to start the application.

Manifest and storage paths are relative to the process working directory.
Connector implementations remain disabled until `SATQUERY_CONNECTORS_CONFIG`
points to a manifest. See the following connector section for example setup.

## Start SatQuery

Check local dependencies and model configuration:

```powershell
python -m satquery doctor
```

The Earth Intelligence API and workspace do not require vision models. The
optional warmup command loads configured CLIP, captioning, and VQA weights for
the retained image-analysis capability; that may download model files. You can
skip warmup and let the image path load models lazily on its first request:

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
SQLite database stores Earth Memory, mission/investigation lifecycle state,
the execution journal, and the append-only scientific audit trail. Use
`storage.lifecycle_path`, `storage.execution_path`, or `storage.audit_path` to
place those records in separate SQLite databases. The API and
browser mission explorer can inspect records after server restarts. Method
certification transitions and complete benchmark reproducibility reports are
restored from verified audit history and remain bound to the implementation
digest that was validated. Older benchmark audit summaries that omitted the
report content cannot restore a certification; the affected method version is
blocked from emitting findings and a replacement method version must be
independently validated. Successful task checkpoints
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

The optional Esri World Imagery point adapter can also be explicitly enabled
with the `image_fetcher` manifest implementation. It writes acquired images to
its configured local `output_dir`; the imagery provider and geocoding service
terms and availability apply:

```json
{
  "connectors": [
    {
      "implementation": "image_fetcher",
      "configuration": {"output_dir": ".satquery/fetched-images"}
    }
  ]
}
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

The same connector operations are available from the CLI; passive health only
reads local metrics, while `probe` and `discover` explicitly contact providers.
The browser workspace also lists registered datasets, searches their metadata,
and exposes those same connector actions:

```powershell
python -m satquery connectors
python -m satquery connectors health
python -m satquery connectors probe earth-search
python -m satquery connectors discover earth-search
python -m satquery datasets --query "surface temperature"
```

For an explicitly selected NOAA CO-OPS connector, find station candidates
inside a CRS84 bounding box without acquiring observations or choosing a
nearest station:

```powershell
python -m satquery connectors stations noaa-coops-water-level --bbox -123 36 -121 38
```

The station candidate list reports metadata from the provider catalog. A
station's presence does not establish that requested data are available or
representative of the area; choose a station ID explicitly in the subsequent
EarthQuery.

While an investigation is executing, follow its durable task events from
another terminal:

```powershell
python -m satquery investigation events <investigation-id>
```

The stream replays retained journal events and closes after the execution
completion event. It does not start or resume execution.

The workspace's Earth Object panel includes a local SVG locator view, and
canonical GeoJSON can be exported without adding a mapping-library dependency:

```powershell
python -m satquery objects geojson --investigation-id <investigation-id>
```

Only valid geometries with a declared WGS 84 CRS are included. Other geometry
records are returned in the export's `satquery:omitted_objects` diagnostics;
SatQuery does not guess their CRS or reproject them.

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

For categorical class rasters, investigation EarthQueries can additionally
specify `raster_component_extraction` with exact source-band class codes,
caller-provided object types, connectivity, AOI pixel selection, and component
limits. The platform polygonizes the encoded classes; it does not classify
imagery or validate source labels. See the example in the API reference.

Recurring observations use the same structured EarthQuery and investigation
execution path. Create a schedule from the workspace or API, then run due work
with `satquery monitor run-due`. To enable the API process's local polling loop,
configure `monitoring.enabled`, `monitoring.poll_interval_seconds`,
`monitoring.max_runs_per_tick`, and `monitoring.max_concurrency` in the platform configuration.
`monitoring.max_triggered_investigations_per_tick` independently bounds the
number of rule-triggered follow-up investigations dispatched by a scheduler
cycle (default 5).
`monitoring.lease_seconds` sets the worker lease and heartbeat interval. Due runs
are claimed deterministically and dispatched with that concurrency bound.
Schedule definition revisions change only when user-controlled schedule state
changes; each run retains the exact definition revision that scheduled it.
Expired worker leases are recorded as failures and are not automatically
re-acquired, since SatQuery cannot know whether an upstream acquisition completed
before the worker stopped. Inspect scheduler state with `satquery monitor health`
and the append-only journal with `satquery monitor events`. The workspace and
`satquery monitor notifications` expose a durable local inbox for partial and
failed runs; acknowledge an item with `satquery monitor acknowledge <id>`. A
monitoring event page includes `next_cursor`; load older history with
`satquery monitor events --cursor <next_cursor>`. The API offers the same
keyset pagination through `/api/v1/platform/monitoring/events/page`. A
schedule defaults to `skip_while_running`, which lets missed interval handling
coalesce future work while an acquisition remains active; `allow` can be chosen
when overlapping runs are explicitly desired. External message delivery needs
an owner-selected channel and credentials.
Revise a schedule using the API's `PATCH` endpoint or a JSON patch file with
`satquery monitor update <schedule-id> --update-file <path>`; the inspected
`expected_revision` is required so concurrent operator edits cannot silently
overwrite each other.
When `monitoring.enabled` is true under the `production` profile, configuration
validation requires a durable monitoring, Earth Memory, lifecycle, or execution
path. The profile does not provision storage. Each scheduled occurrence creates a normal child
investigation; missed intervals are coalesced into one acquisition and recorded,
never replayed as fabricated observations. Use `satquery monitor list`,
`satquery monitor runs <schedule-id>`, and the `enable`/`disable` subcommands to
inspect and control schedules.
Use `satquery monitor compare <schedule-id>` or the workspace's Compare runs
action to align exact resolved canonical variable/unit labels across recent
successful runs. The stored comparison preserves source investigation reports
and explicitly does not infer trends or scientific change.
Schedules may declare `trigger_policies` in their create or revision payload.
Each policy must provide the exact canonical variable and unit, an explicit
scalar operator and finite threshold, plus a complete follow-up `EarthQuery`.
For example:

```json
{
  "policy_id": "rain-change-review",
  "name": "Review large precipitation difference",
  "canonical_variable": "precipitation",
  "unit": "mm",
  "operator": "abs_gte",
  "threshold": 25,
  "follow_up_query": {
    "requested_variables": ["precipitation", "air_temperature"]
  },
  "cooldown_seconds": 86400
}
```

This is an operator-defined workflow condition over a descriptive exact-support
difference; it is not a validated scientific threshold or significance test.
The follow-up investigation records its policy revision, diagnostic, comparison
digest, and source observations. It is executed through the normal DAG and
appears in mission history, the investigation report, Earth Memory, and the
reproducibility bundle. `max_attempts` configures bounded retries of the
observation task, not a replay of the entire investigation; values above one
require explicit `retry_safe: true`. Threshold appropriateness and external
notification channels remain domain-owner decisions.

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

When the platform audit store is configured, hypothesis lifecycle transitions
are also recorded there with the complete versioned hypothesis and transition
event. The runtime verifies the audit chain and replays those events after a
restart. Older summary-only lifecycle entries, or persisted Earth Memory
hypothesis snapshots without matching replayable audit events, are reported as
unavailable rather than reconstructed as trusted current state. In that case,
reasoning and lifecycle writes fail closed for the affected investigation.
