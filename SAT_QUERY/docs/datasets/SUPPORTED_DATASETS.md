# Supported Earth Data Sources

These are interchangeable implementations of higher-level Earth sensing
modalities, not the modality model itself. `Earth_Perception.md` defines those
capabilities and records which modality and variable coverage each
implementation declares. A modality can be supplied by multiple independent
datasets, and a single query can use multiple implementations.

"Supported" means SatQuery has an implementation that can discover or return
the listed source records. Raster assets remain references by default. Explicit
point sampling, polygon zonal summaries, and caller-configured categorical
component polygonization can process declared raster bands when the optional
raster dependencies are installed. It does not imply automatic asset
processing, classification, global coverage, or provider availability. Unknown
source metadata stays unknown in SatQuery.

| Earth sensing modality | Current interchangeable implementations | Current coverage and boundary |
|---|---|---|
| Visual | STAC collections with recognized optical bands; Esri World Imagery | The provider-neutral runtime supports explicitly requested point values and polygon zonal descriptive statistics. Investigation execution can also polygonize exact class codes from a categorical raster band into Earth Objects when the source declares categorical band metadata and the request supplies class mappings, connectivity, AOI selection, and size limits. This does not classify imagery or validate the raster labels; no spectral indices or sample uncertainty are derived. Esri has no source acquisition timestamp or image footprint. |
| Atmospheric | Open-Meteo; NASA POWER daily point products; STAC collections with declared atmospheric variables | Open-Meteo serves point weather, historical weather, and climate products. NASA POWER adds daily point time series with source-reported parameter units and UTC dates; its parameter/community availability and effective resolution vary. These products are not direct site measurements. |
| Hydrological | USGS daily river-discharge statistics; Open-Meteo modeled river discharge; declared STAC collections | USGS values are station-based daily records for parameter code 00060 and require an explicit daily statistic ID and a station ID or CRS84 bounding box. They are not continuous spatial fields. No groundwater, flood-map, or basin product is implemented. |
| Ecological | Declared STAC collections | No dedicated land-cover, vegetation, or biodiversity implementation. |
| Geological | USGS 3DEP EPQS; declared STAC collections | EPQS returns one interpolated elevation sample per point in supported geographic coordinates. Declared elevation raster bands can be sampled at an explicit point; no terrain derivatives, local error estimate, or history are inferred. |
| Human | OpenStreetMap / Overpass; declared STAC collections | Read-only vector features for supported point, bbox, and single-ring polygon queries. Explicit tagged-feature candidates may be materialized as source-declared Earth Objects with versioned observation lineage; this is not independent validation or remote-sensing detection. No population or census implementation. |
| Oceanic | NOAA CO-OPS water levels; declared STAC collections | In-situ coastal water levels for explicitly selected stations and bounded time intervals. Explicit NOAA station metadata materializes as `earth:CoastalWaterLevelStation`; sample data do not infer station status or regional representativeness. No station discovery, spatial-area query, wave, current, or basin-scale ocean state implementation. |
| Disaster | NASA LANCE FIRMS active-fire observations; declared STAC collections | Satellite thermal-anomaly records from a selected VIIRS/MODIS product, requested by 2D bbox and no more than five calendar days. Source records materialize as `earth:ThermalAnomalyDetection`; they do not establish wildfire cause, extent, or impact. |
| Cryospheric | Declared STAC collections | No dedicated snow, glacier, or sea-ice implementation. |

NASA Earthdata CMR provides cross-domain collection and granule discovery; it
is catalog infrastructure, not an Earth observation modality. STAC means that
configured catalog metadata and assets can be discovered. It does not assert
that every collection exposes a recognized variable inventory or that every
asset is sampled. After discovery, the capability matrix marks
`raster_point_sampling` and `raster_zonal_analysis` only for collections with
declared band metadata and an available platform raster runtime. These are
platform processing capabilities applied to dataset assets; they are not STAC
connector operations. Each returned item is
still checked for actual band compatibility. Point sampling reads the pixel
containing one point. Zonal analysis reports selected-cell counts and, for
numeric variables, minimum, maximum, cell-weighted mean, and population
standard deviation. Categorical ontology variables receive raw code
frequencies. Pixel-center or all-touched selection is explicit. Equal-cell
weighting is the default. Optional geodesic area weighting is limited to
unrotated geographic grids and uses whole cells rather than fractional polygon
overlaps. The engine does not resample, derive indices, or estimate
uncertainty. Numeric/categorical semantics must come from the
ontology, an explicit band `measurement_kind`, or a query-level
`raster_semantics` declaration; ambiguous bands are rejected.

The [Earth Perception architecture](../architecture/Earth_Perception.md)
documents modality planning, query matching, normalization, provenance,
quality, fusion, streaming, caching, and the limitations of each
implementation. The list above is
the current checked-in implementation, not a claim of complete Earth-domain
coverage.

For a runtime inventory of the actual installed configuration, use
`GET /api/v1/platform/earth/capabilities` or
`python -m satquery platform capabilities`. That matrix includes richer
dataset-level coverage and access metadata than this summary. Missing metadata
is represented as unknown; a declared asset reference does not prove that the
asset is currently reachable.

FIRMS access requires a NASA MAP_KEY. Set `SATQUERY_NASA_FIRMS_MAP_KEY` and add
an enabled `nasa_firms` implementation to the connector manifest. The
credential is kept out of connector metadata and provider error messages.

See the [NASA POWER connector guide](NASA_POWER_CONNECTOR.md) for its daily
point query contract, parameter mappings, and limitations.
