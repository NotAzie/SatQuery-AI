# Contributing to SatQuery

SatQuery's goal is trustworthy Earth observation and investigation. Read the
[current implementation status](../IMPLEMENTATION_STATUS.md) before choosing a
task; the roadmap describes direction and does not mean a capability is
already available.

## Before changing code

1. Work from the repository root, then run application commands from
   `satquery-ai/`.
2. Check the canonical module and its existing contracts before adding a new
   abstraction. The composition root is `satquery.platform.runtime.PlatformRuntime`;
   API and CLI behavior should use the same runtime when applicable.
3. Identify whether a requested scientific result is merely operational,
   descriptive, or validated inference. Keep those categories distinct.
4. Check provider and dataset metadata, source licensing, query scope, and
   uncertainty semantics. Preserve original source metadata and never fill
   unknown fields with guessed values.

## Change requirements

- Keep external providers behind connector interfaces and return canonical
  contracts.
- Preserve observation, object, and method lineage. Do not turn an explicit
  source class into a validated detection without independent evidence.
- Make retries explicit and safe for acquisition side effects. Keep unknown
  execution outcomes visible.
- Add deterministic fixture-based tests for contracts, failure paths, and
  reproducibility. Live-provider and model tests must be opt-in.
- Update the API reference, CLI/workspace examples, and the relevant
  architecture page when behavior changes. Update
  [implementation status](../IMPLEMENTATION_STATUS.md) when the capability
  boundary changes.
- Do not add scientific benchmarks or claim certification without owner-supplied
  reference data and documented validation.

## Verification

From `satquery-ai/`, run focused test modules and any static checks configured
for the changed code. Ruff is not currently pinned in project dependencies or
the GitHub Actions workflow; if using it locally, install it explicitly and
report the command. The complete deterministic suite is:

```powershell
python -m pytest -c pyproject.toml -m "not real_acceptance"
```

Run opt-in model acceptance only when its weights and environment are
available. The checked-in GitHub Actions workflow runs a selected deterministic
subset; a local full-suite pass is not a scientific certification or a
production deployment sign-off.

## Pull request notes

Describe user-visible behavior, the evidence semantics, exact limitations,
configuration changes, and commands actually run. Call out any compatibility
change. Do not report tests, live acquisitions, benchmarks, or deployments
that were not run.
