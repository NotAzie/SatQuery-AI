# `src/features/earth`

**Purpose.** User-facing Earth workspace controls: camera undo/redo, session bookmarks, drawing and
measurement actions, selection display, and split-view preferences.

**Belongs here**
- Panel UI and user input for EarthController operations
- Presenting local workspace errors and measurement results

**Never here**
- Cesium imports or scene manipulation
- Scientific calculations outside the Earth workspace controller
- Starting Engine investigations from drawings or measurements

**Public interface.** `WorkspaceToolsPanel`, registered in the shared panel host.
