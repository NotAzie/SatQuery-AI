# `src/services/api`

**Purpose.** Typed REST client and error normalisation.

**Belongs here**
- `client.ts` and typed per-resource modules (`chat.ts`, `sessions.ts`, `vision.ts`,
  `monitoring.ts`, `engineDiscovery.ts`); chat reads Engine-authored reports and investigation-scoped Earth Object GeoJSON,
  while monitoring calls proxy Engine-owned mission and schedule operations, including
  revision-checked schedule definition and trigger-policy edits; Engine discovery reads registered
  dataset metadata, image-analysis capability status, and versioned Earth modality and Agent tool
  snapshots

**Never here**
- State

**Depends on.** `shared`.

**Public interface.** `apiFetch<T>`, `apiUrl`, `ApiError`.
