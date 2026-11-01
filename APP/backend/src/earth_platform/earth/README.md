# `earth_platform/earth`

**Purpose.** Server-side contracts for the globe: what the user sees and how the platform makes it react.

**Belongs here**
- `EarthContext`/`CameraState` (user -> agent)
- `EarthCommand` union (agent -> globe)
- `LayerSpec` and `LayerRegistry` (declarative layer catalogue)

**Never here**
- Cesium or any rendering code
- Computed geospatial results (reference Engine evidence by id)
- Layer tile serving

**Depends on.** `shared`.

**Public interface.** `EarthContext`, `EarthCommand`, `LayerSpec`, `LayerRegistry`.
