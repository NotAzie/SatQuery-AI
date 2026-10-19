# Phase 0 Platform Foundation

This document describes the Phase 0 infrastructure that exists in the
repository. It distinguishes implemented local interfaces from future systems
that are not yet implemented.

## Scope and boundaries

Phase 0 adds reusable infrastructure under `satquery.platform` while
preserving the existing query API, CLI, and tool implementations. The existing
model-loading and query paths remain authoritative for user queries. The new
interfaces are available to future components but do not replace those paths.

The implementation is process-local and in-process. Distributed scheduling,
cloud execution, durable investigation storage, remote cache backends,
provider-specific adapters for the new model interface, and a reasoning or
agent runtime are not implemented. The registries for agents, reasoners,
visualizers, and evaluators are discovery points only; their corresponding
subsystems do not exist yet.

The Phase 1 Earth Perception contracts and pipeline are documented separately
in [`Earth_Perception.md`](./Earth_Perception.md); they extend, rather than
replace, the Phase 0 connector lifecycle and cache protocols.

## Components

| Module | Responsibility |
|---|---|
| `satquery.platform.contracts` | Frozen Pydantic contracts for mission, investigation, task, observation, evidence, Earth object, dataset reference, tool/model metadata and results, reasoning step, connector metadata, and execution plan/result/progress. Nested JSON-compatible dictionaries and lists are frozen; `contract_version` is a class-level marker and is not serialized. |
| `satquery.errors` | Shared SatQuery error base and specialized configuration, validation, model, connector, authentication, timeout, network, execution, reasoning, extension, and cache errors. Existing error types remain available. |
| `satquery.platform.registry` | Thread-safe named registries, explicit registration/replacement, category registries, and installed Python entry-point discovery. Entry-point code executes in-process and is trusted code, not sandboxed. |
| `satquery.platform.connectors` | Async connector lifecycle, authentication hook, metadata discovery, acquisition, streaming, request rate limiting, timeouts, explicitly safe retries, and cache hooks. |
| `satquery.platform.perception` | Canonical EarthQuery selection/acquisition, provenance enrichment, exact duplicate merging, observation streaming, and a separate observation-cache protocol. |
| `satquery.platform.execution` | Dependency-validated task DAG execution, bounded concurrency, sync/async handlers, per-task timeouts and explicitly safe retries, progress callback, result isolation, and structured execution events. It does not plan reasoning. |
| `satquery.platform.investigations` | Mission-bound investigation lifecycle and a replaceable repository protocol. The supplied adapter stores investigations in memory only. |
| `satquery.platform.config` | JSON configuration, profile selection, environment and explicit overrides, validation, and adapters to connector/cache settings. |
| `satquery.platform.observability` | JSON-line logging formatter, trace context, event helper, and best-effort redaction for commonly named secret fields. |
| `satquery.platform.cache` | Async backend protocol and in-memory LRU/TTL implementation with basic statistics. |
| `satquery.platform.models` | Provider-neutral model adapter/runtime contract for synchronous or asynchronous inference. |
| `satquery.platform.tools` | Versioned tool contract/runtime and an adapter for existing SatQuery tools. |
| `satquery.platform.runtime` | Dependency-injected local composition root for registries, connector/model/tool/execution runtimes, investigations, and connector shutdown. |

`satquery.orchestrator` bootstraps the component registries and registers the
existing tool implementations using `LegacyToolAdapter`. This preserves
legacy `ToolContext` requirements; those tools are not silently routed through
the new generic tool execution path. The existing image-fetcher integration
has a connector adapter under `connectors/image_fetcher`; the initial
standards-based Earth Perception connector is under `connectors/stac` and is
described in [`../datasets/STAC_CONNECTOR.md`](../datasets/STAC_CONNECTOR.md).

`satquery.platform.runtime.PlatformRuntime` is the composition root for new
platform workflows. It accepts a platform configuration, shared registries,
an investigation repository, an authentication provider, and a progress
callback, then wires connector, model, tool, execution, and investigation
services around those dependencies. Connector startup remains lazy. The
runtime supports asynchronous context management and attempts to stop all
started connectors on exit. It is a local process lifecycle boundary; it does
not replace the legacy query engine or provide durable storage, a worker
queue, or process isolation.

## Data and execution flow

1. A caller creates validated `Mission`, `Task`, and `ExecutionPlan` contracts.
   The plan rejects duplicate task IDs, missing dependencies, and cycles.
2. `ExecutionEngine` resolves each task's handler from its registry. Tasks
   whose dependencies have succeeded run concurrently up to the configured
   limit; results and failures are tracked independently.
3. A task handler may use registered tools, models, or connectors. Connector
   calls can include mission, investigation, task, trace, tool, and model
   identifiers as execution context for structured logs.
4. `InvestigationService` tracks the lifecycle and references to tasks,
   evidence, results, and the final report through its repository interface.
   The in-memory repository is the only supplied persistence adapter.

The application composition now routes Earth observation requests through a
mission and investigation lifecycle. `SatQueryEngine.answer_on_platform`
executes the registered `earth.observe` task; the existing image-analysis
capability is also invoked through this execution path for compatibility.
Uploaded image bytes are passed as ephemeral task resources and are not stored
in mission or task parameters. Mission and investigation records remain
process-local with the default in-memory repository.

## Operational behavior

### Connectors

Implementations subclass `Connector`, provide `ConnectorMetadata`, and
implement `discover` and `acquire`. They can override `open`, `close`,
`authenticate`, and `stream` as needed. `ConnectorManager` registers
instances, starts them on demand, provides discovery/acquisition/streaming,
and supports shutdown. Connector retry is permitted only when policy declares
`retry_safe=True`; streaming retries stop after an item has been yielded to
avoid duplicate output. When caching is enabled, request data used to
automatically construct cache keys must be JSON serializable.

### Execution

Each `Task` may specify a timeout, retry count, retry delay, and the explicit
`retry_safe` declaration. A failed dependency causes dependent tasks to be
skipped, while independent branches continue. Synchronous handlers run via
`asyncio.to_thread`; cancelling the awaiting coroutine does not forcibly stop
work already running in that thread.

### Configuration

`PlatformConfig.load` applies defaults, selected profile defaults, JSON file
values, explicit overrides, then `SATQUERY_PLATFORM__...` environment
overrides. Supported profiles are `local`, `development`, `testing`, and
`production`. Current configuration sections are execution, connector, cache,
and logging. Unknown sections, settings, profiles, and invalid values fail
with `ConfigurationError`. This configuration is separate from the existing
query/model configuration.

### Logging and cache

`configure_logging` configures SatQuery's JSON-line logger. `log_event` writes
structured event fields; execution events include trace, mission,
investigation, task, timing, result, and available resource measurements.
Connector acquisition/cache events include available connector identity,
execution context, redacted request parameters, duration, and process CPU
delta. Redaction detects common key names such as token, secret, password,
credential, API key, authorization, and private key; it is not a general
secret scanner.

The provided `MemoryCache` is in-process only, with optional entry limits and
TTL. The protocol permits another backend to be supplied, but no persistent or
distributed backend is included. The existing query-tool cache remains
unchanged.

## Compatibility and current gaps

- Existing public query API, CLI, fixed model-loading registry, and tool
  behavior remain available. Earth planning and observation routes and CLI
  commands use the platform runtime; legacy image-analysis behavior remains
  available through the same query interface and is wrapped as a platform
  task.
- `PlatformRuntime` is composed by `SatQueryEngine` and supplies the local
  mission, investigation, connector, perception, model, tool, and execution
  services. Mission and investigation records use in-memory storage by
  default. Configuring SQLite storage makes lifecycle snapshots durable across
  process restarts; the local workspace can then inspect prior missions and
  investigations.
- The new generic `ModelRuntime` is provider-neutral, but there are no
  provider-specific implementations wired into it.
- Connector authentication is a hook; credentials are passed by the caller
  and are not sourced from a secret manager.
- Entry-point extensions load trusted installed Python code in the current
  process. There is no isolation or hot-reload mechanism.
- Durable execution payloads and canonical observations are indexed through
  Earth Memory when SQLite storage is configured. A separate execution journal
  records versioned successful checkpoints and immutable hash-chained task
  events for explicit local resume. Execution queueing, distributed resource
  management, live event transport, and worker leases remain unimplemented.
- The `Observation` and `EarthObject` contracts are generic data containers;
  they do not implement geospatial validation, storage, or Earth analysis.
- Future registries do not imply that agents, reasoning modules, or
  visualization/evaluation runtimes exist.

## Tests

The focused Phase 0 tests are in `tests/test_platform_*.py`. They cover
contract validation, dependency execution, retry safety, connector lifecycle
and caching, configuration and extension registration, model/tool adapters,
and compatibility bootstrap. Run them from `satquery-ai`:

```powershell
python -m pytest -c pyproject.toml ..\tests\test_platform_contracts.py ..\tests\test_platform_execution.py ..\tests\test_platform_connectors.py ..\tests\test_platform_config_and_extensions.py ..\tests\test_platform_adapters.py ..\tests\test_platform_bootstrap.py
```

GitHub Actions runs deterministic Phase 0 and Earth Perception regression
tests on Python 3.12 without enabling real model-download acceptance checks.
