# Earth Memory Retrieval

Earth Memory stores immutable, digest-checked artifacts and their explicit
source links. It is an index, not a learning system or scientific reasoner.

Perception executions index exact-support `observation_stack` artifacts and
consecutive `temporal_difference` diagnostics when produced. Stacks link to
their member observation artifacts and retain per-sample measurements, source
uncertainty, and provenance. Difference diagnostics retain both complete source
members and are marked descriptive-only with uncertainty not propagated. These
records are not trend tests or scientific conclusions. Stacks and differences
are spatially indexed only from their explicit support geometry and CRS, and
temporally indexed from their source acquisition timestamps.

## Deterministic search

`EarthMemoryQuery` supports literal text terms and structured filters for
artifact type, mission, investigation, method, source artifact, space, and
time. Text terms use deterministic case-folded substring matching. Results
label the spatial and temporal match semantics when those filters are used.
The same
query has the same ordering and results in the in-memory and SQLite adapters.

Spatial filters use a four-coordinate bounding box plus an explicit CRS. The
match is inclusive envelope overlap in the same CRS; the system does not
reproject, infer a CRS, or claim exact geometry intersection. Geometry-backed
bounds are indexed only for canonical observations, Earth Objects, exact-support
observation stacks, and temporal differences that explicitly carry a CRS.
Six-coordinate observation bounds are interpreted as the standard
min-x/min-y/min-z/max-x/max-y/max-z shape.

Temporal filters require an aware start and end timestamp. They match inclusive
overlap against an observation's explicit temporal extent or timestamp, an
Earth Object's explicit temporal validity, the acquisition interval of an
observation stack, or the two source times of a temporal difference. Open-ended
and absent temporal extents remain unknown and do not match a constrained
query.

SQLite schema version 3 stores derived spatial-temporal index rows separately
from immutable artifact payloads. Existing version 1 and 2 stores are migrated
transactionally by rebuilding the indexes from canonical payloads, including
new exact-support stack and temporal-difference extents. Payloads and artifact
IDs are not rewritten. Integrity verification checks that derived indexes
still agree with their source payloads.

Example API request:

```json
{
  "text": "water level",
  "spatial_bbox": [72.7, 18.8, 73.2, 19.3],
  "spatial_crs": "OGC:CRS84",
  "temporal_start": "2025-01-01T00:00:00Z",
  "temporal_end": "2025-02-01T00:00:00Z"
}
```

The API is `POST /api/v1/platform/earth-memory/search`. The CLI exposes the
same filters with `satquery memory search TERMS --bbox MIN_X MIN_Y MAX_X MAX_Y
--crs OGC:CRS84 --start ISO_TIMESTAMP --end ISO_TIMESTAMP`. A bounding box
and CRS must be supplied together; temporal bounds must be supplied together.

This retrieval layer does not yet provide exact spatial predicates, coordinate
transforms, raster footprint indexes, vector-tile indexes, temporal nearest
neighbor ranking, semantic search, or distributed geospatial storage. Those
require explicit semantics and scale requirements before adoption.
