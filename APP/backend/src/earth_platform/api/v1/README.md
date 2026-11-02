# `earth_platform/api/v1`

**Purpose.** Version 1 routers, one module per resource: chat, sessions, vision, earth, plugins,
streams, intelligence, and Engine-backed monitoring.

**Belongs here**
- Routes for that resource; each module exposes `router`
- Chat report and Earth Object GeoJSON reads scoped to investigation IDs in the linked Engine transcript
- Chat turn orchestration resolves optional session-owned image assets before Engine forwarding
- Monitoring mission/schedule management, optimistic schedule and trigger-policy revisions,
  trigger events, run history, comparisons, and notification acknowledgement proxied to Engine
- Typed Engine dataset, image-analysis, versioned Earth modality, and Agent tool discovery for the Earth workspace

**Never here**
- Cross-resource logic
- Breaking changes (introduce `v2/` instead)

**Depends on.** `api.deps` and domain modules.

**Public interface.** Aggregated `router` mounted at `/api/v1`.
The intelligence router exposes `GET /intelligence/engine-discovery` for Engine-validated dataset
metadata, image-analysis capability status, versioned Earth modality snapshot, and Agent tool
descriptors; unsupported or unavailable Engine responses surface as API errors rather than an empty
success response.
