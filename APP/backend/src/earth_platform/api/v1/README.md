# `earth_platform/api/v1`

**Purpose.** Version 1 routers, one module per resource: chat, sessions, vision, earth, plugins, streams.

**Belongs here**
- Routes for that resource; each module exposes `router`

**Never here**
- Cross-resource logic
- Breaking changes (introduce `v2/` instead)

**Depends on.** `api.deps` and domain modules.

**Public interface.** Aggregated `router` mounted at `/api/v1`.
