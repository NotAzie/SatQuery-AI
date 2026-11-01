# `earth_platform/shared`

**Purpose.** Dependency-free primitives every module may use.

**Belongs here**
- Id helpers, clock, error taxonomy, generic `Registry[T]`
- Neutral value types: `geo` (LngLat, BoundingBox, TimeRange), `earth` (serializable EarthContext,
  selection, drawings, camera history and bookmark contracts), `messages` (conversation content)
- Constants such as wire-schema versions

**Never here**
- Imports from any other platform module
- Anything with I/O or global state
- Feature logic, or geometry/science computation (that is the Engine's job)

**Depends on.** Standard library and pydantic only.

**Public interface.** `Registry`, `PlatformError` and subclasses, `Message`/`ContentPart`,
`BoundingBox`/`TimeRange`, `EarthContext`/`EarthWorkspaceState`, `new_id`.
