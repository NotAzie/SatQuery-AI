# `src/earth/overlays`

**Purpose.** Transient Engine geometry rendered as Cesium data sources.

**Belongs here**
- `OverlayController` loads Engine-exported Earth Object GeoJSON, applies typed overlay commands,
  highlights matching evidence IDs, and clears owned data sources

**Never here**
- Persistent layers (see `layers/`)

**Depends on.** `cesium`, `shared`.

**Public interface.** `getState`, `onChange`, `onHighlightChange`, `add`, `showInvestigation`,
`highlight`, `clear`, `destroy`.

Investigation sources are generation-fenced so a source that finishes loading after clear or
replacement is not attached to the viewer. Session ownership is enforced by the chat API before a
GeoJSON response reaches this module; Cesium objects remain owned here and are released on clear or
controller teardown. The controller also exposes its current serializable GeoJSON overlay state and
evidence highlights so the primary viewport's EarthContext describes what is actually displayed.
