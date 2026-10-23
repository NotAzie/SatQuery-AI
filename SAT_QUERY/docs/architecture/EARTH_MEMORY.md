# Earth Memory Retrieval

Earth Memory stores immutable, digest-checked artifacts and their explicit
source links. It is an index, not a learning system or scientific reasoner.

Capability snapshots are indexed as `capability_snapshot` artifacts linked to
the plan or execution that used them. They preserve the public capability
entries and modality declarations for the recorded matrix revision and verify
their own content digest. Raw dataset metadata, asset URIs, and connector
source/provider payloads are excluded; the snapshot does not freeze source data
or guarantee that a provider can reproduce an earlier response.

Candidate-to-object extraction batches are indexed with links to their source
observation artifacts. They record the pipeline version, candidate digests,
source method identities, and reconciliation issues. Every batch with input
observations is indexed, including batches that emit no candidates, preserving
the distinction between no candidate and no recorded extraction. A
source-declared candidate is explicitly marked as not independently validated; indexing it does not
upgrade its class to ground truth. Canonical Earth Objects are linked to the
same investigation scope in memory and are available to subsequent reasoning
and report generation.

Source attributes copied from an explicit candidate are retained on the object
as typed `source_attributes`, separately from canonical property assertions.
Each value records its source observation, dataset, extraction mapping ID,
uncertainty status, and a digest of candidate provenance. The complete source
observation remains linked on the object rather than duplicated for each
attribute. Multiple explicit extraction methods
may contribute when they declare the same stable identity and canonical type; all
method IDs remain attached to the extraction record. Attributes are labeled unmapped; preserving
a source key/value does not establish an ontology mapping or scientific
interpretation. Reports expose these values as source attributes rather than
canonical object properties.

Reclassification and lifecycle changes require an explicit transition naming
the exact prior revision, actor, rationale, and source observations or evidence
already linked to that object. A transition creates a new immutable object
revision and an investigation audit event. The platform does not infer a state
change from elapsed time or an observation alone. Transition records are also
indexed as `earth_object_transition` artifacts, linked to prior/result object
revisions and the cited source records for deterministic search.

`EarthObjectExtractionBenchmarkRunner` plugs supplied canonical observation
bundles into the platform's exact-output validation executor. It compares
reproducible extraction and materialization output only. A passing regression
benchmark does not validate detection accuracy, scientific meaning, or
applicability beyond the supplied reference data; no benchmark suite or
validation dataset is bundled by SatQuery.

Perception executions index exact-support `observation_stack` artifacts and
consecutive `temporal_difference` diagnostics when produced. Stacks link to
their member observation artifacts and retain per-sample measurements, source
uncertainty, and provenance. Difference diagnostics retain both complete source
members and are marked descriptive-only with uncertainty not propagated. These
records are not trend tests or scientific conclusions. Stacks and differences
are spatially indexed only from their explicit support geometry and CRS, and
temporally indexed from their source acquisition timestamps.

## Deterministic search

Investigation comparisons are indexed with their canonical measurement groups,
exact-support stacks, descriptive differences, blockers, identity conflicts,
and source investigation/observation links. Schedule-driven comparisons also
retain monitoring run links. These artifacts are searchable by type and source
investigation, and are captured by reproducibility exports.

`EarthMemoryQuery` supports literal text terms and structured filters for
artifact type, exact canonical variable identifier, mission, investigation,
method, source artifact, space, and time. Canonical-variable matching reads
only resolved measurement identifiers or explicit canonical-variable fields;
it does not resolve source aliases or search arbitrary text. It therefore
matches canonical observations, Earth Objects, observation stacks, and temporal diagnostics
without treating provider terms as ontology mappings. Text terms use
deterministic case-folded substring matching. Results label the spatial and
temporal match semantics when those filters are used. The same query has the
same ordering and results in the in-memory and SQLite adapters.

Search results use ascending artifact ID order and support snapshot-bound
cursor pagination. `next_cursor` can be supplied as `cursor` on the next query
with the same filters (the page limit may change). Each page reports the number of matching records still
available from that cursor position before applying the page limit. The cursor
is tied to the index revision returned by the first page; if the index changes,
the next request is rejected as stale and the search must restart. Cursor tokens
are opaque continuation data, not authorization tokens or cryptographic proofs.
The API returns 409 for a stale snapshot cursor and 422 for a malformed cursor
or one reused with different filters.

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

SQLite schema version 6 stores derived spatial-temporal, canonical-variable,
and case-folded trigram search indexes plus a revision accumulator separately
from immutable artifact payloads. Existing version 1–5
stores are migrated transactionally by rebuilding the indexes from canonical
payloads, including exact-support stack and temporal-difference extents.
Payloads and artifact IDs are not rewritten. SQLite applies artifact-type,
mission, investigation, method, source-link, canonical-variable, cursor, and
explicit spatial-temporal constraints before loading candidate payloads. For
terms with at least three case-folded characters, a trigram index narrows the
candidate set; short terms and unusually large query gram sets use a full
metadata-filtered scan. Exact substring checks remain authoritative and match
the in-memory adapter's semantics. Candidate rows are consumed in bounded
batches; only the requested page plus one lookahead artifact is retained while
the exact remaining match count is computed. Search verifies every candidate
it examines, including candidates after the current page. A complete
`verify_integrity()` audit also checks that derived trigram rows match the
immutable records, detecting missing index entries that could otherwise omit
a search result. Repository-wide
`verify_integrity()` independently audits all artifact payload digests and all
derived indexes; it is the operation for detecting corruption outside a
filtered query's candidate set. The revision is a deterministic SHA-256 digest
of the artifact count and a 521-bit commutative accumulator over SHA-512
artifact identity/digest entries. SQLite updates this state in the same
transaction as artifact insertion, so filtered searches need not rescan all
artifact digests. The algorithm identifier is returned with every search
result. This revision identifies a snapshot; it is not a signature or
tamper-proof audit proof.

Example API request:

```json
{
  "text": "water level",
  "canonical_variable": "water_level",
  "spatial_bbox": [72.7, 18.8, 73.2, 19.3],
  "spatial_crs": "OGC:CRS84",
  "temporal_start": "2025-01-01T00:00:00Z",
  "temporal_end": "2025-02-01T00:00:00Z"
}
```

The API is `POST /api/v1/platform/earth-memory/search`. The CLI exposes the
same filters with `satquery memory search TERMS --variable water_level
--artifact-type observation --mission-id MISSION_ID --investigation-id
INVESTIGATION_ID --method-id METHOD_ID --source-artifact-id ARTIFACT_ID --bbox
MIN_X MIN_Y MAX_X MAX_Y --crs OGC:CRS84 --start ISO_TIMESTAMP --end
ISO_TIMESTAMP --limit 100`. Reuse the returned `next_cursor` with `--cursor`
to fetch another page. A bounding box and CRS must be supplied together;
temporal bounds must be supplied together.

This retrieval layer does not yet provide exact spatial predicates, coordinate
transforms, raster footprint indexes, vector-tile indexes, temporal nearest
neighbor ranking, semantic search, or distributed geospatial storage. Those
require explicit semantics and scale requirements before adoption.

Investigation reproducibility bundle schema `1.4.0` retains capability
selection snapshots alongside Earth Object
revision snapshots, the selected relationship graph, source-declared extraction
batches, explicit transition artifacts, and their audit events. Each collection
contributes to the bundle's artifact hashes. Empty object and transition
collections are valid recorded outcomes; missing extraction records remain
explicit when extraction did not run. For monitoring-driven investigations, the
bundle also captures the exact schedule-definition revision, scheduled run,
monitoring lifecycle events, and any operational notifications associated with
that run. Monitoring records are optional for ordinary investigations and are
included in hashes when present.
Exact-support temporal diagnostics from investigation and monitoring
comparisons are indexed as immutable `investigation_comparison` and
`monitoring_comparison` artifacts and included in each linked investigation
bundle. Each comparison retains its
source reports, stack members, deterministic arithmetic diagnostics, alignment
blockers, identity conflicts, and explicit method version. A descriptive
difference is not a trend test; source uncertainty is retained but not
propagated. Empty comparison collections are recorded as valid outcomes.
Investigation comparisons are stored as `investigation_comparison` artifacts;
schedule-scoped run comparisons additionally retain run and schedule links in
`monitoring_comparison` artifacts.
Each eligible cross-investigation temporal difference is also separately
indexed as a `temporal_difference` artifact linked to its exact comparison,
source observations, and source investigations. These records can be retrieved
directly by artifact type or source investigation.
Comparison schema `1.2` stores evidence-only report snapshots so changes to
monitoring event history or prior comparison links do not change a comparison's
content identity. It includes stack-builder and difference-engine versions
in the content digest.
Investigation reports include compact digest references and diagnostic counts
for linked comparisons while the complete comparison payload remains available
through Earth Memory and reproducibility exports. This avoids recursively
embedding prior reports inside later comparisons.
with exact run and investigation references. They align only resolved canonical
variables with identical unit labels; Earth Memory does not treat this
alignment as a scientific change event, trend, or conclusion. Where each source
declares exact shared point or pixel support, the comparison can additionally
emit consecutive same-dataset, same-source-variable differences using the
versioned spatiotemporal engine. Unsupported alignments remain explicit
blockers; there is no reprojection, resampling, unit conversion, statistical
significance, or causal interpretation.
Investigation identity links remain stable, while lifecycle states are indexed
as immutable content-addressed snapshots. Monitoring run artifacts reference
the terminal snapshot as well as the stable investigation identity, preventing
completion from mutating an earlier pending or running record.
