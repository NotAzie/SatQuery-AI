# `tests`

**Purpose.** Cross-stack end-to-end tests (browser + backend + Engine test double).

**Belongs here**
- `e2e/` Playwright specs when the UI exists

**Never here**
- Unit or integration tests (those live with each project)

**Depends on.** A running stack.

**Public interface.** `make e2e` (to be added).
