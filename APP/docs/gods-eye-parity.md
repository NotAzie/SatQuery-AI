# God's Eye View parity audit

## Scope and evidence

The original source at `C:\Users\mazin\gods-eye-view` is compared with the
vendored implementation at `APP/earth-view`. This matrix records the state
before the integration fixes below; it distinguishes source preservation from
runtime verification.

The recursive authored-file comparison excluded dependencies, build output,
caches, logs, backups, and private `.env` files. It found 1,624 source files and
1,627 vendored files: no source-only files, three vendored-only files
(`CHANGELOG.md`, `docs/CURRENT-STATE.md`, and
`src/tooling/apiNotFound.test.mjs`), and three content differences:

- `README.md`: updated for the SatQuery host.
- `server/standalone/api-not-found.js`: Platform API routing integration.
- `src/main.js`: startup/error events for the SatQuery host.

The original and integrated applications were both started in a browser. Each
exposed one live Cesium viewer, a `SceneDirector`, annotations, voice commands,
and the same 29 registered data layers. Their God’s Eye controls and first-run
flow were present in both. The integrated page additionally showed a separate
SatQuery command center over the native dock. The browser could not verify live
provider results or Platform-backed project/session workflows; the Platform
API was unavailable during the prior smoke test.

## Parity matrix

Each row has exactly one status from the requested classification set. “Fully
migrated” means the source implementation is present and the stated browser
check succeeded; it does not claim that an external provider was reachable.

| Feature | Status | Evidence / difference |
|---|---|---|
| Application HTML and God’s Eye template assembly | Fully migrated | All nine source template sections are assembled into the SatQuery page. |
| God’s Eye startup and runtime initialization | Replaced intentionally | The standalone startup is retained and extended to signal readiness/failure to SatQuery. |
| God’s Eye component lifecycle and teardown | Fully migrated | `createStandaloneApplication` and its source lifecycle code are unchanged. |
| Cesium viewer creation and runtime ownership | Fully migrated | Browser inspection found one live viewer in each app. |
| Render governor and visibility suspension | Fully migrated | Source modules are unchanged; runtime initializes with the GEV application. |
| Browser build, provider middleware, and local MCP routes | Partially migrated | GEV Vite builder/plugins are composed into the frontend build; production behavior was not exercised. |
| React hot reload | Replaced intentionally | Disabled because the GEV content-security policy blocks React Fast Refresh's inline preamble. |
| Node package scripts and QA harness entry points | Partially migrated | GEV package files remain vendored, but the host frontend does not expose all standalone scripts as frontend commands. |
| Provider credential setup and settings UI | Partially migrated | GEV’s native setup surface remains and is opened through an explicit runtime action; its setup endpoint is available only in supported development deployments. |
| `/api/v1` Platform routing | Replaced intentionally | SatQuery’s typed Platform API is used instead of GEV's standalone not-found response. |
| Location search, presets, POIs, and camera navigation | Fully migrated | Native controls are present; source modules are unchanged. |
| Globe zoom, tilt, north reset, orbit, full-globe reset, and presentation mode | Fully migrated | Native globe-action controls are present in both browser runs. |
| Camera telemetry and share-link restoration | Fully migrated | Native controls and URL state are present; GEV owns active navigation. |
| Mouse gestures, entity picking, and camera interaction | Partially migrated | GEV interactions are retained, but SatQuery adds a second `ScreenSpaceEventHandler` to the same canvas. |
| Keyboard shortcuts and command-dock keyboard behavior | Fully migrated | GEV shortcut and surface-keyboard modules are unchanged. |
| Native command dock, drawers, rails, and responsive layout | Partially migrated | The GEV dock is present, but the SatQuery AI surface is a separate fixed overlay rather than a dock feature. |
| First-run mission chooser and onboarding | Fully migrated | Native dialog and its four choices are present in the integrated browser. |
| Visual presets and post-processing | Fully migrated | Preset controls/modules are unchanged and present. |
| Imagery provider selection and map-source tray | Fully migrated | Native source tray and provider modules are present. |
| Terrain and 3D-tiles providers | Partially migrated | Provider code and settings are present; credential-dependent provider switching was not exercised. |
| Atmospheric, lighting, and celestial rendering | Fully migrated | Source implementation is unchanged and runs with the integrated viewer. |
| Aircraft and live flight data | Partially migrated | Flights layer is registered; live data arrival and aircraft rendering were not verified. |
| Military flights, awareness, and installations | Partially migrated | All three layers are registered; provider data and interaction were not verified. |
| Local ADS-B | Partially migrated | Layer is registered; local receiver/device data was not available for verification. |
| AIS vessels | Partially migrated | Layer is registered; live AIS results were not verified. |
| Satellites and orbital visualization | Partially migrated | Layer is registered; feed results and camera interaction were not verified. |
| Rocket launches and space missions | Partially migrated | Layer is registered; provider results were not verified. |
| Earthquakes | Partially migrated | Layer is registered; live feed rendering was not verified. |
| Wildfires and fire perimeters | Partially migrated | FIRMS/perimeter layers are registered; live feed rendering was not verified. |
| Weather: wind, radar, satellite, lightning, and cyclones | Partially migrated | All five layers are registered; external weather data/rendering was not verified. |
| Traffic and road-network visualization | Partially migrated | Traffic layer is registered; browser status remained at 0% during the comparison. |
| Transit and bikeshare | Partially migrated | Both layers are registered; network/provider results were not verified. |
| CCTV and ALPR cameras | Partially migrated | Both layers are registered; camera feeds and configuration were not verified. |
| Radio and local SDR controls | Partially migrated | Radio layer and controls are present; hardware/browser-device workflows were not verified. |
| Directions and route overlays | Partially migrated | Layer and source code are present; external routing behavior was not verified. |
| Recent imagery and imagery-box workflow | Partially migrated | Layer/tool code is present; imagery provider and box workflow were not exercised. |
| Submarine cables | Partially migrated | Layer is registered; dataset rendering was not separately exercised. |
| Local data centers and dams | Partially migrated | Both layers are registered; visualization was not separately exercised. |
| Local FIRMS | Partially migrated | Layer is registered; local dataset workflow was not separately exercised. |
| Bhote Koshi scenario and locator | Partially migrated | Both layers and scene attachment are present; scenario workflow was not exercised. |
| CCTV calibration and camera presentation | Fully migrated | Source modules and controls remain present. |
| Scene presets, playback, and scene sharing | Fully migrated | Native `SceneDirector` and scene controls are present in both runtimes. |
| Draw, manual annotations, and annotation persistence | Partially migrated | GEV annotation engine is present; SatQuery separately renders persisted drawings through another viewer controller. |
| Distance, area, coordinate, and elevation measurement | Partially migrated | GEV tools are preserved; SatQuery also creates an unused second interaction controller. |
| Display controls, cockpit instruments, and HUD | Fully migrated | Native rails, telemetry, and HUD runtime are present. |
| Voice control and voice-command workflows | Fully migrated | GEV voice command runtime is present in both browser instances. |
| GEV command execution and tool registration | Fully migrated | Native command and voice-tool modules are unchanged. |
| GEV settings, scenes, layer panels, and provider dialogs | Fully migrated | Native settings/templates remain in the integrated page. |
| Data attribution and source credits | Fully migrated | Cesium ion and Esri attribution are visible in the integrated browser. |
| SatQuery projects, sessions, investigations, and Engine | Superseded by SatQuery | These are Platform/Engine capabilities, not GEV features; the existing routes, typed API, and workflows remain in SatQuery. |
| SatQuery investigation geometry and evidence overlays | Partially migrated | Engine geometry is rendered on the GEV viewer, but its presentation is still owned by SatQuery's Earth overlay controller. |
| SatQuery saved Earth views and session context | Partially migrated | Persistence remains in the SatQuery session model and restores through extra controllers on the GEV viewer. |
| SatQuery AI command center | Partially migrated | Chat, Engine commands, reports, and image attachments remain functional surfaces, but the center is visually and structurally separate from GEV's dock. |
| SatQuery workspace drawer | Partially migrated | Product workflows remain available on demand, but the drawer is not yet a native GEV panel. |
| GEV test suite and package-boundary checks | Partially migrated | Source tests are present; the earlier full run had four upstream failures and four cancellations unrelated to copied-source omissions. |

## Remediation follow-up

- The SatQuery command center now portals into a dedicated mount in God’s Eye's
  native command dock; its expanded conversation opens from that dock.
- EarthStage now consumes the exported `applicationReady` promise directly.
  Custom DOM readiness/error events and startup-global polling were removed.
- The SatQuery workspace creates a Cesium screen-space handler only while an
  explicit drawing/measurement operation is active. Entity selection follows
  the viewer's native selection event.
- The command notch opens God's Eye provider settings through a typed runtime
  action rather than querying and clicking a DOM element.
- SatQuery persistence and Engine contracts remain in place. Live provider
  results, configured credential paths, and production API deployment still
  require a configured runtime for end-to-end verification. The on-demand
  Platform workspace drawer remains a product-level surface rather than an
  Earth-specific GEV panel.
