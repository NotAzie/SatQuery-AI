# `src/app`

**Purpose.** Application shell: bootstrap, providers, routing, layout.

**Belongs here**
- `App`, `providers.tsx`, `router.tsx`, `layout/AppShell`, `routes/*` (thin: select state, render nothing heavy)

**Never here**
- Feature logic (goes in `features/`)
- Cesium code (goes in `earth/`)

**Depends on.** `earth`, `plugins`, `state`.

**Public interface.** `<App />`.
