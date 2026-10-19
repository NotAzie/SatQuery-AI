# SatQuery API reference

Start the local server with `python -m satquery serve`, then open
`http://127.0.0.1:8000/docs` for the generated OpenAPI schema.

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
| `GET` | `/api/v1/platform/runtime` | Read local runtime counts and passive connector diagnostics. |
| `GET` | `/api/v1/platform/modalities` | List Earth sensing domains. |
| `GET` | `/api/v1/platform/connectors` | Inspect registered connector manifests. |
| `GET` | `/api/v1/platform/connectors/health` | Read local call, failure, latency, and health-probe metrics without contacting providers. |
| `POST` | `/api/v1/platform/connectors/{connector_id}/health-check` | Explicitly ask one adapter to run its active health probe. This may contact the provider. |
| `POST` | `/api/v1/platform/connectors/{connector_id}/discover` | Ask one adapter to discover datasets and register their metadata. This performs a live request. |
| `GET` | `/api/v1/platform/datasets` | List currently known dataset metadata. |
| `GET` | `/api/v1/platform/datasets/search?q=water level` | Search registered dataset metadata by declared names, aliases, variables, and terms. |
| `GET` | `/api/v1/platform/earth/capabilities` | Read the deterministic Earth capability matrix, including registered/declared domains, source variables, coverage, access, quality, and unknown fields. |
| `GET` | `/api/v1/platform/scientific-methods` | Inspect registered versioned methods, domain registration status, operator manifests, and the method catalog revision. |
| `GET` | `/api/v1/platform/scientific-methods/{method_id}/{version}/governance` | Inspect executable benchmark reports and append-only certification lifecycle for one exact method version. |
| `POST` | `/api/v1/platform/scientific-methods/assess` | Conservatively preflight a registered method against an EarthQuery and capability-matrix snapshot; does not execute the method. |
| `GET` | `/api/v1/platform/scientific-knowledge/methods` | List cited method knowledge records, including explicit benchmark and implementation readiness. Optional `domain` filter. |
| `GET` | `/api/v1/platform/scientific-knowledge/domains` | Show seeded method-record coverage separately from executable certified coverage. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/scientific-methods/{method_id}/{version}/sufficiency` | Assess recorded observations against a cited method record and return deterministic acquisition recommendations without executing them. |
| `POST` | `/api/v1/platform/earth-memory/search` | Deterministic literal search and explicit CRS-scoped bounding-box/time filtering across indexed Earth artifacts. Spatial matches are envelope overlaps, not exact geometry intersections or reprojections. |
| `GET` | `/api/v1/platform/scientific-workflows` | List structure-only Earth investigation templates. |
| `POST` | `/api/v1/platform/scientific-workflows/{template_id}/instantiate` | Produce an instance with supplied and unresolved configuration; never selects methods or emits conclusions. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/audit` | Read per-aggregate hash-chained investigation and plan events. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/reproducibility` | Export currently retained investigation artifacts with per-artifact and bundle digests plus explicit missing artifacts. |
| `POST` | `/api/v1/platform/earth/plan` | Plan modality, variable, implementation, and dataset coverage without acquisition. |
| `POST` | `/api/v1/platform/earth/plan/explain` | Return the plan, matrix revision, selected declarations, and planning limitations. |
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
| `GET` | `/api/v1/platform/investigations/{investigation_id}/report` | Build deterministic Markdown and structured output from recorded plans, observations, Earth Objects, coverage, reasoning, provenance, and limitations. |
| `POST` | `/api/v1/platform/investigation-comparisons` | Align exact resolved canonical variable and unit labels across 2–20 investigations; preserves the source records and explicitly performs no unit conversion, trend analysis, or scientific conclusion. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/intelligence` | Inspect the linked evidence strategy and, after execution, its bounded coverage assessment. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/reasoning` | Inspect the versioned reasoning report; returns `not_evaluated` before evidence assessment exists. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/reasoning/evaluate` | Re-evaluate retained observations with current Earth Objects in the deterministic reasoning context. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/hypotheses` | Inspect the versioned hypothesis graph and append-only lifecycle event history. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/hypotheses` | Register an explicitly sourced hypothesis as proposed; it is not activated or scientifically evaluated automatically. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/hypotheses/{hypothesis_id}/transitions` | Append a lifecycle transition using an expected version, actor, and rationale. |
| `GET` | `/api/v1/platform/scientific-methods` | Inspect versioned rules, operators, validation states, and uncertainty methods. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/execute` | Execute the investigation's Earth observation tasks. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/resume` | Resume a stopped investigation from exact-plan successful checkpoints; prior uncertain tasks run again only when declared `retry_safe`. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/observations` | Return observations retained from completed in-process execution results. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/observation-stacks` | Return exact-geometry-and-CRS temporal groupings with each source measurement, uncertainty, and provenance record intact. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/temporal-differences` | Return reproducible consecutive-sample arithmetic diagnostics from exact-support raster stacks; no trend or uncertainty propagation is claimed. |
| `POST` | `/api/v1/platform/investigations/{investigation_id}/earth-objects` | Materialize an Earth Object from an explicit identity/type declaration and source observations; every supplied evidence reference is validated. |
| `GET` | `/api/v1/platform/earth-objects` | List current process/memory-restored Earth Object revisions; optional `investigation_id` filter. |
| `GET` | `/api/v1/platform/earth-objects/id/{object_id}` | Inspect one canonical object with its source records, measurements, provenance, uncertainty, and revision metadata. |
| `GET` | `/api/v1/platform/earth-objects/graph` | Read the selected Earth Object graph and evidence-backed relationships; optional `investigation_id` filter. |
| `POST` | `/api/v1/platform/earth-objects/relationships` | Record a relationship assertion only when it cites source observations or evidence associated with its endpoint objects. |
| `GET` | `/api/v1/platform/investigations/{investigation_id}/provenance` | Return each observation's dataset, provider metadata, provenance, and reproducibility declaration. |
| `GET` | `/api/v1/platform/executions/{execution_id}` | Retrieve task outcomes, outputs, timing, and trace ID for an execution plan ID. |
| `GET` | `/api/v1/platform/executions/{execution_id}/events?after_sequence=0` | Poll the append-only, ordered execution journal after a sequence cursor. |

### Mission-oriented CLI and natural-language boundary

The primary CLI commands are `investigate`, `plan`, `explain`, `observe`,
`capabilities`, `datasets`, `connectors`, `mission`, `investigation`, and
`runtime`. `ask` remains a compatibility entry point for the image-analysis
capability. Structured acquisitions use an EarthQuery JSON file:

Use `satquery investigation resume <investigation-id>` to resume an interrupted
workflow when a durable journal is configured. The event endpoint is available
for ordered polling by CLI, API clients, and the workspace.

```powershell
python -m satquery investigate "Review air temperature near this site" --query-file earth-query.json
python -m satquery intelligence design "Measure air temperature globally last week" --query-file earth-query.json
python -m satquery investigation execute <investigation-id>
python -m satquery investigation report <investigation-id>
python -m satquery investigation compare <investigation-id-1> <investigation-id-2>
python -m satquery reasoning show <investigation-id>
python -m satquery reasoning methods
python -m satquery objects list --investigation-id <investigation-id>
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
or learned knowledge.

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
task, and inspect its output and provenance. The legacy image query remains
available in the same workspace as an image-perception capability.

The supplied mission and investigation repositories are process-local and
in-memory. Restarting the application clears those records. The HTTP task
execution route accepts only Earth observation investigations; arbitrary
registered task handlers remain available to trusted Python integrations,
not to client-supplied task definitions.

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
| `POST` | `/api/v1/query` | Analyze uploaded satellite or aerial imagery. |
| `POST` | `/api/v1/query/json` | Analyze server-side image paths. |
| `POST` | `/api/v1/query/location` | Fetch imagery for a point/place, then run the image capability. |
