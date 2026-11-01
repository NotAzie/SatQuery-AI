# `plugins`

**Purpose.** First-party and example plugins, each an independent package using only the public plugin API.

**Belongs here**
- One folder per plugin with its own `pyproject.toml` (entry point group `earth_platform.plugins`) and optional frontend bundle

**Never here**
- Imports of platform internals beyond `earth_platform.plugins.api`
- Core features (those live in the backend and frontend)

**Depends on.** `earth_platform.plugins.api`, `frontend/src/plugins/types.ts`.

**Public interface.** See `docs/plugins.md`.
