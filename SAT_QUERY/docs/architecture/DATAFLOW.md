# Runtime data flow

This document describes the implemented local application path. See
[implementation status](../IMPLEMENTATION_STATUS.md) for explicit capability
boundaries and [system architecture](../foundation/SYSTEM_ARCHITECTURE.md) for
the subsystem map.

## User request to investigation result

```text
CLI / HTTP API / browser workspace
  -> application composition and PlatformRuntime
  -> mission and investigation records
  -> deterministic planner and capability matrix
  -> investigation design and compiled workflow DAG
  -> selected perception connectors
  -> canonical observations, provenance, quality, optional raster processing
  -> explicit Earth Object extraction stages
  -> evidence coverage assessment and diagnostic reasoning
  -> investigation report, audit/execution history, optional Earth Memory index
```

The exact stages depend on the request and the compiled plan. Planning can
return a clarification or candidate plans when inputs are absent. A planned
EarthQuery is not proof that a provider has data or will return successfully.

## Acquisition and canonicalization

The capability and dataset registries describe declared connector support.
Configured connector factories create the available implementations.
Perception routes a structured EarthQuery to compatible implementations and
records returned source metadata and provenance on canonical observations.
Normalization and fusion preserve source records and report conflicts; they
do not invent missing measurements, uncertainty, or provider freshness.
Acquisition is limited to each connector's query shape and configured access.

Raster operations are opt-in and require the raster extra. Current operations
include compatible-CRS point samples, polygon zonal summaries, and connected
components for categorical rasters only when the caller provides class
mappings. The engine does not silently reproject, resample, mosaic, classify,
or derive scientific indices.

## Investigation execution

The platform compiles a versioned `ExecutionPlan` and executes its dependency
DAG with bounded local concurrency. Perception and Earth Object extraction
are workflow stages; evidence assessment and scientific diagnostics consume
their outputs. Independent branches can complete despite a sibling failure
when task dependencies permit. Cancellation, safe retries, partial results,
execution events, and compatible SQLite checkpoint resume are supported.
Resume reuses only successful outputs whose workflow fingerprint and
registered codec version match.

## Output and persistence

The result includes stage/task status, observations, provenance, quality,
extraction records, evidence assessment, reasoning diagnostics, and report
artifacts where those stages ran. Optional SQLite adapters persist local
lifecycle, execution, audit, memory, and monitoring state. Without configured
paths those stores are process-local. Persistence does not imply distributed
execution, cross-host locking, or transactional access to upstream providers.

Earth Memory indexes artifacts and lineage for deterministic retrieval. It
does not learn scientific relationships or independently validate findings.
Monitoring schedules can rerun configured EarthQueries and create operational
events; they do not constitute scientifically validated change detection.

## Boundaries

There is no always-on planetary ingestion, autonomous scientific conclusion,
general-purpose Earth Object detector, live map-rendering engine, distributed
worker fleet, or guaranteed end-to-end answer. See the [roadmap](../foundation/ROADMAP.md)
for future direction, clearly separated from this runtime description.
