# Earth Perception Layer

## Scope

The implemented perception layer accepts a validated `EarthQuery`, plans
requested Earth sensing modalities across interchangeable data
implementations, obtains canonical `ObservationSearchResult` values, adds
acquisition provenance, and can return an aggregated result or asynchronous
observation stream. Aggregated results
include conservative exact-duplicate compaction, overlapping observation
groups, and explicit conflicts. It is independent of
the existing user-query and image-analysis paths. It does not analyze raster
assets or plan investigations.

## Contracts

`satquery.platform.contracts.EarthQuery` represents one spatial and temporal
request. It supports one of bbox, point, or GeoJSON geometry; a CRS identifier;
temporal bounds; an optional resolution and unit; requested Earth modalities
and variables; optional dataset IDs; required capabilities; a region;
source-neutral filters; and asset preferences. Dataset IDs scope acquisition
to planned implementations. Geographic bboxes and points are checked against longitude and
latitude bounds, projected bboxes are checked for ordered finite coordinates,
and temporal bounds must be timezone-aware and ordered. Geometry validation is
structural; it does not validate topology or reproject coordinates.

`Observation` remains backwards compatible with its earlier fields and now
also carries temporal extent, observation type, measured variables, declared
perception modalities, provenance, uncertainty, provider metadata, quality
information, optional source-provided confidence, and reproducibility
metadata. Provider values and keys remain intact in `measured_variables`;
perception adds separate `canonical_measurements` only for unambiguous known
semantics. Unknown or ambiguous names stay explicitly unresolved.
`ObservationQuality` provides a common assessment shape for completeness,
source confidence, uncertainty, freshness, provider-quality metadata, lineage,
reproducibility metadata presence, and geometry validation status. Unknown
values remain unknown; confidence is copied only from the source observation.
Completeness is calculated only against explicitly requested variables and
resolved canonical measurement records. Provider quality is ranked only when
the source supplies a normalized score in the canonical quality field.
The original provider document remains available in `source_document`.

`ObservationAsset` is the common reference for assets and does not open,
download, or interpret them. `AssetCatalog` searches assets attached to
observations and registered dataset metadata by dataset, role, media type, and
text. It preserves the source URI, roles, metadata, and source ID.

## Earth sensing modalities

SatQuery models perception domains independently from the datasets that
implement them. The extensible `SensingModalityRegistry` currently defines
visual, atmospheric, hydrological, ecological, geological, human, oceanic,
disaster, and cryospheric modalities. These are Earth observation capabilities,
not vendor or API categories. A modality may be served by multiple datasets;
one dataset may support multiple modalities. `DatasetMetadata.modalities`,
`ConnectorMetadata.modalities`, and `Observation.modalities` declare the
relationship at dataset, implementation, and evidence levels respectively.

Ontology variables map to domains where the mapping is unambiguous. For
example, `air_temperature` implies atmospheric perception and `elevation`
implies geological perception. Visual imagery is an explicit modality because
an image asset is not itself a measured Earth variable. Ambiguous or unknown
terms are not assigned a domain by guesswork. The registry accepts an
injectable Earth ontology; extensions can register additional modality
definitions and aliases without changing unrelated data implementations.

`PerceptionEngine.plan(query)` describes expected modality and variable
coverage before acquisition. The selector can choose several implementations
for one query and can split known requested variables across them. The plan
reports selected and unavailable modalities and variables, plus selected
implementation IDs and namespaced dataset identities. Results retain this plan;
dataset IDs can be used to scope a later request to the same implementation.
Unavailable requested coverage
makes the result `partial`. `DatasetRegistry.plan(query)` offers the same
coverage view during dataset discovery. Dataset search therefore finds
implementations that cover any known part of a multi-domain request instead of
requiring one dataset to answer every variable.

The plan describes declared capability only. Explicitly disjoint dataset
coverage is filtered out; absent coverage remains unknown and does not get
converted into a coverage claim. A query-capable implementation may still be
asked to search that location or time. The plan does not claim that data exist,
that assets can be opened, or that an observation was successfully returned.
Query-time failures, empty results, source coverage, and observation evidence
remain separate facts.

`DatasetMetadata` describes implementation/dataset identity, provider, version,
variables and declared units, perception modalities, capabilities, optional
spatial, temporal, historical, and forecast coverage, resolution, CRS, update
frequency, uncertainty characteristics, licensing, citation, latency, access
policy, quality characteristics, confidence availability, tags, keywords,
categories, aliases, deprecation, assets, and additional metadata. Missing
forecast, confidence, unit, and quality declarations remain unknown; they are
not inferred from a modality or provider name. `DatasetRegistry` is an
independent contract. The local `InMemoryDatasetRegistry` supports explicit
registration, version lookup, listing, capability filtering, deterministic
metadata text search, alias lookup, and filtering against an `EarthQuery`.
Connector registration adds its declared dataset references to the manager's
shared registry without network I/O. Explicit discovery enriches those
declarations with returned catalog metadata; an existing manual registration
is not replaced. Unknown spatial or
temporal coverage is not treated as a match for a query that constrains that
dimension. If provider identity is absent from connector metadata, automatic
registration records it as `"unknown"`. Default-version selection is
deterministic but currently compares version strings lexicographically; it
does not implement semantic-version ordering. Text search is token-substring
matching, not ontology or embedding search. Spatial-coverage filtering uses
declared-CRS GeoJSON and the optional geospatial dependencies.

`PerceptionEngine.build_capability_matrix()` produces a deterministic snapshot
across the modality ontology, registered implementations, and dataset
metadata. The snapshot reports canonical and source variable names, provider
identity, declared coverage and resolution, units, latency, update cadence,
quality and uncertainty metadata, access policy, licensing, authentication,
asset-reference declarations, streaming support, implementation health, and
the provenance source for those fields. A dataset whose adapter is not loaded
is reported as `declared`; a loaded adapter is `registered` or `unavailable`;
a domain with no known implementation is `not_registered`. These states
describe local registrations, not live upstream reachability.

Every perception plan includes the matrix revision used for selection, and
observations carry the same revision in their platform provenance. The
observation cache key includes that revision, so changed capability metadata
cannot silently reuse a result planned against an older metadata snapshot.
The matrix is available from `GET /api/v1/platform/earth/capabilities` and
`python -m satquery platform capabilities`. Provider source documents and
dataset records remain available through the dataset registry; the matrix API
does not serialize those raw metadata payloads or asset URLs.
Live connector call and probe metrics are exposed separately at
`GET /api/v1/platform/connectors/health`; this local diagnostics read performs
no provider request. `POST /api/v1/platform/connectors/{connector_id}/health-check`
is an explicit active probe and may contact that provider.

## Dataset implementation selection

Data implementations subclass `PerceptionConnector`, in addition to the
existing lifecycle, discovery, acquisition, timeout, retry, and logging
contract. Its `observe(EarthQuery)` method must return an
`ObservationSearchResult`; provider parsing and normalization belong inside
that connector. Its stream method yields `Observation` values. Legacy
`Connector` implementations remain valid and are not implicitly adapted.
Every connector can expose a `ConnectorManifest` built from its declared
metadata, dependencies, authentication schemes, quota, configuration schema,
and implemented lifecycle hooks. `ConnectorManager` validates registered
connectors and can load trusted Python entry points from the
`satquery.connectors` group through an explicit builder. This is an in-process
extension hook; loading an entry point executes installed code.

`ConnectorMetadata` declares sensing modalities, string capabilities, priority, health,
availability, supported regions, supported spatial query shapes, whether
temporal filtering is supported, additional supported query fields, temporal
bounds, supported variables, provider version, and provider metadata.
Capabilities are open strings so extensions can add source-specific
categories without platform changes.
The default `ModalityImplementationSelector` implements the matching policy and
can be replaced through the `ConnectorSelector` protocol. The manager also
exposes connector self-descriptions, declared capability indexes, validation
results, runtime diagnostics, and health snapshots. Health snapshots are local
by default. An explicit active snapshot calls connector health-probe hooks;
connectors without an override report active probing as unsupported. The STAC
adapter probes the configured catalog landing page and records a bounded
availability ratio and probe latency.
Selection includes available implementations that are not marked unhealthy
and match required capabilities, requested perception targets (modalities and,
when specified, one or more variables), requested region, spatial/temporal
query shape, supported query fields, and declared temporal bounds. A multi-
variable query can be split across implementations; each implementation
receives a subquery limited to
the variables and modalities it declares. Unknown variable names still
require an exact declaration. Unspecified region or spatial-query support does
not match a query that explicitly requests those constraints. Results are ordered
by descending priority, then healthy/degraded/unknown status, then connector
ID. `fallback_for` declares explicit connector-ID fallback relationships.
Fallbacks are attempted in priority order only after all their declared primary
connectors fail; a fallback cycle without a primary is an explicit error.
Availability and initial health remain declarations for connectors without
an active probe implementation. The current probe history and latency
statistics are process-local; provider quota metadata remains declarative and
there is no live quota polling.

## Acquisition and normalization

`PerceptionEngine.observe` starts selected connectors and acquires from them
concurrently, with an adjustable concurrency bound (eight simultaneous
connectors by default; `None` disables the bound). Connector policy provides
optional acquisition timeouts, request pacing, cache TTL for the legacy
request interface, and explicitly safe retries with a configurable attempt
count and delay. The canonical observation path records attempts, retries,
failures, durations, and latest outcomes in connector diagnostics. A connector
failure is
preserved as a `PerceptionFailure`;
successes are still returned with `partial` status. If all selected connector
acquisitions fail, the result status is `failed`. Unexpected non-connector
exceptions are surfaced rather than converted into success-shaped results.

The engine verifies that every connector returns the canonical result
contract, then adds connector identity, declared provider identity (only when
present), version, query fingerprint, and actual pipeline retrieval time to
provenance and reproducibility metadata. Source acquisition times remain in
the connector-provided record when available. Existing source provenance,
provider metadata, and source documents are retained. Missing provider
identity stays missing.

Duplicate merging is deliberately conservative: observations merge only
when their canonical content (including geometry, temporal extent,
measurements, properties, quality, confidence, and assets) is identical.
Differences in source identity, dataset, provenance, provider metadata, or
source document are retained in
`provenance.satquery.earth_perception.merged_sources`; connector-generated
fields use their own namespace rather than replacing source-supplied
`satquery` metadata.
This is exact duplicate removal, not unit conversion or scientific
comparability assessment.

Before quality assessment, fusion, and graph construction, the engine's
`SemanticNormalizer` adds `CanonicalMeasurement` records for unambiguous
ontology aliases. The original `measured_variables` mapping, connector-supplied
canonical records, units, and metadata remain unchanged. Unmapped or ambiguous
source names remain explicitly unresolved; configured mappings can be injected
for domain or dataset-specific vocabularies. Normalizer version and revision
are recorded in perception provenance and included in the observation cache
key so a result normalized under one vocabulary cannot be reused under another.

After exact duplicate compaction, `ObservationFusion` groups observations when
known temporal extents overlap or known geometries intersect (using shared
CRS-aware spatial operations when available). A shared source variable, a
resolved canonical variable, or matching observation type is also required.
Missing spatial or temporal coverage is not
treated as proof of overlap. Conflicts are recorded only for pairs not known
to be disjoint in either dimension, avoiding false measurement conflicts
between spatially overlapping observations from known separate times. Groups
contain original observation IDs, a deterministically quality-ranked primary
ID, temporal and spatial intersections when calculable, and conflict records.
Different units are reported as incomparable rather than converted;
disagreement records retain the original values and units. Fusion does not
synthesize a new measurement or scientific conclusion.

`SemanticNormalizer` provides explicitly configured mappings for variable
aliases, standard names, ontology URIs, unit dimensions, observation types,
categorical values, and dataset vocabulary. Runtime canonicalization adds
semantic measurement records without rewriting provider measurements.
Observation harmonization remains available for callers that explicitly want
normalized variable keys; it records the source CRS and observation type,
canonicalizes known CRS identifiers, and retains source names, values, units,
and metadata alongside normalized terms. Dataset harmonization preserves
original vocabulary. Neither path converts units, infers unmapped equivalence,
or discards original provider measurements.

## Fusion, graph, and quality

`ObservationFusion` groups observations only where their declared type or
measured variables are compatible and known spatial or temporal overlap
supports grouping. It keeps every observation, deterministically ranks a
primary record using available quality evidence and configured connector
weights, reports differing measurements as conflicts, and retains uncertainty
records and a provenance tree. It does not average values, propagate
uncertainty mathematically across incompatible source models, or infer a
scientific conclusion.

`ObservationGraphBuilder` creates explicit `overlaps`, `conflicts_with`,
`corroborates`, temporal-neighbor, and optionally spatial-neighbor edges from
observation evidence. Other relationship types such as `derived_from`,
`supersedes`, and `same_phenomenon` are added only when explicitly declared in
source provenance. Edges retain evidence. Graph links organize records; they
are not an inference result.

`ObservationQualityService` assesses and filters observations independently
of acquisition. It preserves source uncertainty, confidence, provider flags,
provenance lineage, reproducibility state, freshness, and geometry validation.
Completeness is calculated only when expected variables were requested.
`quality_score` is populated only from an explicitly supplied normalized
provider quality score. Completeness, source confidence, and provider quality
remain separate dimensions; the platform does not combine unlike measures
into a synthetic aggregate. Missing values remain unknown; no confidence is
fabricated.

## Spatial and temporal utilities

`satquery.platform.temporal` exposes timezone validation/UTC conversion,
interval overlap, deterministic rolling-window and seasonal-window generation,
chronology sorting, temporal grouping, and observation freshness calculation.
These helpers preserve unknown timestamps as unknown and do not aggregate
measurements. Freshness is a signed age in seconds; future timestamps therefore
remain distinguishable rather than being clamped to zero.

`satquery.platform.spatial` provides bbox-to-geometry conversion, deterministic
AOI tiling clipped to the source geometry, geometry validation/repair and CRS
transformation, geometry simplification, buffering, distance, intersection,
containment, and an in-memory STRtree spatial index. These operations use the
optional `geospatial` dependencies (`pyproj` and Shapely); source geometry and
CRS must be supplied explicitly for reprojection. Tiling and planar distance
units are the units of the supplied CRS; the helpers do not silently assign
geographic-distance meaning. These are shared reusable services; existing
provider adapters still translate source requests themselves and do not
automatically invoke every operation.

## Open-Meteo point adapters

`connectors.open_meteo.OpenMeteoConnector` is configurable per endpoint and
implements four point-query products using the canonical connector contract:

| Endpoint | Capability | Product represented |
|---|---|---|
| `weather` | `weather`, `meteorology` | Open-Meteo hourly forecast output |
| `historical_weather` | `weather`, `meteorology` | Open-Meteo historical weather output |
| `climate` | `climate`, `scientific_dataset` | Daily downscaled climate model output |
| `hydrology` | `hydrology`, `river_discharge` | Daily GloFAS river-discharge model output |

The adapter accepts one point in OGC:CRS84/EPSG:4326, optional supported
variables, and either no temporal range or a complete timezone-aware range.
Historical weather, climate, and hydrology require both temporal bounds.
Responses are normalized into one observation per provider timestamp, use
provider-returned grid coordinates, preserve provider units and values, retain
the returned response metadata and each row's original variable values, and
attach endpoint and request details for reproducibility. Null values are kept
and named in the observation quality metadata. No confidence is fabricated.
HTTP timeouts, rate limits, service errors, and invalid source payloads remain
explicit connector failures; the existing connector policy controls retries,
request pacing, and timeout behavior.

The Open-Meteo HTTP response is currently downloaded and decoded as one JSON
document before its timestamps are mapped to observations. Its inherited
observation stream yields normalized records after that acquisition; it is not
an HTTP-level streaming parser or a multi-point batch client.

Weather and historical weather values are model-derived provider outputs, not
direct instrument readings. Climate output is a downscaled climate projection
product, not a reconstruction of actual historical weather. Hydrology output
represents modeled GloFAS discharge; point-to-river association and inherent
model uncertainty are provider limitations, not resolved by this adapter.
Provider output and source metadata are preserved rather than relabeled as
direct measurements.

The adapter does not serve bbox or polygon queries, spatial resolution,
filters, asset preferences, model analysis, or observations from independent
weather/climate/hydrology providers. Open-Meteo weather, climate, and flood
products are distinct endpoints within one provider integration, not
independent provider implementations.

`PerceptionEngine.stream` yields normalized observations from each selected
connector in deterministic connector order. Connector errors during streaming
surface to the caller; results already yielded are not silently replayed.
`stream_batches` groups that stream into caller-sized tuples without
prefetching, retaining source order and propagating consumer backpressure.
Cancellation follows the active async iteration; no platform-level queue is
used.
`PerceptionEngine.observe` acquires independent primary connectors
concurrently within its configured concurrency bound. Explicit fallbacks are
sequential and deterministic. Exact duplicate compaction and overlap grouping
are deterministic for a fixed canonical input set.

Raster sampling and zonal analysis are platform processing stages owned by
`PerceptionEngine`, not STAC-specific connector behavior. Connectors return
canonical observations and asset references; the engine invokes the selected
platform raster service after acquisition. Any implementation may participate
when its dataset and connector declarations satisfy the requested operation
and its observations contain compatible asset-band metadata. Processing runs
off the event loop. A per-observation processing error remains linked to its
source observation in `PerceptionResult.processing_failures`; the source record
is retained and the overall result is marked partial. The streaming API raises
the processing error at the affected item because it has no aggregate result
envelope.

## Cache

`ObservationCache` is a separate protocol from connector/tool caching.
`MemoryObservationCache` is the local implementation and uses a dedicated
namespace and positive TTL. Cache keys are SHA-256 fingerprints of canonical
EarthQuery fields, not provider request payloads. UTC-normalized temporal
bounds and order-independent capability/variable selectors are fingerprinted
canonically. Cache results are accepted only while the selected connector
identity/version tuple still matches. Failed and partial acquisitions are not
cached. The cache protocol can be implemented by another backend without
changing `PerceptionEngine`. Named SQLite, Redis, and object-storage
subprotocols describe future implementations only; no persistent or
distributed cache backend is included. `ManagedObservationCache` exposes local-cache
administration: connector-aware invalidation, clear, and entry/hit/miss/
eviction/stale-expiration statistics. The local implementation uses monotonic
TTL expiry. The cache remains in-process and is not distributed.

## Current adapters and boundaries

The shared STAC connector implements `PerceptionConnector`. Presets expose
Microsoft Planetary Computer, Copernicus Data Space, and USGS LandsatLook
catalogs without introducing different observation contracts. They translate
canonical bbox, point/GeoJSON geometry, and temporal bounds into STAC Item
Search and return normalized observations while retaining source Items and
catalog provenance. They accept OGC:CRS84 coordinates and do not reproject.
STAC does not have a universal mapping for all canonical fields: the adapter
rejects requested filters, spatial resolution, or asset preferences rather
than silently ignoring them. Requested variables require a connector that
declares those variables; the generic STAC adapter does not claim a variable
inventory. Planetary Computer asset signing is not implemented. Assets remain
references unless the query explicitly requests a supported raster operation, the
discovered collection declares band metadata, and the platform raster extra
(including `rasterio`) is installed. This capability belongs to the platform
processing runtime and applies to compatible assets regardless of which
connector acquired their source observations. HTTPS GeoTIFF assets can then yield the source pixel
value for an exactly mapped requested band. SatQuery records source asset,
band, transform, pixel, scale/offset, and query CRS; it preserves the scene
record and returns a separate point-supported observation linked to it. An
explicit Polygon or MultiPolygon query can instead request zonal descriptive
statistics. These are typed analytical products attached to the source scene,
with exact band/asset lineage, selected-cell semantics, grid transform, and a
stable product identity. The supported pixel-center or all-touched rule is
required in the query; cells have equal weight, so reported means are not
area-weighted. Numeric summaries require numeric semantics from the ontology,
declared units, or explicit band `measurement_kind`; categorical ontology
variables produce raw code frequencies without class-label guessing. No pixel
resampling, index derivation, or uncertainty estimate is performed.

For queries returning multiple scenes, the platform processes each scene
independently and attaches one or more products to that scene's observation.
This is multi-scene execution with preserved timestamps and identities; it is
not yet a pixel-aligned temporal stack, cross-scene temporal statistic, or
change method. No implicit resampling or spatial-support equivalence is
claimed. Product grids, windows, selection rules, and source assets remain
available in each product's reproducibility metadata for later validated
alignment methods.

For multi-observation point-sampling requests, `PerceptionEngine` also builds
`ObservationStack` records from raster samples only when each member has a
source acquisition time, finite numeric value, declared unit, and identical
pixel-support geometry and CRS. Resolved canonical variables may align across
datasets; unresolved variables are scoped to the same declared dataset and
source-variable name. Units must match exactly. The stack retains every source
observation, measurement metadata, uncertainty record, and provenance record.
It does not resample, reproject support, convert units, interpolate time,
aggregate uncertainty, or calculate a trend. A versioned consecutive-difference
diagnostic now reports `later - earlier` for each adjacent pair in a valid
stack only when both samples identify the exact same dataset and source
variable. Cross-dataset or source-variable comparisons are returned as explicit
issues and remain available in the unaggregated stack until a validated
compatibility method exists. It embeds both source members, exact pixel support,
units, provenance, and source uncertainty; its status is explicitly descriptive
and uncertainty is explicitly not propagated. It does not calculate a rate,
test significance, interpret physical meaning, or support a scientific
conclusion. Non-finite arithmetic is returned as a typed issue instead of a
result. Alignment blockers remain available as
`PerceptionResult.alignment_issues`; they do not erase acquired observations.
The streaming API continues to yield observations individually and does not
claim to produce an aggregate stack.

Diagnostics are part of `PerceptionResult`, indexed in Earth Memory with their
exact CRS-scoped spatial support and source time interval, and exposed through
the investigation API, CLI inspection, and workspace. Earth Memory schema v3
rebuilds the derived spatiotemporal index from immutable payloads when opening
v1 or v2 stores. These records are descriptive arithmetic, not validated trend
or change methods.

The NASA Earthdata connector uses NASA CMR collection discovery and granule
search. It can discover configured collection concept IDs or short names,
preserves CMR metadata and links, and exposes granule links as canonical asset
references. It does not crawl every NASA product automatically or download
Earthdata assets. Earthdata bearer credentials are optional configuration;
protected-resource authorization beyond that is provider-controlled.

The OpenStreetMap connector queries Overpass for configured element types and
tags within supported point, bbox, or single-ring polygon AOIs. Returned OSM
elements are canonical vector observations with their tags and metadata
preserved. Polygon holes and antimeridian-crossing bboxes are rejected rather
than approximated. The connector does not expose an exhaustive OSM dataset
catalog or download source assets.

The USGS 3DEP EPQS connector returns one interpolated elevation sample for a
single OGC:CRS84/EPSG:4326 point. It retains the service response, selected
data source, resolution, request parameters, and reported units. It does not
claim a time-series timestamp, infer a local uncertainty estimate, or accept
bbox/polygon requests. USGS notes that EPQS values are interpolated from the
dynamic elevation service and that accuracy varies with the source data at a
location; the provider's overall accuracy statement is not used as a local
uncertainty value. See the [USGS EPQS API](https://epqs.nationalmap.gov/v1/docs)
and [USGS accuracy notes](https://www.usgs.gov/faqs/how-accurate-are-elevations-generated-elevation-point-query-service-national-map).

Connector discovery registers dataset references in the shared in-memory
dataset registry. The built-in local registry is also available when a
`ConnectorManager` is used without an explicitly injected registry. Discovery
metadata is catalog metadata, not a guarantee that a dataset can satisfy
every query or that its full coverage/variables are known.

The Earth Variable Ontology provides concepts for atmosphere, weather,
climate, hydrology, terrain, vegetation, agriculture, land cover, geology,
cryosphere, oceans, biodiversity, disasters, infrastructure, transportation,
population/human geography, and energy. Variables declare aliases,
standard-name/ontology references where known, unit dimensions, canonical
units, and related variables. Concept metadata is available through the
ontology API and includes canonical variables and declared relationships.
`SemanticNormalizer` can use it to map unambiguous names while preserving
source metadata; ambiguous aliases are not resolved automatically. It does
not convert units, interpret arbitrary provider vocabularies, or make
scientific inferences. STAC collection discovery maps only recognized
collection keywords, declared variables, and supported band summaries into
canonical dataset variables/concepts. The source collection document and its
original terms remain in dataset metadata. Dataset variable search recognizes
unambiguous ontology aliases.

The existing Esri World Imagery image fetcher also implements
`PerceptionConnector` for point requests. It wraps its existing image
acquisition result as an imagery observation with a local image asset
reference. It does not provide an observation timestamp or image-footprint
geometry, so those remain absent; the requested point is recorded as request
metadata and must not be interpreted as the full image footprint. It rejects
temporal, filter, resolution, and asset-preference constraints that it cannot
honor.

The current modality-to-implementation coverage is intentionally incomplete:

| Modality | Current declared implementations | Main gaps |
|---|---|---|
| Visual | STAC collections with recognized imagery metadata; Esri World Imagery point fetcher | Platform point sampling and zonal descriptive statistics can process compatible STAC assets with declared raster bands; no spectral-index derivation, area weighting, or sample uncertainty |
| Atmospheric | Open-Meteo weather, historical weather, and climate endpoints; STAC collections when variables are declared | No broad reanalysis, atmospheric composition, or multi-source gridded coverage |
| Hydrological | Open-Meteo modeled river discharge; STAC collections when variables are declared | No dedicated surface-water, groundwater, flood-monitoring, or basin products |
| Ecological | STAC collections when ecological variables are declared | No dedicated vegetation, biodiversity, or land-cover products |
| Geological | USGS 3DEP EPQS point elevation; STAC collections when variables are declared | Explicitly declared elevation bands can be point-sampled; no terrain derivatives or broad geology products |
| Human | OpenStreetMap/Overpass; STAC collections when variables are declared | No population, census, or harmonized administrative-boundary products |
| Oceanic | STAC collections when marine variables are declared | No dedicated ocean-state products |
| Disaster | STAC collections when hazard variables are declared | No dedicated active-event, impact, or response feeds |
| Cryospheric | STAC collections when cryosphere variables are declared | No dedicated snow, glacier, or sea-ice products |

NASA Earthdata CMR supplies cross-domain catalog discovery; it is not treated
as one observation modality. The implemented data adapters include STAC
catalogs (including the three presets above), NASA Earthdata CMR,
OpenStreetMap/Overpass, USGS 3DEP EPQS, the Esri World Imagery image fetcher,
and Open-Meteo. EPQS covers single-point elevation only; it does not provide
DEM raster access, terrain derivatives, or global elevation coverage. Asset
URIs are references by default; explicitly requested point samples can read
declared HTTPS raster bands through the optional raster extra. General asset
download, area materialization, and cross-provider unit conversion are not implemented. The dataset registry is in-memory and has no
persistent backing store, full-text semantic search, or automatic complete
catalog crawl. The ontology currently supplies a finite variable vocabulary,
not a universal Earth science ontology.

The local cache supports connector-aware invalidation, but there is no
scheduled refresh. Open-Meteo requests are single-point and do not batch
multiple locations; large temporal requests are materialized in memory.
Connector request concurrency is managed by the existing perception engine,
but the Open-Meteo adapter does not split one query into scheduled subrequests.
Active health probing is implemented for STAC landing pages only; other
connectors currently expose local diagnostics unless they add a probe hook.
Adaptive scheduling and live quota monitoring are not implemented.

## Extension contract

An extension supplies a data implementation, registers it with the existing
`ConnectorManager`, and declares its sensing modalities, supported variables,
and verified coverage in `ConnectorMetadata` and `DatasetMetadata`. It
translates `EarthQuery` into its acquisition request, normalizes returned
evidence into `ObservationSearchResult`, and yields `Observation` values from
`stream_observations`. Implementations for an existing modality are
interchangeable when their declared variables and query constraints match; a
new modality can be registered without changing unrelated implementations.
Source identity, original metadata, and acquisition provenance remain
attached to evidence.

## Verification

Deterministic tests for query validation, modality planning, capability
selection, ordering,
provenance, exact duplicate merging, cache behavior, failure reporting,
streaming, and STAC query translation are in
`tests/test_perception.py`. STAC protocol discovery and search tests remain in
`tests/test_stac_connector.py`. Open-Meteo request translation, normalization,
provenance, missing-value preservation, failure handling, and retries, plus
temporal and spatial utilities, are covered in `tests/test_open_meteo.py`.
Fusion, conflict reporting, quality assessment, fallback execution, cache
invalidation/statistics, dataset metadata lookup, and asset discovery are
covered in `tests/test_perception_platform.py`, including manifest validation, entry-point
discovery, authentication resolution, diagnostics, automatic dataset
registration, quality querying, graph generation, and shared spatial services.
The additional provider and ontology contract tests are in
`tests/test_earth_sources.py`.
