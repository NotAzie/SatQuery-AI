# `src/services/api`

**Purpose.** Typed REST client and error normalisation.

**Belongs here**
- `client.ts`; later per-resource modules (`sessions.ts`, `vision.ts`)

**Never here**
- State

**Depends on.** `shared`.

**Public interface.** `apiFetch<T>`, `apiUrl`, `ApiError`.
