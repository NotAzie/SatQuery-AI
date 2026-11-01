# Investigation and execution pipeline

The pipeline is implemented through shared platform services, not duplicated
inside endpoint handlers. A request can stop at planning/design or continue
through acquisition and diagnostic evaluation.

```text
Natural language / EarthQuery
  -> deterministic plan and capability analysis
  -> mission + investigation (for investigate workflow)
  -> evidence requirements and investigation design
  -> versioned workflow compilation
  -> dependency-aware local execution DAG
  -> configured connector acquisition
  -> canonical observations and explicit Earth Object candidates
  -> evidence coverage assessment
  -> registered diagnostic reasoning
  -> report, provenance, audit, reproducibility, optional memory index
```

## Planning and design

The planner uses supported terms, ontology mappings, explicit structured query
fields, and configured capabilities. Ambiguous or missing requirements remain
unresolved and can produce clarification or candidate plans. The intelligence
design links requirements to proposed observation steps; it does not claim
that those observations scientifically support hypotheses. Planning and
design endpoints do not acquire data.

## Workflow execution

Ready investigations compile into a versioned `ExecutionPlan`. The DAG
validates IDs, dependencies, and cycles. The local runtime schedules ready
tasks up to the configured concurrency and records independent outcomes.
Cancellation is cooperative for synchronous handlers and direct for async
handlers. Retry counts are bounded and retries require explicit `retry_safe`
declaration. Evidence assessment and reasoning can consume successful
acquisition branches when another independent branch failed; a cancelled
dependency does not proceed as success.

When a SQLite execution journal is configured, workflow fingerprints,
checkpointable typed outputs, and append-only hash-chained events persist.
Resume uses only matching successful outputs with compatible registered
codecs. It does not replay an uncertain side effect unless the task explicitly
allows safe retry. Unsupported outputs remain uncheckpointed. The event API
provides ordered polling; it is not a live event bus.

## Evidence and reasoning boundaries

Earth Object extraction requires explicit, supported candidates. Evidence
assessment reports coverage, missing requirements, and conflicts. The
reasoning system runs deterministic registered diagnostics and rules; it does
not invent probabilities, validate general scientific claims, or substitute
for an independently validated method. Reports distinguish evidence,
diagnostics, unknowns, and limits.

## Interfaces and lifecycle

The FastAPI API, CLI, and browser workspace use the same runtime composition.
The legacy image `ask` capability is preserved as a platform task, but it
does not transform arbitrary satellite data into canonical scientific
observations. Missions, investigations, execution results, audit, memory, and
monitoring records may persist through configured SQLite adapters; otherwise
they are process-local.

Detailed routes are in the [API reference](../api/API_REFERENCE.md); command
examples are in [setup](../development/SETUP.md). See [runtime data flow](DATAFLOW.md)
for acquisition and persistence semantics.
