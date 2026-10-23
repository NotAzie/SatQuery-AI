# SatQuery API reference

Start the local server with `python -m satquery serve`, then open
`http://127.0.0.1:8000/docs` for the generated OpenAPI schema.

## Python client

The installable `satquery` package exports `SatQueryClient` and
`PlatformAPIError` for synchronous use of the versioned `/api/v1` API. Grouped
resources expose the platform route families: `platform`, `earth`, `missions`,
`investigations`, `monitoring`, `objects`, `memory`, and `science`. Existing
top-level helpers remain available and delegate to these groups. The generic
`request`, `get`, `post`, and `patch` methods remain available for routes added
by a newer server or legacy JSON image-perception endpoints. Multipart image
upload remains available through the REST API, not this JSON-focused client.

```python
from satquery import SatQueryClient

with SatQueryClient("http://127.0.0.1:8000") as client:
    matrix = client.platform.capability_matrix()
    proposal = client.investigations.start(
        "Review air temperature",
        earth_query={
            "point": [80.15, 12.84],
            "requested_variables": ["air_temperature"],
        },
    )
    report = client.investigations.report(proposal["investigation_id"])
```

The SDK returns decoded server JSON without local coercion and does not retry
requests. A supplied bearer token is sent by the client, but server-side
authentication and authorization are not implemented by this package. Resource
groups cover the routes documented below for platform inspection, EarthQuery,
mission and investigation lifecycle, execution, reports, reasoning and
hypotheses, governance and reproducibility, Earth Objects, monitoring, Earth
Memory, and scientific knowledge. IDs are URL-encoded as individual path
segments; query parameters with `None` values are omitted. Request and response
payloads follow the server's OpenAPI contracts and are not independently
validated by the client.

## Earth Intelligence platform

Earth Perception routes accept and return the canonical contracts documented
in [Earth Perception](../architecture/Earth_Perception.md). A connector
manifest is optional; set `SATQUERY_CONNECTORS_CONFIG` before starting the
server to load registered adapters. Connector startup is lazy. Dataset
discovery and observation acquisition make network requests only when their
routes are called.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/platform/inspect` | Inspect locally registered modalities, adapters, datasets, models, tools, task handlers, and missions. |
| `GET` | `/api/v1/platform/runtime` | Read local runtime counts, passive connector diagnostics, and effective durability/backend status for Earth Memory, lifecycle, execution, audit, and monitoring stores. Store fallback paths are reflected in this status. |
| `GET` | `/api/v1/platform/execution/workflows` | Inspect locally registered versioned workflow compilers and supported task types. |
| `GET` | `/api/v1/platform/modalities` | List Earth sensing domains. |
| `GET` | `/api/v1/platform/connectors` | Inspect registered connector manifests. |
| `GET` | `/api/v1/platform/connectors/health` | Read local call, failure, latency, and health-probe metrics without contacting providers. |
| `POST` | `/api/v1/platform/connectors/{connector_id}/health-check` | Explicitly ask one adapter to run its active health probe. This may contact the provider. |
| `POST` | `/api/v1/platform/connectors/{connector_id}/discover` | Ask one adapter to discover datasets and register their metadata. This performs a live request. |
| `POST` | `/api/v1/platform/connectors/{connector_id}/stations/search` | For a NOAA CO-OPS connector, return provider-declared water-level station candidates inside a CRS84 `bbox`; candidates are not automatically selected or treated as observations. |
| `GET` | `/api/v1/platform/datasets` | List currently known dataset metadata. |
| `GET` | `/api/v1/platform/datasets/search` | Search registered dataset metadata by declared names, aliases, variables, and terms using `q`. |
| `GET` | `/api/v1/platform/earth/capabilities` | Read the deterministic Earth capability matrix, including registered/declared domains, source variables, coverage, access, quality, unknown fields, and a content digest for its safe public snapshot. |
| `GET` | `/api/v1/platform/scientific-methods` | Inspect registered versioned methods/rules, domain registration status, operator manifests, uncertainty methods, and the catalog revision. |
| `GET` | `/api/v1/platform/scientific-methods/{method_id}/{version}/governance` | Inspect verified benchmark reports and certification lifecycle for one exact method version, including whether certification can currently emit findings and any restoration failure. |
| `POST` | `/api/v1/platform/scientific-methods/assess` | Conservatively preflight a registered method against an EarthQuery and capability-matrix snapshot; does not execute the method. |
| `GET` | `/api/v1/platform/scientific-knowledge/methods` | List cited method knowledge records, including explicit benchmark and implementation readiness. Optional `domain` filter. |
| `GET` | `/api/v1/platform/scientific-knowledge/domains` | Show seeded method-record coverage separately from executable certified coverage. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/scientific-methods/{method_id}/{version}/sufficiency` | Assess recorded observations against a cited method record and return deterministic acquisition recommendations without executing them. |
| `POST` | `/api/v1/platform/earth-memory/search` | Deterministic literal and exact canonical-variable filtering plus explicit CRS-scoped bounding-box/time filtering across indexed Earth artifacts. Supports query-bound, revision-bound cursor pagination; stale cursors return 409 and incompatible cursors return 422. Spatial matches are envelope overlaps, not exact geometry intersections or reprojections. |
| `GET` | `/api/v1/platform/scientific-workflows` | List structure-only Earth investigation templates. |
| `POST` | `/api/v1/platform/scientific-workflows/{template_id}/instantiate` | Produce an instance with supplied and unresolved configuration; never selects methods or emits conclusions. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/audit` | Read per-aggregate hash-chained investigation and plan events with verification status; event payloads are withheld when integrity checks fail. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/reproducibility` | Export retained artifacts, object revisions/graph, extraction batches, transitions, audit links, linked monitoring schedule/run events and comparisons when applicable, hashes, and explicit missing artifacts. Returns 409 if Earth Memory changes during paginated export. |
| `POST` | `/api/v1/platform/earth/plan` | Plan modality, variable, implementation, and dataset coverage without acquisition; returns the content-verified public capability snapshot associated with its matrix revision. |
| `POST` | `/api/v1/platform/earth/plan/explain` | Return the plan, matrix revision and snapshot, selected declarations, and planning limitations. |
| `POST` | `/api/v1/platform/earth/observe` | Acquire canonical observations from matching registered implementations. |
| `POST` | `/api/v1/platform/planning/investigations` | Parse a natural-language objective into a deterministic `InvestigationPlan`; does not create missions or acquire data. |
| `GET` | `/api/v1/platform/investigation-plans/{plan_id}` | Retrieve the plan and reproducibility manifest. |
| `POST` | `/api/v1/platform/intelligence/design` | Return a deterministic plan plus evidence strategies and requirement-to-step traceability; does not acquire observations. |
| `GET` | `/api/v1/platform/intelligence/designs/{design_id}` | Retrieve a stored investigation design. |
| `POST` | `/api/v1/platform/investigate` | Plan and design a natural-language investigation, create mission/investigation records, and attach tasks only when both plan and evidence strategy are ready. |
| `POST` | `/api/v1/platform/missions` | Create a local mission. |
| `GET` | `/api/v1/platform/missions` | List local missions. |
| `GET` | `/api/v1/platform/missions/{mission_id}` | Read a mission. |
| `POST` | `/api/v1/platform/missions/{mission_id}/investigations` | Create an Earth observation investigation from an `EarthQuery`. |
| `GET` | `/api/v1/platform/missions/{mission_id}/investigations` | List investigations belonging to a mission. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}` | Inspect task, evidence, result, and lifecycle references. |
| `POST` | `/api/v1/platform/monitoring/schedules` | Create a recurring EarthQuery schedule linked to an active mission. |
| `GET` | `/api/v1/platform/monitoring/schedules` | List schedules, optionally filtered by `mission_id`. |
| `PATCH` | `/api/v1/platform/monitoring/schedules/{schedule_id}` | Revise query/cadence/policy with an `expected_revision`; stale edits return 409. |
| `POST` | `/api/v1/platform/monitoring/schedules/{schedule_id}/enable` | Enable a schedule without discarding run history. |
| `POST` | `/api/v1/platform/monitoring/schedules/{schedule_id}/disable` | Disable a schedule without deleting it. |
| `GET` | `/api/v1/platform/monitoring/schedules/{schedule_id}/runs` | Inspect persisted run, investigation, and execution links. |
| `GET` | `/api/v1/platform/monitoring/schedules/{schedule_id}/triggers` | Inspect operator-authored trigger policies and a stable page of deterministic evaluations, cooldown suppressions, and linked follow-up investigations (`limit`, `cursor`). |
| `POST` | `/api/v1/platform/monitoring/run-due` | Dispatch due schedules through the ordinary investigation DAG (`limit` defaults to 100). |
| `GET` | `/api/v1/platform/monitoring/health` | Inspect scheduler counts and expired run leases. |
| `GET` | `/api/v1/platform/monitoring/events` | Read append-only lifecycle events; filter by `schedule_id` or `run_id`. |
| `GET` | `/api/v1/platform/monitoring/events/page` | Read a stable keyset page of append-only event history (newest page first); pass `next_cursor` as `cursor` to load older events without an offset or fixed history window. |
| `GET` | `/api/v1/platform/monitoring/notifications` | List unread or all partial/failure notifications. |
| `POST` | `/api/v1/platform/monitoring/notifications/{notification_id}/acknowledge` | Acknowledge a local notification and retain the acknowledgement event. |

Each monitoring run records `schedule_revision`, linking it to the immutable
schedule definition that caused the acquisition. Scheduler-only changes such as
advancing `next_run_at` do not create new definition revisions. The configured
`monitoring.max_concurrency` bounds simultaneous investigation dispatches. A
worker renews a durable lease while a run is active; expired runs are finalized
as failed and are never silently replayed. Event history records schedule
changes, claims, completion states, and lease recovery. Schedules declare an
`overlap_policy`: `skip_while_running` coalesces the due slot while a prior run
is active, while `allow` permits overlapping investigations. Notifications are
local inbox records; external email, SMS, and webhook delivery are not implied.
CLI schedule edits use a JSON document with `expected_revision` and one or more
of `name`, `earth_query`, `interval_seconds`, `priority`, `overlap_policy`, and
`trigger_policies` via
`satquery monitor update <schedule-id> --update-file <path>`.
Use `satquery monitor compare <schedule-id>` to align exact resolved canonical
variable and unit labels across the most recent completed or partial runs. This
reuses investigation comparison, persists a hashed artifact in Earth Memory,
and makes no change, trend, or causal claim; specify `--limit` from 2 to 20.
Trigger policies are explicit operational rules attached to a schedule revision.
Each requires an exact `canonical_variable`, exact `unit`, comparison operator,
finite threshold, and a caller-authored `follow_up_query`. Operators are `gt`,
`gte`, `lt`, `lte`, `abs_gt`, and `abs_gte`. Policy evaluation only compares
the descriptive difference against that configured scalar condition. It does
not test significance, propagate uncertainty, or claim a scientific event.
`cooldown_seconds` suppresses repeat triggers for that policy; deterministic
event and child investigation identities make the follow-up idempotent across
restarts. `max_attempts` is the ordinary execution task's bounded handler retry
count, not a replay count for the entire investigation DAG. It defaults to one;
a larger value requires explicit `retry_safe: true`. Follow-ups use the same Earth observation handler and are
bounded per scheduler tick by `monitoring.max_triggered_investigations_per_tick`.
Use `satquery monitor triggers <schedule-id>` or the workspace Triggers action
to inspect rule history and investigation lineage. Trigger matches and failures
create local notifications; external delivery is not configured by this layer.
Event and trigger history is returned as bounded pages. Pass a page's
`next_cursor` as `--cursor` to `satquery monitor events` or as the API `cursor`
query parameter to continue with older records.

## Investigation reports and comparisons

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/platform/investigations/{investigation_id}/report` | Build deterministic Markdown and structured output from recorded plans, observations, Earth Objects, coverage, reasoning, provenance, linked monitoring history, comparison artifact references, and limitations. Monitoring and cross-investigation comparisons remain context and do not add scientific findings. |
| `GET` | `/api/v1/platform/monitoring/schedules/{schedule_id}/comparison` | Align explicit canonical measurements from recent completed or partial runs of one schedule; requires at least two linked investigations and persists the content-hashed comparison in Earth Memory. Exact declared spatial support can additionally enable versioned descriptive consecutive differences. |
| `POST` | `/api/v1/platform/investigation-comparisons` | Align exact resolved canonical variable and unit labels across 2–20 investigations; persists an auditable Earth Memory artifact. It can emit descriptive consecutive differences only for exact shared point/pixel support and compatible dataset/source-variable identities. It does not convert units, resample, test trends/significance, propagate uncertainty, or produce scientific conclusions. |

Comparison schema `1.2` records evidence-only investigation report snapshots,
the exact-support stack builder version, and
consecutive-difference method/version with each content digest. Temporal outputs
remain descriptive arithmetic, retain their exact source members, and mark
uncertainty as not propagated.

## Investigation records, evidence, and execution

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/platform/investigations/{investigation_id}/intelligence` | Inspect the linked evidence strategy and, after execution, its bounded coverage assessment. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/reasoning` | Inspect the versioned reasoning report; returns `not_evaluated` before evidence assessment exists. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/reasoning/evaluate` | Re-evaluate retained observations with current Earth Objects in the deterministic reasoning context. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/hypotheses` | Inspect the versioned hypothesis graph and append-only lifecycle event history; returns 409 when persisted history cannot be safely replayed. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/hypotheses` | Register an explicitly sourced hypothesis as proposed; it is not activated or scientifically evaluated automatically. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/hypotheses/{hypothesis_id}/transitions` | Append a lifecycle transition using an expected version, actor, and rationale. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/execute` | Execute the versioned investigation DAG: acquisition, explicit candidate reconciliation, requested categorical-raster component polygonization, Earth Object materialization, evidence assessment, and reasoning when a ready design exists. Raster component semantics and connectivity must be declared in `EarthQuery`; no image classification is inferred. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/resume` | Resume a stopped investigation from exact-plan successful checkpoints; prior uncertain tasks run again only when declared `retry_safe`. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/cancel` | Request cooperative cancellation of the active local investigation execution. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/observations` | Return observations retained from completed in-process execution results. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/observation-stacks` | Return exact-geometry-and-CRS temporal groupings with each source measurement, uncertainty, and provenance record intact. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/temporal-differences` | Return reproducible consecutive-sample arithmetic diagnostics from exact-support raster stacks; no trend or uncertainty propagation is claimed. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/earth-objects` | Materialize an Earth Object from an explicit identity/type declaration and source observations; every supplied evidence reference is validated. |
| `GET` | `/api/v1/platform/earth-objects` | List current process/memory-restored Earth Object revisions; optional `investigation_id` filter. |
| `GET` | `/api/v1/platform/earth-objects/geojson` | Export RFC 7946 GeoJSON for valid geometries with a declared WGS 84 CRS; optional `investigation_id` filter. Unknown/projected CRS and invalid geographic geometries are listed in `satquery:omitted_objects`, not silently transformed. |
| `GET` | `/api/v1/platform/earth-objects/id/{object_id}` | Inspect one canonical object with its source records, measurements, provenance, uncertainty, and revision metadata. |
| `POST` | `/api/v1/platform/earth-objects/id/{object_id}/transitions` | Create a reclassification or lifecycle revision with an exact prior object ID, actor, rationale, and already-linked observation/evidence support. |
| `GET` | `/api/v1/platform/earth-objects/graph` | Read the selected Earth Object graph and evidence-backed relationships; optional `investigation_id` filter. |
| `POST` | `/api/v1/platform/earth-objects/relationships` | Record a relationship assertion only when it cites source observations or evidence associated with its endpoint objects. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/provenance` | Return each observation's dataset, provider metadata, provenance, and reproducibility declaration. |
| `GET` | `/api/v1/platform/executions/{execution_id}` | Retrieve task outcomes, outputs, timing, and trace ID for an execution plan ID; Earth Object extraction is a checkpointed typed task output. |
| `GET` | `/api/v1/platform/executions/{execution_id}/events` | Poll the append-only, ordered execution journal; use `after_sequence` as the sequence cursor. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/events/stream` | Stream the same journal as replayable Server-Sent Events while execution runs; reconnect with `Last-Event-ID` or use `after_sequence`. |

The platform API is not an authenticated multi-user service. Store selection,
connector access, and network exposure are operator configuration. Provider
discovery, active health checks, and acquisition may make external requests;
passive inspection routes report local declarations and call history only.

Categorical raster extraction can be requested with an explicit EarthQuery,
for example:

```json
{
  "bbox": [70.0, 10.0, 71.0, 11.0],
  "crs": "OGC:CRS84",
  "requested_variables": ["land_cover_class"],
  "raster_component_extraction": [
    {
      "asset_key": "classification",
      "band_index": 1,
      "source_variable": "land_cover_class",
      "class_mappings": [
        {"class_value": 4, "object_type": "earth:CallerDeclaredClass4"}
      ],
      "connectivity": 4,
      "pixel_selection": "pixel_center",
      "minimum_component_pixels": 5,
      "maximum_components": 1000
    }
  ]
}
```

This converts explicit categorical cell values to connected polygon regions.
The caller supplies class semantics; this does not classify imagery or assert
that the source mask is scientifically validated. The optional `raster` extra
is required. `satquery investigate --query-file earth-query.json` accepts the
same contract, and the workspace structured EarthQuery field passes it through.

Earth Object responses include `source_attributes` separately from canonical
property assertions. These are raw, unmapped source key/value records with
observation, dataset, extraction mapping, uncertainty status, and provenance links;
their presence does not imply ontology resolution or validation.

Transitions are explicit review/source assertions. They append an immutable
Earth Object revision and an investigation audit event; the API does not infer
object type changes or lifecycle state from observations. The transition is
also searchable in Earth Memory as `earth_object_transition`.

Reproducibility exports use bundle schema `1.4.0`. They include the public
capability-selection snapshots associated with investigation planning and
acquisition, each matching Earth Object revision with its retained
source/evidence records, the selected object relationship graph (including an
empty graph when no objects exist), Earth Object extraction batches, and
explicit transition artifacts. Snapshot contents and other records are hashed
into the bundle digest. Capability snapshots omit raw dataset metadata, asset
URIs, and connector source/provider payloads; they do not retain or recreate
upstream data. Empty object and transition collections mean that none were
recorded; they are not reported as missing artifacts. Export timestamps are
excluded from the stable bundle digest, and repeated exports of the same
investigation snapshot reuse the same immutable Earth Memory artifact.

Capability snapshots are also searchable in Earth Memory with
`--artifact-type capability_snapshot` or an `artifact_types` filter. The
synchronous Python SDK returns these response fields as server JSON without
local coercion.

### Mission-oriented CLI and natural-language boundary

The primary CLI commands are `investigate`, `plan`, `explain`, `observe`,
`capabilities`, `datasets`, `connectors`, `mission`, `investigation`, and
`runtime`. `ask` remains a compatibility entry point for the image-analysis
capability. Structured acquisitions use an EarthQuery JSON file:

The workspace catalog shows registered sensing modalities, datasets,
connectors, and passive connector diagnostics. Dataset search uses registered
metadata. Provider health probes and connector discovery are explicit actions
that may make live provider requests. The CLI exposes these same operations as
`connectors`, `connectors health`, `connectors probe ID`, and
`connectors discover ID`; `platform discover ID` remains an alias for the last
operation.

`satquery investigate QUESTION --query-file earth-query.json` creates the
mission, deterministic plan, evidence design, and investigation record without
acquiring data. Adding `--execute` explicitly authorizes acquisition when the
plan has executable tasks; the CLI then returns creation data, execution
artifacts, and the evidence-linked report together. If clarification is
required, execution is skipped and the CLI exits with status 2. The API keeps
planning and `POST /api/v1/platform/investigations/{id}/execute` as separate
operations so clients can review the plan before acquisition. A successful CLI
run also collects execution events, observations, Earth Objects, reasoning,
provenance, the audit chain, reproducibility bundle, and report through their
existing inspection endpoints.

Use `satquery investigation resume <investigation-id>` to resume an interrupted
workflow when a durable journal is configured. The event endpoint is available
for ordered polling by CLI, API clients, and the workspace.

```powershell
python -m satquery investigate "Review air temperature near this site" --query-file earth-query.json
python -m satquery intelligence design "Measure air temperature globally last week" --query-file earth-query.json
python -m satquery investigation execute <investigation-id>
python -m satquery investigation events <investigation-id>
python -m satquery investigation report <investigation-id>
python -m satquery investigation compare <investigation-id-1> <investigation-id-2>
python -m satquery monitor compare <schedule-id> --limit 10
python -m satquery reasoning show <investigation-id>
python -m satquery reasoning methods
python -m satquery objects list --investigation-id <investigation-id>
python -m satquery objects geojson --investigation-id <investigation-id>
python -m satquery objects show <object-id>
python -m satquery objects graph --investigation-id <investigation-id>
python -m satquery hypotheses show <investigation-id>
python -m satquery plan earth-query.json --explain
python -m satquery observe earth-query.json
python -m satquery mission list
python -m satquery runtime
```

Investigation governance artifacts can also be inspected from the CLI with
`python -m satquery investigation audit <id>` and
`python -m satquery investigation reproducibility <id>`.
The `investigation report` command renders a deterministic summary of recorded
artifacts and explicitly states when no scientific reasoning report is
available.

`python -m satquery science library [--domain DOMAIN]` lists referenced method
records. `python -m satquery memory search "literal terms"` searches retained
Earth Memory artifacts; this is exact literal matching, not semantic retrieval
or learned knowledge. Filter with `--artifact-type earth_object_extraction` to
inspect candidate reconciliation, method identity, applicability context,
source digests, and explicit extraction limitations.

Earth Memory and mission/investigation lifecycle state are in-process by
default. Set `SATQUERY_PLATFORM__STORAGE__EARTH_MEMORY_PATH` or pass
`--platform-config` to `satquery serve` with `storage.earth_memory_path` to
retain them in SQLite across restarts. Execution payloads retain typed
observation outputs and remain available through investigation history. The
SQLite adapters are single-host storage; they do not provide distributed
replication or encryption.

Natural-language objectives are preserved verbatim. The deterministic planner
extracts recognized ontology terms and supported explicit scope, reports
candidate datasets/sensors and missing information, and stores a reproducibility
manifest. It does not geocode arbitrary place names or invent observation
parameters. Supply clarifications or an explicit EarthQuery, review the plan,
then execute as a separate action.

The intelligence design links declared evidence requirements to planned
observation steps. After execution, its assessment reports metadata coverage
and passes through conflicts reported by perception fusion. It does not claim
that evidence is scientifically sufficient, evaluate hypotheses, infer
causality, or calculate confidence. Spatial and temporal coverage remain
indeterminate unless a later validator can verify them against observation
footprints and intervals.

After execution, the initial reasoning engine evaluates evidence structure
through versioned operators and registered scientific rules. Built-in
operators do not evaluate hypothesis truth. Without an applicable scientific
rule, competing hypotheses remain unevaluated and the conclusion is unresolved.
The reasoning route and investigation intelligence response expose the same
report for API, CLI, and browser inspection.

The browser workspace at `/` uses these same routes to create investigations,
inspect the capability matrix and runtime, execute a structured observation
task, and inspect its output and provenance. Its Earth Object locator view uses
the GeoJSON export route and only draws explicitly WGS 84 geometry; it is an
equirectangular locator, not a basemap or measurement surface. The legacy image
query remains available in the same workspace as an image-perception capability.

Mission and investigation repositories are in-memory by default. Configure
SQLite storage paths to retain supported lifecycle, execution journal, audit,
Earth Memory, and monitoring records across local restarts. This is
single-host persistence, not distributed storage. The HTTP task execution
route accepts Earth observation investigations; arbitrary registered task
handlers remain available to trusted Python integrations, not to client-
supplied task definitions.

The deterministic Scientific Investigation Planner matches exact aliases in
the Earth ontology, explicit coordinates or capability-declared regions, and
defined calendar or relative time expressions. Missing or ambiguous scope is
returned as structured clarification requests. Ambiguous ontology terms may
produce multiple candidate plans; SatQuery does not choose one silently.
Planning returns a proposal and reproducibility metadata. It does not invoke
connectors. Execute only an investigation whose plan status is `ready`. Cost
is reported only when every selected dataset declares compatible pricing;
quality expectations preserve dataset declarations and remain unknown when
none exist. Provider confidence is not numerically estimated.

The capability matrix revision is a hash of the current connector and dataset
metadata snapshot. `null` fields mean the source did not declare that fact;
`asset_references_declared` reports catalog references, not verified download
availability. Connector registration and health status do not guarantee that
an upstream service is reachable. Use `python -m satquery platform capabilities`
to inspect the same matrix from the CLI.
Connector diagnostics are separate from declared capability health. The local
diagnostics route omits raw error text; an active provider probe occurs only
when the explicit `POST .../health-check` route is called.

### Example Earth query

```json
{
  "point": [80.15, 12.84],
  "requested_variables": ["air_temperature_2m"],
  "requested_dataset_ids": ["weather-forecast"]
}
```

For example, submit it to the planning endpoint:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/platform/earth/plan `
  -ContentType application/json `
  -InFile earth-query.json
```

`plan` reports declared capability and known coverage. It does not claim that
an observation exists. `/earth/observe` returns source observations and their
provenance. By default, referenced raster assets remain untouched. A
structured EarthQuery can request opt-in point sampling with
`"asset_sampling": "point"` plus `point` and `requested_variables`; only
discovered datasets declaring band metadata are eligible. Install the optional
`raster` extra. Sampling returns a separate point-supported observation and
records asset/band lineage. It reads HTTPS assets only and applies declared
scale/offset. Polygon summaries use `"raster_analysis": "zonal_descriptive"`,
a Polygon or MultiPolygon `geometry`, requested variables, and an explicit
`raster_pixel_selection` of `"pixel_center"` or `"all_touched"`. They return
typed `raster_analysis_products` on source observations: valid/selected cell
counts and, for numeric variables, minimum, maximum, cell-weighted mean, and
population standard deviation. Categorical ontology variables receive raw
code frequencies. Equal-cell weighting remains the default. An explicit
`"raster_weighting": "geodesic_cell_area"` adds ellipsoidal area-weighted
summaries for unrotated geographic rasters (install both `raster` and
`geospatial` extras); projected and rotated grids are rejected for this mode.
Cell areas are whole-pixel areas, including boundary pixels selected by
`all_touched`; the polygon does not fractionally clip edge cells. These
products remain descriptive and carry no inferred uncertainty or scientific
conclusion.
Band measurement semantics must be resolvable from the ontology, explicit band
`measurement_kind`, or a query-level `raster_semantics` declaration; a unit
label alone is not used to assume coded values are continuous.
For example, a source band named `red` without ontology or metadata semantics
requires an explicit query mapping such as `"raster_semantics": {"red": "numeric"}`.
For multi-scene point-sampling responses, `observation_stacks` contains only
measurements whose acquisition times, units, and pixel-support geometry/CRS
match exactly. Unresolved variables remain scoped to their declared dataset.
`alignment_issues` explains why other samples could not be aligned. No
resampling, unit conversion, temporal interpolation, uncertainty aggregation,
or trend inference is performed.

## Existing image capability

The image endpoints remain supported and execute through the platform task
runtime. Successful `QueryResponse` values include `platform_mission_id`,
`platform_investigation_id`, and `platform_execution_id` for inspection.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Serve the browser workspace. |
| `GET` | `/api/v1/health` | Report legacy model/application readiness and setup actions. This does not probe Earth data providers. |
| `GET` | `/api/v1/capabilities` | List currently available legacy image capabilities. This is distinct from `/api/v1/platform/earth/capabilities`. |
| `GET` | `/api/v1/config` | Return effective application configuration with secrets redacted. |
| `POST` | `/api/v1/warmup` | Load configured optional image models now rather than on first image request. |
| `POST` | `/api/v1/query` | Analyze uploaded satellite or aerial imagery. |
| `POST` | `/api/v1/query/json` | Analyze server-side image paths. |
| `POST` | `/api/v1/query/location` | Fetch an Esri imagery snapshot for a point/place, then run the image capability; external imagery/geocoding availability and terms apply. |
