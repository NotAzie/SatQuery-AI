# `src/earth/timeline`

**Purpose.** Own the Cesium clock adapter and typed time-axis contract for the Earth workspace.
God's Eye owns the user-facing Earth time controls; SatQuery does not mount a competing timeline panel.

**Belongs here**
- Cesium clock integration and playback state
- Temporal range and instant validation

**Never here**
- Scientific date selection or claims about observation availability
- Automatically submitting time changes to the Engine

**Depends on.** `cesium`, `shared`.

**Public interface.** `TimelineController`, exposed through `EarthController.timeline`: `setInstant`,
`setRange`, `play`, `pause`, `getState`, and `onChange`. The controller updates Cesium's
presentation clock and shared EarthContext. Time selection remains local until the Engine defines a
supported context input or emits a typed time command.
