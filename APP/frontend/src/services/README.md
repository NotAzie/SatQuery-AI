# `src/services`

**Purpose.** Everything that talks to the backend. No React.

**Belongs here**
- `api/` typed HTTP client
- `stream/` `StreamClient` contract and its SSE/WebSocket implementations

**Never here**
- React components or hooks
- Business rules

**Depends on.** `shared`.

**Public interface.** `apiFetch`, `ApiError`, `StreamClient`.
