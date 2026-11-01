# `src/features`

**Purpose.** User-facing capabilities, one folder each.

**Belongs here**
- `chat/`, `earth/` (camera, bookmarks, drawing, measurements, split view), `timeline/`, `vision/` (drop zone, paste, screenshots), `investigations/`, `sessions/`,
  `settings/`
- Each feature registers its panels via the plugin host, exactly as plugins do

**Never here**
- Cross-feature imports (share via `state/`, `services/` or `components/`)
- Cesium imports (use `useEarthController`)

**Depends on.** `components`, `hooks`, `services`, `state`, `plugins`, `shared`.

**Public interface.** Each feature exports a `register(host)` function (convention) and its public types.
