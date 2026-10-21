# SatQuery

SatQuery is an Earth Intelligence platform for observing and investigating
Earth through provider-neutral data interfaces, canonical observations,
evidence-linked Earth Objects, reproducible workflows, and explicit limits.
The platform does not claim that its current connectors cover the planet or
that its reasoning layer can produce generally validated scientific
conclusions.

## Repository layout

This directory is the canonical Python project. The outer `SAT_QUERY/` folder
contains project documentation, configuration examples, tests, and archives;
it is not a second application.

- `satquery/` — FastAPI app, CLI, runtime composition, and platform subsystems.
- `connectors/` — registered external data implementations and the optional
  image fetcher.
- `../tests/` — unit and integration tests.
- `../configs/` — example platform and connector configuration.
- `../docs/` — architecture, API, setup, data coverage, testing, and roadmap.

Read [the current implementation status](../docs/IMPLEMENTATION_STATUS.md) for
the limits of every major capability. The
[documentation index](../docs/README.md) links contributor materials.

## Install and run locally

Python 3.10 or later is required. CI currently uses Python 3.12. For a new
Windows PowerShell environment:

```powershell
cd satquery-ai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,geospatial,raster]"
```

The base installation supports the API, CLI, platform runtime, and
provider-neutral contracts. `geospatial` adds geometry utilities; `raster`
adds Rasterio, PyProj, and Shapely for the supported explicit raster
operations. Install `vision` if you want the legacy Hugging Face image
analysis tools (`torch` and `transformers`); choose a PyTorch wheel compatible
with your OS/device. See [setup](../docs/development/SETUP.md) for Linux/macOS,
configuration, live connectors, and persistence.

Start the local application:

```powershell
python -m satquery doctor
python -m satquery serve
```

Open `http://127.0.0.1:8000/` for the browser workspace and
`http://127.0.0.1:8000/docs` for generated OpenAPI. The server binds to
loopback by default. Do not expose it to a network without owner-configured
authentication and network controls; this repository does not supply a
production identity or authorization layer.

The CLI uses the running API by default, so its mission and investigation
state is shared with the workspace. Set `SATQUERY_API_URL` when using another
server URL.

## Python platform client

Applications can use the versioned synchronous API client instead of building
HTTP requests themselves:

```python
from satquery import SatQueryClient

with SatQueryClient("http://127.0.0.1:8000") as client:
    capabilities = client.capability_matrix()
    plan = client.plan_earth(
        {"point": [-112.074, 33.4484], "requested_variables": ["air_temperature"]},
        explain=True,
    )
```

`SatQueryClient.api_version` identifies the client API version. Responses remain
the server's JSON objects so clients can inspect fields introduced by newer
servers. HTTP failures raise `PlatformAPIError` with the response status,
payload, and remediation when supplied. Requests are not retried automatically:
an acquisition or mutation may have completed even if its response was lost.
The optional bearer token is only sent as a header; this repository does not
provide server-side authentication or authorization.

## Configure data connectors

Connector implementations are registered only when explicitly listed in a
connector manifest. To use the example configuration from the repository
root:

```powershell
$env:SATQUERY_CONNECTORS_CONFIG = "..\configs\connectors.example.json"
python -m satquery serve
```

Paths in a manifest are interpreted by the process at startup. Discovery and
acquisition contact upstream services only when their operations are called.
The example manifest is a starting configuration; it does not guarantee
service availability, complete dataset metadata, licensing, geographic
coverage, or credentials. NASA FIRMS requires a MAP_KEY and an explicit
`nasa_firms` manifest entry. NASA Earthdata access to protected assets remains
provider-controlled. See [supported datasets](../docs/datasets/SUPPORTED_DATASETS.md)
and the [connector guides](../docs/README.md#platform-and-science).

## Typical Earth investigation

Create a structured query file, for example `earth-query.json`:

```json
{
  "point": [-112.074, 33.4484],
  "temporal_start": "2024-01-01T00:00:00Z",
  "temporal_end": "2024-01-07T00:00:00Z",
  "requested_variables": ["air_temperature"]
}
```

Then plan, inspect, and explicitly execute:

```powershell
python -m satquery capabilities
python -m satquery plan earth-query.json --explain
python -m satquery investigate "Review air temperature at this point" --query-file earth-query.json
python -m satquery mission list
```

Use the investigation ID returned by `investigate` to inspect and execute it:

```powershell
python -m satquery investigation show <investigation-id>
python -m satquery investigation execute <investigation-id>
python -m satquery investigation report <investigation-id>
python -m satquery investigation audit <investigation-id>
python -m satquery investigation reproducibility <investigation-id>
```

For an explicit one-command run, add `--execute`:

```powershell
python -m satquery investigate "Review air temperature at this point" --query-file earth-query.json --execute
```

This acquires observations only when planning produced executable tasks, then
prints the creation record, execution events, observations, Earth Objects,
reasoning, provenance, audit chain, reproducibility bundle, and evidence-linked
report in one JSON document. If planning needs clarification, no acquisition is
made and the command exits with status 2. Without `--execute`, `investigate`
remains plan-only.

Natural-language planning is deterministic and bounded by recognized
ontology vocabulary and supported time/location parsing. Missing or ambiguous
scope is returned for review; planning does not acquire observations.
Structured query values are authoritative. A successful acquisition can
still be partial or empty if an upstream source cannot satisfy the request.

Other platform commands include:

```powershell
python -m satquery observe earth-query.json
python -m satquery datasets
python -m satquery connectors
python -m satquery objects list --investigation-id <investigation-id>
python -m satquery reasoning show <investigation-id>
python -m satquery science methods
python -m satquery memory search --artifact-type observation
python -m satquery monitor health
python -m satquery runtime
```

See [API reference](../docs/api/API_REFERENCE.md) for endpoints and exact
response semantics. The image endpoint and `satquery ask` remain available as
one legacy image-perception path.

## Data and scientific limits

- Current provider coverage is deliberately bounded; a registered connector
  or catalog item is not proof that data are reachable or fit for an analysis.
- STAC usually returns metadata and asset references. Raster point samples,
  polygon zonal summaries, and categorical component polygonization are
  explicit operations; no automatic image classification, general
  reprojection, or uncertainty propagation is implied.
- Earth Objects are constructed from explicit source candidates and caller
  declarations. OSM/FIRMS/NOAA source records and categorical raster codes are
  not independently validated detections or ground truth.
- The reasoning framework exposes evidence, hypothesis, method, and
  governance diagnostics. No bundled method is certified to make general
  scientific conclusions; cited literature metadata is not validation.
- Monitoring predicates are operator-authored operational rules, not
  scientifically validated change detection. Notification delivery is local.
- The default platform runtime and stores are process-local. Optional SQLite
  stores support single-host persistence; remote/distributed execution is not
  provided.

## Verification

From this directory, install development and relevant optional dependencies,
then run the deterministic suite:

```powershell
python -m pytest -c pyproject.toml -m "not real_acceptance"
```

GitHub Actions runs a selected deterministic regression set, not every test
or live provider/model checks. Real Hugging Face model acceptance is opt-in
and requires the configured model weights and compatible hardware/network or
a populated cache. See the [testing guide](../docs/testing/TESTING_GUIDE.md)
and [benchmark policy](../docs/testing/BENCHMARKS.md).
