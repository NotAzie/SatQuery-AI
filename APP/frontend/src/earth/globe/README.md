# `src/earth/globe`

**Purpose.** Attach Platform Earth controllers to the single God's Eye viewer.

**Belongs here**
- `EarthStage`, the runtime attachment lifecycle

**Never here**
- A second viewer constructor or viewer-owned data rendering

**Depends on.** God's Eye's `APP/earth-view` runtime, `EarthController`, `state`.

**Public interface.** `EarthStage`. It does not create or destroy a second Cesium viewer; it
awaits God's Eye's exported startup promise, connects SatQuery camera, layer, timeline, overlay,
capture, and workspace controllers to God's Eye's page-owned viewer, and reports startup failures
explicitly.
