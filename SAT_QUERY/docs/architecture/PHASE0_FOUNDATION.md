# Core foundation in the current repository

Phase 0 provides shared local contracts and runtime mechanisms used by the
Earth observation and investigation paths. This is an implementation guide,
not a claim that the platform is production deployed. See [implementation
status](../IMPLEMENTATION_STATUS.md) and [system architecture](../foundation/SYSTEM_ARCHITECTURE.md).

## Implemented foundation

- Pydantic contracts for configuration, Earth queries/observations,
  provenance, capabilities, missions, investigations, Earth Objects, evidence,
  and execution.
- Named registries and Python extension discovery. Extensions run as trusted
  in-process Python; there is no sandbox.
- Validated configuration profiles, JSON configuration, environment
  overrides, and opt-in connector manifests.
- Async connector lifecycle, request context, bounded retries/timeouts,
  cache hooks, and streamed observations.
- Versioned investigation workflow compilation and dependency validation.
- Bounded local DAG execution, cancellation, per-task status, explicit
  retry-safety, partial results, event records, and SQLite checkpoint replay
  through registered codecs when fingerprints match.
- Structured logging and diagnostic endpoints, local cache interfaces,
  provider-neutral model/tool interfaces, and deterministic tests.
- Optional SQLite persistence for lifecycle, execution history, audit,
  memory, and monitoring; default stores remain in-memory.

## Runtime flow

`PlatformRuntime` composes registries, connectors, planner, investigation
repository, task handlers, execution journal, and platform services. The API,
CLI, and browser workspace call this composition. An investigation compiles to
a validated task DAG; task handlers acquire observations or produce explicit
Earth Object/evidence/diagnostic outputs. Compatibility image analysis is
integrated as a platform task but retains its optional model stack.

## Configuration boundary

`SATQUERY_PLATFORM_CONFIG` selects a JSON configuration file;
`SATQUERY_PLATFORM_PROFILE` chooses local/development/testing/production
defaults. Profiles change settings, not infrastructure. Environment overrides
use `SATQUERY_PLATFORM__SECTION__FIELD`. Connector loading is separately
opt-in through `SATQUERY_CONNECTORS_CONFIG`. Example manifests are not
automatically enabled.

## Not provided by this foundation

No distributed workers, remote queue, sandbox, multi-tenant authorization,
external cache, cloud deployment, secret manager, production backup strategy,
or enterprise availability guarantee is included. SQLite persistence is
single-host and does not provide distributed locking. Model and tool contracts
do not imply an active general-purpose model reasoning service. See
[deployment limitations](../deployment/README.md).

## Verification

Foundation behavior is covered across `test_config.py`,
`test_platform_contracts.py`, `test_platform_execution.py`,
`test_execution_journal.py`, `test_platform_bootstrap.py`, and related
integration tests. Commands and verification boundaries are maintained in the
[testing guide](../testing/TESTING_GUIDE.md).
