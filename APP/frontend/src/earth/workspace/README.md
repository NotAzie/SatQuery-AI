# `src/earth/workspace`

**Purpose.** Own globe interaction and local Earth presentation behavior: selecting entities,
creating GeoJSON drawings, and measuring coordinates, distance, area, and locally available terrain
height.

**Belongs here**
- Cesium picking, screen-space input handlers, and entity rendering
- GeoJSON geometry creation and local measurement algorithms
- Serializable drawing/selection/measurement contracts and tests

**Never here**
- Scientific interpretation, evidence generation, investigation execution, or Engine calls
- Cesium objects in shared state or feature components
- Treating a missing terrain height as zero or as a scientific result

**Public interface.** `EarthWorkspaceController`, exposed as `EarthController.workspace`. Typed
selection, drawing, and measurement events publish through `EarthController.events`.
