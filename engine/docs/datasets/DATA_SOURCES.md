# Earth data sources

The canonical source inventory is [Supported datasets and adapters](SUPPORTED_DATASETS.md).
That page tracks implemented connector families and their current limits;
this page explains how to read the inventory and enable them.

## Configuration model

Connectors are not automatically enabled just because their Python adapter is
installed. `SATQUERY_CONNECTORS_CONFIG` must point to a manifest, such as
`configs/connectors.example.json`, and each manifest entry must use a
registered connector type. The manifest configures provider endpoint,
collections/products, variables, coverage declarations, and optional
credentials. Capability declarations express configured/claimed support;
they do not prove that a remote service is reachable or that a particular
request has data.

Connector manifests are parsed relative to the process working directory.
Use an absolute path or start the process from the repository/package root
consistently. Keep credentials in environment variables or a secret manager,
never in a committed manifest.

## Provider access and scientific scope

Public endpoints may still rate-limit, change, be temporarily unavailable, or
return no matching records. Authentication is provider-specific. Spatial and
temporal query support, returned metadata, units, latency, and product
semantics differ by adapter. Read the connector document and provider terms
before operational use. SatQuery preserves source metadata and does not
convert a dataset's presence into scientific validation.

Current adapters include STAC, NASA Earthdata CMR, NASA POWER, NASA FIRMS,
Open-Meteo, OpenStreetMap, USGS 3DEP, USGS Water, and NOAA CO-OPS. They do not
represent complete coverage of these organizations' catalogs or all Earth
sensing modalities.

## Related documentation

- [Supported datasets](SUPPORTED_DATASETS.md)
- [STAC connector](STAC_CONNECTOR.md)
- [NASA POWER connector](NASA_POWER_CONNECTOR.md)
- [Earth Perception architecture](../architecture/Earth_Perception.md)
- [Connector configuration and local setup](../development/SETUP.md)
