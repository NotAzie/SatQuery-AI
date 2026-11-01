# `earth_platform/api`

**Purpose.** HTTP surface and request-scoped plumbing.

**Belongs here**
- Health probes, dependency providers (`deps.py`), error mapping, versioned routers under `v1/`

**Never here**
- Business logic: routes validate input, call a service, shape output
- Direct construction of components (take them from the container)

**Depends on.** `container` and all domain modules.

**Public interface.** `/healthz`, `/readyz`, `/api/v1/*`; OpenAPI at `/openapi.json`.
