# `src/state`

**Purpose.** Global client state (Zustand), small stores by concern.

**Belongs here**
- `earthStore` (what the user is looking at), `sessionStore` (active session)

**Never here**
- Server cache duplicated verbatim
- Cesium objects

**Depends on.** `shared`.

**Public interface.** `useEarthStore`, `snapshotEarthContext`, `useSessionStore`. The Earth
snapshot reflects serializable camera, timeline, selection, and drawing state. Camera history and
bookmarks are scoped to a Platform session, cached in browser storage, and synchronized through
the existing SQLite-backed session API. The current Engine Agent API does not accept EarthContext.
