# SatQuery style guide

The repository uses Python 3.10+ syntax and Pydantic v2 contracts. Keep
implementation detail in the subsystem that owns it; expose stable typed
contracts at subsystem boundaries.

## Python

- Use type annotations for public functions, protocols, and persisted
  contracts. Prefer built-in generic types and `T | None`.
- Use immutable dataclasses for validated configuration snapshots and
  Pydantic `Contract` models for serialized platform data.
- Name provider-specific data explicitly (`source_document`, source metadata,
  provider identity). Do not silently present provider values as canonical
  variables or units.
- Keep connector/network code in `connectors/` and orchestration in
  `satquery/platform/`; avoid importing connector packages from canonical
  contracts or scientific operators.
- Catch expected errors at boundaries. Preserve actionable error types and
  context; do not swallow failures or convert unknown output to success.
- Never put credentials, signed URLs, or private user data in logs, fixtures,
  docs, or committed configuration.

## Scientific records

- Represent unknown metadata as absent/unknown, not zero, false, or an
  invented confidence value.
- Retain units, CRS, temporal extent, spatial support, source identifiers,
  uncertainty as reported, and method/version identity.
- Diagnostics must be labeled as diagnostics. Deterministic arithmetic is not
  automatically a scientific method, validation, significance test, or causal
  explanation.
- A scientific method requires its references, applicability, assumptions,
  limitations, inputs, output semantics, uncertainty treatment, and independent
  validation artifacts before it can be treated as validated.

## Tests and documentation

- Prefer deterministic injected HTTP transports, temporary SQLite files, and
  explicit clocks over live services or wall-clock assumptions.
- Test failure, partial, conflict, restart, and unknown-metadata paths as well
  as successful paths.
- Put user-facing behavior in the API/CLI/workspace docs and architecture
  boundaries in `docs/architecture/`. Update the current implementation map
  when a capability becomes available or changes status.
- Run focused pytest modules from `satquery-ai/`. Ruff is optional and is not
  currently part of the configured CI gate; if installed, use it as an
  additional check. See the
  [testing guide](../testing/TESTING_GUIDE.md) for full-suite and optional
  acceptance commands.
