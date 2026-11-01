# STAC Catalog Connector

The initial Earth Perception integration is a generic connector for catalogs
that implement the SpatioTemporal Asset Catalog (STAC) API. It is in
`satquery-ai/connectors/stac/` and builds on the platform connector lifecycle.
It also implements the provider-neutral `PerceptionConnector` contract and
translates supported `EarthQuery` fields at the connector boundary; see the
[Earth Perception architecture](../architecture/Earth_Perception.md) for
capability selection, provenance, caching, and explicit field limitations.

## Architectural choice

Three integration approaches were considered:

1. **One bespoke connector per provider.** This can expose provider-specific
   features but duplicates catalog discovery, spatial/temporal search,
   pagination, and lifecycle code. It also couples the core to provider
   endpoints and credentials.
2. **An unrestricted HTTP/plugin layer.** This is flexible but leaves every
   caller to invent request shapes, pagination behavior, and result formats;
   that is not a stable observation interface.
3. **A standards-based STAC API connector.** STAC supplies interoperable
   collection discovery and GeoJSON item search while retaining each catalog's
   item properties, assets, and extension fields.

The third approach is the current choice. Its deliberate trade-off is that a
provider must expose a compatible STAC API for this adapter to work. A native
provider connector remains appropriate when the provider offers capabilities
or data that cannot be represented through its STAC interface. That can be
added independently without changing this connector's contract.

## Supported behavior

- Configurable catalog URL, connector ID, and optional allowed collection IDs.
  Configured IDs become the default search scope and are checked against the
  catalog during discovery; explicit searches cannot select undiscovered
  collections.
- Manifest presets for Microsoft Planetary Computer
  (`planetary_computer`), Copernicus Data Space (`copernicus_data_space`),
  and USGS LandsatLook (`usgs_landsat`) reuse this same STAC implementation
  with provider-specific default catalog URLs and descriptive metadata.
  Configuration may override the catalog URL and collection IDs. These
  presets do not add provider-specific search behavior or asset downloads.
- An example Earth Search catalog configuration is provided at
  `configs/catalogs/earth-search.json`; its selected collection IDs were
  confirmed in the catalog landing page during this implementation.
- STAC landing-page discovery through `search` and `data` links.
- Collection discovery with pagination through `next` links.
- Item Search using the catalog's advertised `POST` method when available
  (preferred to avoid URL-length constraints and putting spatial filters in
  request URLs), with `GET` fallback.
- Spatial and temporal search fields: collection IDs, item IDs, bbox,
  GeoJSON intersects, datetime interval, limit, token, query, filter, and
  sort-by.
- Item pagination through `next` links, preserving POST bodies and GET query
  parameters.
- `Connector.acquire` returns an `ObservationSearchResult`. Each item maps to
  the shared `Observation` and `ObservationAsset` contracts; `source_document`
  on each observation retains the original STAC Item. The result carries
  pagination links, search context, and the remaining original response
  metadata.
- `Connector.stream` yields `Observation` objects page by page, retaining each
  source item without requiring a full result collection in memory.
- Collection band declarations can advertise platform raster capabilities.
  Categorical component polygonization is advertised only when the collection
  explicitly marks a raster band `measurement_kind: categorical` and the
  optional raster and geometry dependencies are installed. The investigation
  must still supply class-code meanings and polygonization rules.
- The `raster` optional extra installs Rasterio, PyProj, and Shapely for those
  platform processing operations; base STAC acquisition remains usable without
  these libraries.
- Optional bearer authentication, or required bearer authentication when the
  connector configuration declares it.
- Cache keys include one-way scope hashes for the catalog URL and bearer
  credential so responses cannot be reused across catalog origins or
  authenticated principals. The credential itself is not part of the cache
  key or log fields. Automatic result caching is disabled unless a positive
  connector cache TTL is configured, since catalog searches can change over
  time; explicitly supplied cache keys also require that TTL.
- Configurable connector timeouts, rate limiting, retries (only when the
  request policy explicitly marks them safe), and lifecycle cleanup.
- Origin checks prevent catalog and pagination links from forwarding
  credentials to another host. Redirect following is disabled.

No new runtime dependency was required; the implementation uses the project's
existing `httpx` dependency. An injectable HTTP transport permits deterministic
offline tests.

## Use

Create and register a connector explicitly. The URL below is illustrative;
select an actual STAC API catalog and collection available to your deployment.

```python
from connectors.stac import StacCatalogConnector
from satquery.platform.connectors import ConnectorManager, ConnectorPolicy

connector = StacCatalogConnector(
    configuration={
        "catalog_url": "https://catalog.example/stac",
        "connector_id": "earth-observation-catalog",
        "collection_ids": ["collection-id"],
    },
    policy=ConnectorPolicy(timeout_seconds=30),
)
manager = ConnectorManager()
manager.register(connector)

collections = await manager.discover("earth-observation-catalog")
items = await manager.acquire(
    "earth-observation-catalog",
    {
        "collections": ["collection-id"],
        "bbox": [-123.0, 37.0, -121.0, 38.0],
        "datetime": "2024-01-01/2024-01-31",
        "limit": 100,
    },
)
```

The checked-in Earth Search example can be loaded as connector configuration
without hardcoding the provider in application code:

```python
import json
from pathlib import Path

configuration = json.loads(
    Path("../configs/catalogs/earth-search.json").read_text(encoding="utf-8")
)
connector = StacCatalogConnector(configuration=configuration)
```

For a catalog requiring bearer authentication, set
`authentication_required: true` in connector configuration and pass
`{"token": <secret>}` to `manager.start(connector_id, credentials)`. Credentials
are supplied separately from configuration.
Bearer credentials are refused over non-HTTPS catalog connections except for
loopback development hosts.

The example assumes it runs inside an async function. `limit` is passed to the
catalog; catalogs may enforce their own maximum page size. Use `manager.stream`
for page-by-page feature delivery and `manager.stop`/`stop_all` to close the
HTTP client.

## Scope and limitations

- This is a protocol connector, not an exhaustive provider integration. No
  provider endpoint, collection ID, data entitlement, or successful live
  acquisition is bundled or guaranteed.
- Sentinel, Landsat, and some Copernicus collections can be accessed through
  configured STAC catalogs; the provider presets above expose three catalog
  endpoints through the shared adapter, not independent provider APIs.
  MODIS, Google Earth Engine, ERA5, CHIRPS, OpenStreetMap, NOAA, and other
  sources are not thereby made available through these presets. Any catalog
  exposing suitable STAC endpoints and collections may be used through
  configuration, subject to its auth, network, and API behavior. The Earth
  Search example selects Sentinel-1, Sentinel-2, Landsat, and Copernicus DEM
  collections; this is a catalog configuration, not an independently
  maintained provider connector.
- OAuth refresh, API-key authentication, signed asset downloads, cloud
  storage transfer, raster reprojection, asset materialization, and dataset
  version pinning are not implemented.
- The connector returns catalog metadata and asset references. It does not
  download all assets or perform Earth analysis.
- Normalized observation fields intentionally cover only common metadata
  (identifier, collection, time, geometry, bbox, properties, and assets).
  Provider-specific extensions remain in `source_document`; no cross-provider
  semantic interpretation or harmonization is performed.
- A streamed failure after features have been yielded is surfaced to the
  caller; restarting the entire stream implicitly could duplicate delivered
  items.
- Automated tests use an in-memory HTTP transport. Live catalog availability
  and provider-specific behavior are not part of the automated test suite.
  The Earth Search landing page and collections were inspected, and a
  one-item Sentinel-2 search smoke test succeeded on 2026-10-17. That
  point-in-time check does not guarantee future availability or item searches.

## Verification

Run the focused connector tests from `satquery-ai`:

```powershell
python -m pytest -c pyproject.toml ..\tests\test_stac_connector.py ..\tests\test_platform_connectors.py
```

## References

- [STAC API Item Search specification](https://api.stacspec.org/v1.0.0/item-search/)
- [Earth Search catalog landing page](https://earth-search.aws.element84.com/v1/)
