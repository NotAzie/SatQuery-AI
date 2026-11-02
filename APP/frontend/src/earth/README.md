# `src/earth`

**Purpose.** Everything Cesium. The rest of the app talks to the globe only through `EarthController`.

**Belongs here**
- `globe/` viewer lifecycle, `camera/`, `layers/`, `timeline/`, `workspace/` picking/drawings/measurements, `overlays/`, `investigations/`, `capture.ts`, `controller.ts`, `EarthProvider`
- Typed `earth.command` dispatch from streamed server events to workspace controllers

**Never here**
- Chat, session or network logic
- Constructing commands from chat text, model output, or scientific-result heuristics
- Importing `cesium` anywhere outside this folder

**Depends on.** `shared`, `state` (camera mirror).

**Public interface.** `EarthController` (`camera`, `commands`, `overlays`, `timeline`, `workspace`, `events`, `capture`), `EarthCommandDispatcher`, `EarthCommandHandlers`, `EarthEventBus`, `EarthProvider`, `EarthStage`. Serializable viewport and overlay changes are published through the Earth event bus for EarthContext snapshots. Cesium-only types and objects remain within this module.

The viewer uses Cesium request-render mode so an idle workspace does not continuously redraw.
Application-owned entity mutations explicitly request a frame; Cesium's clock and camera changes
continue to request frames during timeline playback and navigation.
