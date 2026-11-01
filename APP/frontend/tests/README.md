# `tests`

**Purpose.** Frontend test setup and cross-module tests; unit tests are colocated as `*.test.ts(x)` beside the code.

**Belongs here**
- Vitest setup, shared fixtures, reducer/contract tests

**Never here**
- Real network calls

**Depends on.** Code under test.

**Public interface.** `npm test`.
