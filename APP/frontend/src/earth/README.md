# `src/earth`

**Purpose.** Platform EarthContext, Engine command/overlay integration, and shared-viewer attachment.
God's Eye owns the rendered Earth workspace and user-facing Earth interactions; SatQuery attaches
typed Platform/Engine behavior to the same Cesium viewer and consumes its startup promise directly.

**Belongs here**
- `globe/` runtime attachment, `integration/` same-page God's Eye runtime and layer adapter, `camera/`, `layers/`, `timeline/`, `workspace/` serializable EarthContext support, `overlays/`, `investigations/`, `capture.ts`, `controller.ts`, `EarthProvider`
- Typed `earth.command` dispatch from streamed server events to workspace controllers

**Never here**
- Chat, session or network logic
- Constructing commands from chat text, model output, or scientific-result heuristics
- Importing `cesium` anywhere outside this folder

**Depends on.** `shared`, `state` (camera mirror).

**Public interface.** `EarthController` (`camera`, `commands`, live data layers, `overlays`, `timeline`, `workspace`, `events`, `capture`), `EarthCommandDispatcher`, `EarthCommandHandlers`, `EarthEventBus`, `EarthProvider`, `EarthStage`. The shared viewer remains God’s Eye-owned; SatQuery does not mount its former Earth toolbar or timeline/workspace panels. The AI command notch is mounted in God's Eye's native command dock. The typed controller remains for Platform context persistence and Engine commands/overlays; canvas handlers are created only during explicit SatQuery drawing or measurement operations, and selection follows Cesium's native viewer event. SatQuery never creates a competing globe or destroys the shared viewer.

The viewer uses Cesium request-render mode so an idle workspace does not continuously redraw.
Application-owned entity mutations explicitly request a frame; Cesium's clock and camera changes
continue to request frames during timeline playback and navigation.
