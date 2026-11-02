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

**Public interface.** `WorkspaceToolsPanel` and `EngineDiscoveryPanel`, registered in the shared
panel host. Engine discovery displays Engine-authored registered dataset metadata and
image-analysis capability status, the versioned Earth modality snapshot, and registered Agent tool
schemas through the Platform's typed discovery endpoint. It displays consent visibility and does
not invoke tools. Dataset registrations do not guarantee data access or scientific suitability.
