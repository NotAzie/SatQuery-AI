# `src/features`

**Purpose.** User-facing capabilities, one folder each.

**Belongs here**
- `chat/`, `earth/` (camera, bookmarks, drawing, measurements, split view, Engine data discovery), `timeline/`, `vision/` (drop zone, paste, screenshots), `investigations/`, `monitoring/`, `sessions/`,
  `settings/`
- Each feature registers its panels via the plugin host, exactly as plugins do

**Never here**
- Cross-feature imports (share via `state/`, `services/` or `components/`)
- Cesium imports (use `useEarthController`)

**Depends on.** `components`, `hooks`, `services`, `state`, `plugins`, `shared`.

**Public interface.** Core panels are registered by `app/providers.tsx`; feature components and
typed API services provide their public interfaces.
