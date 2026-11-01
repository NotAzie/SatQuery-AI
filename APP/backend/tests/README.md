# `backend/tests`

**Purpose.** Backend test suite, organized by unit, integration, contract, and architecture scope.

**Belongs here**
- `unit/` pure logic and Protocol conformance
- `integration/` app + real adapters against fakes of external systems
- `contract/` wire schemas (events, commands, OpenAPI) and drift against `contracts/schema.json`
- `architecture/` rules not expressible in import-linter

**Never here**
- Network calls to real LLM providers or a real Engine in CI
- Shared mutable fixtures across tests

**Depends on.** The package under test.

**Public interface.** `pytest` (asyncio mode on); layering is checked separately with `lint-imports`.
